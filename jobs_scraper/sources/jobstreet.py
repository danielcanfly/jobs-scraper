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
import random
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

#: A keyword page that yields fewer *fresh* jobs than this counts as the end of
#: that keyword's results.
#:
#: 2026-11-23 v1.6.8 fix: the soft stop used to measure the jobs that were new to
#: the whole crawl, not to the keyword. Every keyword after the first therefore
#: saw almost nothing "new" on its first page and stopped there, so a five-
#: keyword crawl really crawled one keyword. The signal is now measured per
#: keyword, against the keyword's own results.
SOFT_STOP_MIN_FRESH = 10

#: Retry backoff (seconds) for a list page. Mirrors LinkedIn's ladder, which
#: was added on 2026-10-07 after a 429 hard abort truncated long-range coverage.
BACKOFF = [30, 60, 90]


def _sleep_range_from_env(prefix: str, default_min: float, default_max: float) -> tuple[float, float]:
    """讀 env 的 sleep 區間; 沒設或格式錯就用預設值。"""
    try:
        lo = float(os.environ.get(f"JOBS_SCRAPER_{prefix}_SLEEP_MIN", default_min))
        hi = float(os.environ.get(f"JOBS_SCRAPER_{prefix}_SLEEP_MAX", default_max))
    except ValueError:
        lo, hi = default_min, default_max
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


# v1.8.0: JobStreet 的請求節奏 (2026-11-24 實測純網路只要 0.29-0.80s,
# 舊的 3-10s sleep 讓 wall time 有 80% 是等待)。
# 壓力測試: 0.5s sleep / 200 reqs = 0 fail; 0.1s (10 req/s) / 100 reqs = 0 fail。
# JobStreet 的公開 list API + GraphQL 對壓力比 LinkedIn 寬鬆很多。
SLEEP_MIN, SLEEP_MAX = _sleep_range_from_env("JOBSTREET", 0.5, 1.0)


