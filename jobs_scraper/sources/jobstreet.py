"""JobStreet SG source adapter.

Owns the JobStreet public job API: the list API URL, the list-page parsing,
the GraphQL JD fetch, and the multi-keyword crawl (the list API accepts a
single keyword per request, so the crawl issues one request per keyword and
de-duplicates by `job_id` across keywords).

The module holds no global state. The HTTP session and the sleep function are
injected by the caller, so every function here can be exercised without
touching the network — and the 30/60/90s list-page retry ladder stays
observable.

`sg_product_jobs.py` keeps the public `*_jobstreet_*` names as thin wrappers
that pass its own session, sleep and helpers down, so callers and tests that
patch those module attributes keep working unchanged.
"""

from __future__ import annotations

import os
import re
import time
import urllib.parse
from typing import Callable

from bs4 import BeautifulSoup

SOURCE = "jobstreet"

BASE = "https://sg.jobstreet.com"
LIST_API = "https://sg.jobstreet.com/api/jobsearch/v5/search"
GRAPHQL = "https://sg.jobstreet.com/graphql"

#: JobStreet full-time work type id.
WORKTYPE_FT = "242"
LOCATION = "Singapore"

#: list API page size (also the reference size for the 50% soft stop).
PAGE_SIZE = 20

#: A page that adds fewer new jobs than this counts as the end of the results.
SOFT_STOP_MIN_NEW = 10

#: Retry backoff (seconds) for a list page. Mirrors LinkedIn's ladder, which
#: was added on 2026-10-07 after a 429 hard abort truncated long-range coverage.
BACKOFF = [30, 60, 90]

#: range → API `daterange` query value.
TPR = {
    "1h": "1",
    "24h": "1",
    "3d": "3",
    "7d": "7",
    "14d": "14",
    "21d": "21",
    "30d": "30",
}

# MAX_PAGES 跟 LinkedIn 一樣 (邏輯都跟 LinkedIn 一樣), 50% 軟停由 crawl_list 跑時判斷
# 預期覆蓋 (product manager + FT + 5 keyword + dedup):
# 1d=1 / 3d=7*20=140 raw → ~80 unique / 7d=15*20=300 → ~200 / 14d=30*20=600 → ~400 / 30d=25*20=500 → ~350
# 7d 的 totalCount 是 953, 5 keyword × 15 page × 20 = 1500 raw, 預期 unique ~600
MAX_PAGES = {
    "1h": 1,
    "24h": 4,
    "3d": 7,
    "7d": 15,
    "14d": 30,
    "21d": 30,
    "30d": 25,
}

DEFAULT_KEYWORDS = [
    "product manager",
    "product director",
    "director of product",
    "head of product",
    "product lead",
]

DETAIL_QUERY = """
query getJobDetails($jobId: ID!) {
  jobDetails(id: $jobId) {
    job {
      id
      title
      abstract
      content
      status
      isExpired
      createdAt { dateTimeUtc }
      updatedAt { dateTimeUtc }
      expiresAt { dateTimeUtc }
      advertiser { id name }
      location { label }
      workTypes { label }
    }
  }
}
"""

#: GraphQL detail request headers.
DETAIL_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def keywords(override: str | None = None) -> list[str]:
    """The keyword set, overridable with the ``JOBSTREET_KEYWORDS`` env var.

    Args:
        override: the raw ``JOBSTREET_KEYWORDS`` value (comma separated).
            ``None`` reads the environment at call time; an empty string means
            "no override" and yields the defaults.
    """
    raw = os.getenv("JOBSTREET_KEYWORDS", "") if override is None else override
    if raw:
        return [k.strip() for k in raw.split(",") if k.strip()]
    return list(DEFAULT_KEYWORDS)


def _keywords_from_env() -> list[str]:
    """The keyword set as configured by the environment."""
    return keywords()


def build_list_url(
    keyword: str,
    page: int,
    daterange: str,
    worktype: str = WORKTYPE_FT,
    where: str = LOCATION,
    page_size: int = PAGE_SIZE,
) -> str:
    """組 JobStreet list API URL。"""
    params = {
        "siteKey": "SG-Main",
        "keywords": keyword,
        "where": where,
        "worktype": worktype,
        "daterange": str(daterange),
        "page": str(page),
        "pageSize": str(page_size),
    }
    return f"{LIST_API}?{urllib.parse.urlencode(params)}"


