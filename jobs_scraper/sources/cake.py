"""Cake (www.cake.me) source adapter.

Owns the Cake public job API: search payload construction, list parsing, JD
fetching (public detail page, with the search-response description as the
fallback) and the coverage state machine that proves a crawl reached the
requested time window.

The module holds no global state. The HTTP session, the sleep function and the
engine-owned helper (work-mode detection) are injected by the caller, so every
function here can be exercised without touching the network — and the retry
ladder and the coverage proof stay observable.

`sg_product_jobs.py` keeps the public `*_cake_*` names as thin wrappers that
pass its own session, sleep and hit function down, so callers and tests that
patch those module attributes keep working unchanged.
"""

from __future__ import annotations

import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Callable

from bs4 import BeautifulSoup

API_BASE = "https://api.cake.me/api/client/v2"
WEB_BASE = "https://www.cake.me"
LIST_API = f"{API_BASE}/jobs/search"
FACET_API = f"{API_BASE}/jobs/facet-search"
SUGGESTION_API = f"{API_BASE}/jobs/query-suggestion/search"
DETAIL_PAGE_URL = f"{WEB_BASE}/companies/{{page_path}}/jobs/{{job_path}}"

SOURCE = "cake"
JOB_SOURCE = ["cake", "external"]
JOB_TYPES = ["full_time"]
SENIORITY_LEVELS = ["mid_senior_level", "executive", "director"]
LOCATIONS = [
    "香港",
    "Singapore",
    "United States",
    "Taipei City",
    "China",
    "台北市, 台灣",
    "新北市, 台灣",
    "New Taipei City",
]
PAGE_SIZE = 10
LOCATION_SCOPE = "Global"
SHEET_SOURCE_LABEL = "Cake / Minimax"

DEFAULT_KEYWORDS = [
    "product manager",
    "product director",
    "director of product",
    "head of product",
    "product lead",
    "產品經理",
    "產品總監",
    "產品主管",
    "PM",
]

#: Backoff ladder shared with the other sources: 30/60/90s, four attempts.
BACKOFF = [30, 60, 90]

#: Cake-specific human pacing, kept apart from the engine-wide window.
SLEEP_MIN = 3.0
SLEEP_MAX = 10.0

# Cake API 本身沒有捕捉到穩定的 time filter；這裡仍沿用 range→max_pages 的節流方式，
# 只是 page budget，不是時間窗。client-side 會用 content_updated_at 過濾 (見 crawl_list)。
# 14d/21d/30d 從 ONEZEROFOUR_MAX_PAGES 對齊降一階 (cake server 對高 page 429 敏感, 2026-08-30 實測)
MAX_PAGES = {
    "1h": 1,
    "24h": 4,
    "3d": 7,
    "7d": 15,
    "14d": 15,
    "21d": 20,
    "30d": 25,
}

# Client-side time filter (content_updated_at 對 cutoff 過濾)
# 1h 改 1 hour (不是 1 day); 24h/3d/7d/14d/21d/30d 維持 days
# 注意: content_updated_at 精度是秒級 (ISO 8601 UTC), 但 Cake API 沒 h/m 級的時間窗 server filter
# 所以 client-side 仍然要算實際 hours/days 對 content_updated_at 過濾
TIME_FILTER = {
    "1h": ("hours", 1),
    "24h": ("days", 1),
    "3d": ("days", 3),
    "7d": ("days", 7),
    "14d": ("days", 14),
    "21d": ("days", 21),
    "30d": ("days", 30),
}


def keywords() -> list[str]:
    """The keyword set, overridable with the ``CAKE_KEYWORDS`` env var."""
    override = os.getenv("CAKE_KEYWORDS", "").strip()
    if override:
        return [k.strip() for k in override.split(",") if k.strip()]
    return list(DEFAULT_KEYWORDS)


def sort_by_default() -> str:
    """The configured Cake ordering (default ``latest``)."""
    return os.getenv("CAKE_SORT_BY", "latest")


def proxies() -> dict[str, str] | None:
    """從 env 讀 proxy。

    優先順序:
      1) CAKE_HTTP_PROXY
      2) HTTPS_PROXY / HTTP_PROXY / ALL_PROXY

    空字串或都沒設 → None
    """
    proxy = (
        os.getenv("CAKE_HTTP_PROXY", "").strip()
        or os.getenv("HTTPS_PROXY", "").strip()
        or os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("ALL_PROXY", "").strip()
    )
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return {"http": proxy, "https": proxy}