def human_sleep(label: str = "", *, sleep: Callable[[float], None] = time.sleep) -> None:
    """JobStreet 的請求節奏 (v1.8.0)。

    `sleep` 在呼叫時才傳進來 → 引擎可以注入自己的 sleep, 測試也可以取代它。
    """
    s = random.uniform(SLEEP_MIN, SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    sleep(s)


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
#
# 2026-11-23 v1.6.7 fix: 原本的預設是照「預期覆蓋」推估的, 不是量出來的 ——
# 舊註解說 7d 預期 unique ~600, 但實際只有 ~250。因為 5 個 keyword 共用同一個
# seen set + 50% 軟停, 只有第一個 keyword 會被完整爬完, 其餘四個在第 1 頁就軟停。
#
# 2026-11-23 v1.6.8 fix: v1.6.7 的預算只把「第一個 keyword」算進去, 因為那時
# 只有第一個 keyword 真的會被爬。改成 per-keyword 軟停後, 每個 keyword 都會爬到
# 自己的池底 → 預算必須以「池子最大的那個 keyword」為準, 否則只是換一種截斷。
#
# 實測 (2026-11-23, 新加坡, 每個 keyword 的 totalCount 直接由 API 回報;
#       池子每天會長: 7d 的 product manager 當天就從 494 漲到 520;
#       1 天視窗更會隨一天累積 — 早上只回 2 筆, 中午就 181 筆):
#
#   range | product manager | product director | director of product | head of product | product lead
#   1h    | 38               | 39               | 50                | 19              | 181
#   24h   | 38               | 39               | 50                | 19              | 181
#   3d    | 184              | 140              | 147               | 67              | 448
#   7d    | 520              | 382              | 394               | 184             | 1109
#   14d   | 900              | 665              | 666               | 350             | 1837
#   21d   | 1296             | 924              | 928               | 480             | 2564
#   30d   | 1645             | 1199             | 1187              | 641             | 3369
#
# (1h 與 24h 的 daterange 都是 "1" 天 → 兩個 range 的池子完全相同。)
#
# 需要頁數 = ceil(池深 / 20) + 1 (多那一頁是 pool 到底時回 0 筆的 EOF 頁),
# 預算再留餘裕 (池子每天會長, 短視窗更是整天累積; 上限只是天花板, 軟停會在池底收手,
# 所以寬一點不會多花時間, 只差在不會截斷):
#
#   range | 最大 keyword 池深 | 需要頁數 | 舊預算 (v1.6.7) | 新預算 (v1.6.8)
#   1h    | 181               | 10       | 2  (不夠)       | 20
#   24h   | 181               | 10       | 4  (不夠)       | 20
#   3d    | 448               | 24       | 20 (不夠)       | 40
#   7d    | 1109              | 57       | 62              | 73
#   14d   | 1837              | 93       | 109             | 120
#   21d   | 2564              | 130      | 155             | 168
#   30d   | 3369              | 170      | 210             | 220
#
# v1.6.7 的 1h / 24h / 3d 在 per-keyword 模式下會安靜截斷 (最大的 keyword 只爬到
# 預算的一半), 所以這三個必須一起拉高, 不然改了軟停等於換一種截斷。
MAX_PAGES = {
    "1h": 20,
    "24h": 20,
    "3d": 40,
    "7d": 73,
    "14d": 120,
    "21d": 168,
    "30d": 220,
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
    start_page: int = 1,
) -> list[dict]:
    """跑多個 keyword 的 JobStreet list, 跨 keyword dedup。回傳 unique jobs。

    **每個 keyword 各爬各的池子** (2026-11-23 v1.6.8 fix): 舊版的 50% 軟停量的是
    「對整輪 crawl 而言是新的」筆數, 所以第一個 keyword 爬完之後, 後面每個 keyword
    的第一頁幾乎沒有「新的」→ 全部在第 1 頁就軟停。五個 keyword 的 crawl 其實只爬了
    一個 keyword。現在軟停量的是「這個 keyword 自己還沒回過的筆數」, 每個 keyword 都會
    爬到自己的池底, 跨 keyword 的重複仍然只回傳一次。

    50% 軟停 (per keyword): 該頁對**這個 keyword**而言的新筆數 < pageSize * 0.5 就視為到尾。

    每個 list page 走 `fetch_list_page`, 內含 30/60/90s retry ladder:
    瞬時的 429 / 5xx / connection error 不會再讓整個 keyword crawl 直接中止,
    coverage 不會被靜默砍掉 (2026-10-31 fix)。

    某個 keyword 真的失敗 (重試 4 次都沒成) 時, 只結束那個 keyword, 其他 keyword 繼續爬,
    最後印出失敗的 keyword 清單 (2026-11-23 v1.6.8 fix)。舊版是一個 keyword 失敗就
    中止整輪 → per-keyword 模式下請求量變 5 倍, 一個關鍵字失敗會把其他四個的成果
    一起丟掉, 那是改變本身帶來的 Regression。失敗仍然看得到 (FAIL 行 + 最後的摘要),
    supervisor 一樣抓得到。

    `session`, `sleep`, `sleep_seconds`, `build_url` and `parse_page` are injected
    so the caller decides which implementation runs (and so tests can substitute
    their own).

    `start_page` (v1.8.0): 只爬第 `start_page`..`max_pages` 頁。
    舊的「累計式」切塊 (第 N 塊爬第 1..N 頁) 會把前面 N-1 頁重爬一遍 ——
    30d 實測 product lead 一個 keyword 就爬了 1,260 頁, 但池子只有 169 頁 = 7.5× 重複。
    改成頁面區間式 (chunk k 爬自己的那一段) 後每頁只抓一次。
    跨 chunk 的去重不需要在這裡做: 引擎層的 seen_jds.jsonl + sheet pre-dedup
    已經擋掉前一塊寫過的職缺 → 區間式切塊不會重抓 JD, 也不會漏。
    """
    if keywords is None:
        keywords = _keywords_from_env()
    if start_page < 1:
        start_page = 1
    seen: set[str] = set()
    all_jobs: list[dict] = []
    failed_keywords: list[str] = []
    for kw in keywords:
        kw_seen: set[str] = set()
        for p in range(start_page, max_pages + 1):
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
                # 這個 keyword 結束, 但其他 keyword 繼續 (v1.6.8)
                print(f"  [jobstreet {kw} p{p}] FAIL: {e}")
                failed_keywords.append(kw)
                break
            jobs = parse_page(data, kw)
            # 這個 keyword 還沒回過的筆數 → 軟停訊號的來源 (per keyword)
            kw_fresh = [j for j in jobs if j["job_id"] not in kw_seen]
            for j in kw_fresh:
                kw_seen.add(j["job_id"])
            # 跨 keyword dedup: 只有整輪都沒見過的才回傳
            new_jobs = [j for j in kw_fresh if j["job_id"] not in seen]
            for j in new_jobs:
                seen.add(j["job_id"])
                all_jobs.append(j)
            total_count = data.get("totalCount", "?")
            print(
                f"  [jobstreet {kw} p{p}] 收 {len(jobs):3} | kw 新 {len(kw_fresh):3} | "
                f"跨 kw 新 {len(new_jobs):3} | kw 累計 {len(kw_seen):3} | "
                f"跨 kw 累計 {len(all_jobs):3} | totalCount={total_count}"
            )
            # 50% 軟停 (per keyword: 量的是這個 keyword 自己的新筆數)
            if len(jobs) == 0 or len(kw_fresh) < SOFT_STOP_MIN_FRESH:
                print(f"            50% 軟停 (kw 新 < {SOFT_STOP_MIN_FRESH} 或 jobs 空)")
                break
            if p < max_pages:
                sleep("list")
    if failed_keywords:
        print(f"  [jobstreet] ⚠ {len(failed_keywords)}/{len(keywords)} 個 keyword 失敗: {failed_keywords}")
    return all_jobs