def parse_list_page(data: dict, keyword: str) -> list[dict]:
    """從 JobStreet list API JSON 抓 jobs。"""
    jobs_raw = data.get("data") or []
    out = []
    for j in jobs_raw:
        jid = j.get("id")
        if not jid:
            continue
        # 公司優先用 employer.name, 退到 advertiser.description
        emp = j.get("employer") or {}
        adv = j.get("advertiser") or {}
        company = emp.get("name") or adv.get("description") or j.get("companyName") or ""
        # locations → 用第一個 label
        locs = j.get("locations") or []
        loc_label = locs[0].get("label", "") if locs else ""
        # workArrangements (Remote / Hybrid / Onsite) — 2026-08-23 統一 "Onsite" 沒 hyphen
        wm = ""
        wa = (j.get("workArrangements") or {}).get("data") or []
        if wa and isinstance(wa, list) and wa[0].get("label"):
            wm = wa[0]["label"].get("text", "")
            wm = wm.replace("On-site", "Onsite")  # JobStreet API 給 "On-site" 統一轉 "Onsite"
        out.append(
            {
                "job_id": str(jid),
                "title": j.get("title", ""),
                "company": company,
                "location": loc_label,
                "posted_at": j.get("listingDate", ""),
                "posted_ago": j.get("listingDateDisplay", ""),
                "work_mode": wm,
                "teaser": j.get("teaser", ""),
                "url": "",  # 不在 list 階段組, enrich 階段補 (要用 title slug)
                "keyword_used": keyword,  # debug 用, 哪個 keyword 撈到的
                "source": SOURCE,
            }
        )
    return out


def fetch_jd(job_id: str, *, session) -> dict:
    """打 GraphQL 拿單一職缺完整 content (HTML JD), BS4 轉純文字。

    `session` is injected so the caller controls the HTTP client.
    """
    try:
        r = session.post(
            GRAPHQL,
            json={"query": DETAIL_QUERY, "variables": {"jobId": str(job_id)}},
            headers=dict(DETAIL_HEADERS),
            timeout=30,
            impersonate="chrome",
        )
    except Exception as e:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": str(e),
        }
    if r.status_code != 200:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"HTTP {r.status_code}",
        }
    try:
        data = r.json()
    except Exception as e:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"JSON fail: {e}",
        }
    if "errors" in data:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": str(data["errors"][:1]),
        }
    job = (data.get("data") or {}).get("jobDetails", {}).get("job")
    if not job:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": "no job in response",
        }
    # content (HTML) → plain text
    content_html = job.get("content") or ""
    if content_html:
        soup = BeautifulSoup(content_html, "html.parser")
        jd_text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()
        jd_lines = [t.strip() for t in soup.stripped_strings if len(t.strip()) > 1]
    else:
        jd_text = None
        jd_lines = None
    # 公司/位置 fallback (從 GraphQL 補)
    adv = job.get("advertiser") or {}
    loc = job.get("location") or {}
    return {
        "jd_text": jd_text,
        "jd_lines": jd_lines,
        "jd_html": content_html or None,
        "company": adv.get("name", ""),
        "location": (loc.get("label") if isinstance(loc, dict) else "") or "",
        "title": job.get("title", ""),
        "error": None if jd_text else "empty JD",
    }


def _no_sleep(label: str = "") -> None:
    """Default pacing hook — the engine injects its own `human_sleep`."""
    return None


class FatalListPageError(RuntimeError):
    """A list page failure that must not be retried.

    Raised for 4xx responses other than 429: those are caller bugs (a wrong
    query or a blocked request), not transient network trouble, so spending
    three minutes of backoff on them would only delay the failure.
    """