def headers(*, accept: str = "application/json", referer: str = f"{WEB_BASE}/") -> dict:
    """Cake API / HTML 共用 browser-like headers。"""
    request_headers = {
        "Accept": accept,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "Origin": WEB_BASE,
        "Pragma": "no-cache",
        "Referer": referer,
        "Sec-Ch-Ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
    }
    auth = os.getenv("CAKE_AUTHORIZATION", "").strip() or os.getenv("CAKE_BEARER_TOKEN", "").strip()
    if auth:
        request_headers["Authorization"] = auth if auth.lower().startswith("bearer ") else f"Bearer {auth}"
    session_id = os.getenv("CAKE_SEARCH_SESSION_ID", "").strip() or os.getenv("CAKE_X_SEARCH_SESSION_ID", "").strip()
    if session_id:
        request_headers["X-Search-Session-Id"] = session_id
    return request_headers


def effective_order(sort_by: str | None, cutoff: "datetime | None", default: str | None = None) -> str:
    """Return the auditable Cake ordering for this crawl.

    Repair11 invariant: any crawl that uses a time cutoff MUST be newest-to-oldest.
    A stale/debug CAKE_SORT_BY value may still be used only when there is no cutoff.
    """
    if default is None:
        default = sort_by_default()
    requested = (sort_by or default or "latest").strip().lower()
    if cutoff is not None:
        return "latest"
    return requested or "latest"


def build_search_payload(
    keyword: str,
    page: int,
    per_page: int = PAGE_SIZE,
    sort_by: str | None = None,
    locations: list[str] | None = None,
    job_types: list[str] | None = None,
    seniority_levels: list[str] | None = None,
    job_source: list[str] | None = None,
) -> dict:
    """組 Cake search API POST payload。

    注意:
      - 這是 POST JSON，不是 query string
      - page 是 1-indexed
      - 現階段沒看到穩定的 date filter，所以 range 只拿來決定 max_pages
    """
    return {
        "query": keyword,
        "filters": {
            "job_source": job_source or JOB_SOURCE,
            "job_types": job_types or JOB_TYPES,
            "locations": locations or LOCATIONS,
            "seniority_levels": seniority_levels or SENIORITY_LEVELS,
        },
        "sort_by": sort_by_default() if sort_by is None else sort_by,
        "page": page,
        "per_page": per_page,
    }


def build_detail_url(page_path: str, job_path: str) -> str:
    """組 Cake public detail URL。"""
    return DETAIL_PAGE_URL.format(page_path=page_path, job_path=job_path)


def text_from_html(html: str) -> str:
    """盡量從 Cake detail HTML 抽純文字。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def parse_search_page(data: dict, keyword: str, *, extract_work_mode: Callable[..., str]) -> list[dict]:
    """從 Cake search API JSON 轉成內部 job dict。

    `extract_work_mode` is injected: the work-mode rules are engine-wide and
    must keep exactly one implementation.
    """
    jobs_raw = data.get("data") or []
    out = []
    for j in jobs_raw:
        job_path = j.get("path") or ""
        page = j.get("page") or {}
        page_path = page.get("path") or ""
        if not job_path or not page_path:
            continue
        description = j.get("description") or ""
        locs = j.get("locations") or []
        if isinstance(locs, list) and locs:
            loc = locs[0]
        else:
            loc = (page.get("geo") or {}).get("state_name", "") or ""
        out.append(
            {
                "job_id": job_path,  # Cake 的穩定 identifier: public detail URL path
                "path": job_path,
                "title": (j.get("title") or "").strip(),
                "company": page.get("name", "") or "",
                "location": loc,
                "posted_at": j.get("content_updated_at", ""),
                "url": build_detail_url(page_path, job_path),
                "work_mode": extract_work_mode(description, j.get("title", "")),
                "source": SOURCE,
                "keyword_used": keyword,
                "page_path": page_path,
                "page_name": page.get("name", ""),
                "job_source": j.get("job_source", ""),
                "job_type": j.get("job_type", ""),
                "seniority_level": j.get("seniority_level", ""),
                "content_updated_at": j.get("content_updated_at", ""),
                "description": description,  # 先保留原文，fetch_jd 會優先用它做 fallback
                "highlighted_title": j.get("highlighted_title", ""),
                "highlighted_description": j.get("highlighted_description", ""),
            }
        )
    return out


def fetch_jd(job: dict | str, page_path: str | None = None, *, session) -> dict:
    """抓 Cake JD。

    優先順序:
      1) 先試 public detail HTML
      2) 失敗就 fallback 到 search list 的 description

    Returns:
      {jd_text, jd_lines, jd_html, company, location, title, error, jd_source}
    """
    if isinstance(job, dict):
        job_path = job.get("path") or job.get("job_id") or ""
        page_path = page_path or job.get("page_path") or (job.get("page") or {}).get("path") or ""
        title = job.get("title", "")
        company = job.get("company", "") or (job.get("page") or {}).get("name", "")
        location = job.get("location", "")
        description = job.get("description") or job.get("highlighted_description") or ""
    else:
        job_path = str(job)
        title = ""
        company = ""
        location = ""
        description = ""
    detail_url = build_detail_url(page_path, job_path) if page_path and job_path else ""

    # 1) 先試 public HTML
    if detail_url:
        try:
            r = session.get(
                detail_url,
                headers=headers(
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=f"{WEB_BASE}/",
                ),
                proxies=proxies(),
                timeout=30,
                impersonate="chrome",
            )
            if r.status_code == 200:
                html_text = text_from_html(r.text)
                if html_text and "Just a moment..." not in html_text and len(html_text) >= 60:
                    jd_lines = [t.strip() for t in html_text.split("\n") if t.strip()]
                    return {
                        "jd_text": html_text,
                        "jd_lines": jd_lines,
                        "jd_html": r.text,
                        "company": company,
                        "location": location,
                        "title": title,
                        "error": None,
                        "jd_source": "detail_html",
                    }
        except Exception as e:
            detail_err = f"{type(e).__name__}: {e}"
        else:
            detail_err = f"HTTP {r.status_code}" if detail_url else "no detail url"
    else:
        detail_err = "no detail url"

    # 2) fallback: list description already 很長，通常就是完整 JD
    if description:
        jd_text = re.sub(r"\s+", " ", description).strip()
        jd_lines = [t.strip() for t in description.splitlines() if t.strip()]
        return {
            "jd_text": jd_text,
            "jd_lines": jd_lines,
            "jd_html": None,
            "company": company,
            "location": location,
            "title": title,
            "error": None,
            "jd_source": f"list_description ({detail_err})",
        }
    return {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": company,
        "location": location,
        "title": title,
        "error": detail_err,
        "jd_source": "none",
    }


def list_with_retry(
    kw: str,
    page: int,
    payload: dict,
    max_retries: int = 3,
    *,
    session,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Cake list API 帶 30/60/90s retry (對齊 104 / Jora §15.13 #11)。

    429 / 5xx / connection error → sleep 30/60/90s → retry。
    4xx (非 429) 直接 raise, 視為 caller bug (例如 400 bad request)。
    Returns: response.json() dict
    Raises: RuntimeError if all retries fail
    """
    backoff = list(BACKOFF)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = session.post(
                LIST_API,
                headers=headers(),
                json=payload,
                proxies=proxies(),
                timeout=30,
                impersonate="chrome",
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                raise RuntimeError(f"  [cake {kw!r} p{page}] non-retryable HTTP {r.status_code}: {r.text[:200]}")
        except RuntimeError:
            raise
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < max_retries:
            print(
                f"  [cake {kw!r} p{page} RETRY {attempt + 1}/{max_retries}] {last_err}, sleep {backoff[attempt]}s",
                flush=True,
            )
            sleep(backoff[attempt])
    raise RuntimeError(f"cake list API fail after {max_retries + 1} attempts: {last_err}")


def parse_job_timestamp(job: dict) -> tuple["datetime | None", bool]:
    """Parse Cake ``content_updated_at``.

    Returns ``(parsed_datetime, unknown)``. Missing or malformed timestamps are
    retained as jobs, counted in diagnostics, and never prove that a time
    boundary was reached. This is deliberately conservative: unknown time
    cannot turn an incomplete crawl into COMPLETE.
    """
    ts = job.get("content_updated_at", "")
    if not ts:
        return None, True
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), False
    except Exception:
        return None, True


def aggregate_coverage(keyword_results: list[dict], cutoff: "datetime | None", total_jobs: int) -> str:
    """Aggregate Cake coverage across *every* keyword worker.

    Precedence intentionally keeps failures visible. COMPLETE requires every
    worker to have independently reached the cutoff boundary or server end.
    """
    states = [r.get("coverage_state", "ERROR") for r in keyword_results]
    if any(state == "ERROR" for state in states):
        return "PARTIAL_ERROR"
    if cutoff is None:
        return "UNKNOWN_NO_CUTOFF"
    if any(state == "TRUNCATED" for state in states):
        return "TRUNCATED"
    if keyword_results and all(state == "COMPLETE" for state in states):
        return "EMPTY" if total_jobs == 0 else "COMPLETE"
    if not keyword_results:
        return "EMPTY"
    # Fail closed if a future keyword state is introduced without aggregation.
    return "PARTIAL_ERROR"