def fetch_list_page(
    keyword: str,
    page: int,
    daterange: str,
    worktype: str = WORKTYPE_FT,
    *,
    session,
    sleep_seconds: Callable[[float], None] = time.sleep,
    build_url: Callable[..., str] = build_list_url,
) -> dict:
    """JobStreet list page with a 30/60/90s retry ladder (mirrors LinkedIn).

    2026-10-31 fix: the list page had no retry at all. Any failure — a
    connection error, a non-200 status or a JSON decode error — returned from
    ``crawl_list`` immediately, which aborted the whole keyword crawl. When the
    very first page failed the crawl produced zero jobs, ``main()`` printed
    "無資料，結束" and exited 0, so the caller saw a *successful* run that had
    silently collected nothing (real instance: 2026-10-30, the 7d run's first
    page hit curl error 56 and wrote no rows while still exiting 0).

    429 / 5xx / connection error / JSON decode error → sleep 30/60/90s → retry
    (4 attempts in total). Other 4xx → `FatalListPageError`, no retry.

    Raises:
        FatalListPageError: non-retryable 4xx response.
        RuntimeError: every retry was exhausted.
    """
    backoff = BACKOFF
    last_err = None
    url = build_url(keyword, page, daterange, worktype=worktype)
    for attempt in range(4):
        try:
            r = session.get(url, timeout=20, impersonate="chrome")
            if r.status_code == 200:
                try:
                    return r.json()
                except Exception as e:
                    last_err = f"JSON {type(e).__name__}: {str(e)[:50]}"
            elif r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                raise FatalListPageError(f"jobstreet list fetch failed: http {r.status_code}")
        except FatalListPageError:
            raise
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < 3:
            print(
                f"  [JOBSTREET LIST RETRY {attempt + 1}/3] {keyword} p{page} 失敗 ({last_err}), "
                f"sleep {backoff[attempt]}s",
                flush=True,
            )
            sleep_seconds(backoff[attempt])
    raise RuntimeError(f"jobstreet list fetch failed after 4 attempts: {last_err}")


def crawl_list(
    daterange: str,
    max_pages: int,
    keywords: list[str] | None = None,
    worktype: str = WORKTYPE_FT,
    *,
    session,
    sleep: Callable[[str], None] = _no_sleep,
    sleep_seconds: Callable[[float], None] = time.sleep,
    build_url: Callable[..., str] = build_list_url,
    parse_page: Callable[[dict, str], list[dict]] = parse_list_page,
) -> list[dict]:
    """跑多個 keyword 的 JobStreet list, 跨 keyword dedup。回傳 unique jobs。

    50% 軟停: 某頁 unique new jobs < pageSize * 0.5 就視為到尾。

    每個 list page 走 `fetch_list_page`, 內含 30/60/90s retry ladder:
    瞬時的 429 / 5xx / connection error 不會再讓整個 keyword crawl 直接中止,
    coverage 不會被靜默砍掉 (2026-10-31 fix)。

    `session`, `sleep`, `sleep_seconds`, `build_url` and `parse_page` are injected
    so the caller decides which implementation runs (and so tests can substitute
    their own).
    """
    if keywords is None:
        keywords = _keywords_from_env()
    seen: set[str] = set()
    all_jobs: list[dict] = []
    for kw in keywords:
        kw_seen: set[str] = set()
        for p in range(1, max_pages + 1):
            try:
                data = fetch_list_page(
                    kw,
                    p,
                    daterange,
                    worktype=worktype,
                    session=session,
                    sleep_seconds=sleep_seconds,
                    build_url=build_url,
                )
            except RuntimeError as e:
                print(f"  [jobstreet {kw} p{p}] FAIL: {e}")
                return all_jobs
            jobs = parse_page(data, kw)
            new_jobs = [j for j in jobs if j["job_id"] not in seen and j["job_id"] not in kw_seen]
            for j in new_jobs:
                kw_seen.add(j["job_id"])
                seen.add(j["job_id"])
                all_jobs.append(j)
            total_count = data.get("totalCount", "?")
            print(
                f"  [jobstreet {kw} p{p}] 收 {len(jobs):3} | 新增 {len(new_jobs):3} | "
                f"kw 累計 {len(kw_seen):3} | 跨 kw 累計 {len(all_jobs):3} | totalCount={total_count}"
            )
            # 50% 軟停
            if not new_jobs or len(new_jobs) < SOFT_STOP_MIN_NEW or len(jobs) == 0:
                print("            50% 軟停 (新增 < 10 或 jobs 空)")
                break
            if p < max_pages:
                sleep("list")
    return all_jobs