def human_sleep(label: str = "", *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Cake 專用 sleep: 跟全域同 3.0-10.0s, 2-5s 測試發現 14 page 就 429。"""
    s = random.uniform(SLEEP_MIN, SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    sleep(s)


def crawl_list(
    daterange: str | None = None,
    max_pages: int | None = None,
    keywords: list[str] | None = None,
    sort_by: str | None = None,
    per_page: int = PAGE_SIZE,
    locations: list[str] | None = None,
    job_types: list[str] | None = None,
    seniority_levels: list[str] | None = None,
    job_source: list[str] | None = None,
    *,
    crawl_one_kw: Callable[..., dict],
) -> dict:
    """Run independent Cake keyword searches and aggregate auditable coverage.

    Repair10 coverage contract:
    - worker owns cutoff/boundary proof; old boundary jobs are never returned;
    - each keyword reports COMPLETE / TRUNCATED / ERROR plus diagnostics;
    - global COMPLETE requires every keyword COMPLETE and no worker error;
    - server exhaustion is complete even when all observed jobs are fresh;
    - max-pages with no boundary/end is TRUNCATED;
    - missing/malformed timestamps are retained, counted, and never prove end;
    - no requested time cutoff yields UNKNOWN_NO_CUTOFF (unless a worker failed).

    The crawler stays bounded at ThreadPoolExecutor(max_workers=3) and dedups
    cross-keyword results by Cake path/job_id.

    `crawl_one_kw` is the per-keyword worker, injected so the caller decides
    which implementation runs.
    """
    if keywords is None:
        keywords = module_keywords()
    if max_pages is None:
        if daterange is not None:
            max_pages = MAX_PAGES.get(daterange, 15)
        else:
            max_pages = 15

    cutoff = None
    if daterange is not None and daterange in TIME_FILTER:
        unit, n = TIME_FILTER[daterange]
        if unit == "hours":
            cutoff = datetime.now(timezone.utc) - timedelta(hours=n)
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=n)

    requested_sort_by = (sort_by or sort_by_default() or "latest").strip().lower()
    effective_sort_by = effective_order(requested_sort_by, cutoff)
    if cutoff is not None and effective_sort_by != requested_sort_by:
        print(
            f"  [cake coverage invariant] ranged crawl forces sort_by=latest (requested={requested_sort_by!r})",
            flush=True,
        )

    seen: set[str] = set()
    all_jobs: list[dict] = []
    keyword_results_by_kw: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                crawl_one_kw,
                kw,
                max_pages,
                cutoff,
                effective_sort_by,
                per_page,
                locations,
                job_types,
                seniority_levels,
                job_source,
            ): kw
            for kw in keywords
        }
        for future in as_completed(futures):
            kw = futures[future]
            try:
                result = future.result()
                if not isinstance(result, dict):
                    raise TypeError(f"worker returned {type(result).__name__}, expected dict")
            except Exception as e:
                result = {
                    "keyword": kw,
                    "jobs": [],
                    "coverage_state": "ERROR",
                    "boundary_reached": False,
                    "server_exhausted": False,
                    "pages_scanned": 0,
                    "max_pages": max_pages,
                    "unknown_timestamp_count": 0,
                    "error": f"{type(e).__name__}: {e}",
                }
            keyword_results_by_kw[kw] = result
            jobs = result.get("jobs", [])
            new_jobs = [j for j in jobs if j["job_id"] not in seen]
            for j in new_jobs:
                seen.add(j["job_id"])
                all_jobs.append(j)
            print(
                f"  [cake {kw}] state={result.get('coverage_state')} pages={result.get('pages_scanned')} "
                f"boundary={result.get('boundary_reached')} exhausted={result.get('server_exhausted')} "
                f"unknown_ts={result.get('unknown_timestamp_count')} | 收 {len(jobs):3} | "
                f"新增 {len(new_jobs):3} | 跨 kw 累計 {len(all_jobs):3}"
            )

    # Preserve caller keyword order so raw diagnostics are deterministic.
    keyword_results = [keyword_results_by_kw[kw] for kw in keywords if kw in keyword_results_by_kw]
    coverage_state = aggregate_coverage(keyword_results, cutoff, len(all_jobs))
    return {
        "jobs": all_jobs,
        "coverage_state": coverage_state,
        "max_pages_used": max_pages,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "requested_sort_by": requested_sort_by,
        "effective_sort_by": effective_sort_by,
        "keyword_results": keyword_results,
    }


def crawl_single_kw(
    kw: str,
    max_pages: int,
    cutoff: "datetime | None" = None,
    sort_by: str | None = None,
    per_page: int = PAGE_SIZE,
    locations: list[str] | None = None,
    job_types: list[str] | None = None,
    seniority_levels: list[str] | None = None,
    job_source: list[str] | None = None,
    *,
    hit: Callable[..., dict],
    sleep: Callable[..., None],
    extract_work_mode: Callable[..., str],
) -> dict:
    """Run one ordered Cake keyword crawl and return jobs plus coverage proof.

    With ``sort_by=latest`` and a cutoff, the first parseable job older than the
    cutoff proves the keyword boundary. The old job is filtered, the rest of
    that already-fetched page is still examined, and no later page is requested.
    Missing/malformed timestamps are retained and counted but cannot prove a
    boundary. Server exhaustion is also COMPLETE. Reaching max_pages while the
    server still advertises more pages is TRUNCATED. Request failure is ERROR.

    `hit` (the list fetcher), `sleep` (the human pacing) and
    `extract_work_mode` are injected so the caller controls them.
    """
    requested_sort_by = (sort_by or sort_by_default() or "latest").strip().lower()
    effective_sort_by = effective_order(requested_sort_by, cutoff)
    if cutoff is not None and effective_sort_by != requested_sort_by:
        print(
            f"  [cake {kw!r}] ranged cutoff forces sort_by=latest (requested={requested_sort_by!r})",
            flush=True,
        )

    seen: set[str] = set()
    out: list[dict] = []
    page = 1
    total_pages = None
    boundary_reached = False
    server_exhausted = False
    unknown_timestamp_count = 0
    pages_scanned = 0
    error = None

    while page <= max_pages:
        payload = build_search_payload(
            kw,
            page,
            per_page=per_page,
            sort_by=effective_sort_by,
            locations=locations,
            job_types=job_types,
            seniority_levels=seniority_levels,
            job_source=job_source,
        )
        try:
            data = hit(kw, page, payload)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            print(f"  [cake {kw!r} p{page}] ERROR: {error}")
            break

        pages_scanned += 1
        jobs = parse_search_page(data, kw, extract_work_mode=extract_work_mode)
        for j in jobs:
            jid = j["job_id"]
            if jid in seen:
                continue
            if cutoff is not None:
                job_dt, unknown = parse_job_timestamp(j)
                if unknown:
                    unknown_timestamp_count += 1
                elif job_dt < cutoff:
                    boundary_reached = True
                    # Boundary proof is metadata only. Never return the old job.
                    continue
            seen.add(jid)
            out.append(j)

        total_pages = data.get("total_pages") or total_pages
        total_entries = data.get("total_entries", "?")
        if not jobs or (total_pages is not None and page >= int(total_pages)):
            server_exhausted = True
        print(
            f"  [cake {kw!r} p{page}] 收 {len(jobs):3} | kw 累計 {len(out):3} | "
            f"total_entries={total_entries} total_pages={total_pages} "
            f"boundary={boundary_reached} unknown_ts={unknown_timestamp_count}"
        )

        if boundary_reached or server_exhausted:
            break
        if page < max_pages:
            sleep("list")
        page += 1

    if error is not None:
        state = "ERROR"
    elif cutoff is None:
        # Keyword-level diagnostic; global result uses UNKNOWN_NO_CUTOFF too.
        state = "TRUNCATED" if not server_exhausted else "COMPLETE"
    elif boundary_reached or server_exhausted:
        state = "COMPLETE"
    else:
        state = "TRUNCATED"

    return {
        "keyword": kw,
        "jobs": out,
        "coverage_state": state,
        "boundary_reached": boundary_reached,
        "server_exhausted": server_exhausted,
        "pages_scanned": pages_scanned,
        "max_pages": max_pages,
        "unknown_timestamp_count": unknown_timestamp_count,
        "requested_sort_by": requested_sort_by,
        "effective_sort_by": effective_sort_by,
        "error": error,
    }


def module_keywords() -> list[str]:
    return keywords()
