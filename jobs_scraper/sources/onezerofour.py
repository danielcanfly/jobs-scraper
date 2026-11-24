"""104 (onezerofour) source adapter.

Owns the 104 public job API: URL construction, list parsing, and JD fetching.

The module holds no global state. The HTTP session and the sleep function are
injected by the caller, so every function here can be exercised without
touching the network — and the retry ladders stay observable.

`sg_product_jobs.py` keeps the public `*_onezerofour_*` names as thin wrappers
that pass its own session, sleep, and hit function down, so callers and tests
that patch those module attributes keep working unchanged.
"""

from __future__ import annotations

import os
import random
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable

from jobs_scraper.sources import resolve_proxies

LIST_API = "https://www.104.com.tw/jobs/search/api/jobs"
DETAIL_API = "https://www.104.com.tw/job/ajax/content/{slug}"  # {slug} placeholder
BASE_URL = "https://www.104.com.tw"
AREAS = "6001001000,6001002000"  # 台北+新北 (硬寫, 不開放 CLI 改)

# isnew 合法值: 0/3/7/14/30 (其他 400, 含 21)
TPR = {
    "1h": 0,  # 退化: 1h 沒對應合法值, 用 0
    "24h": 0,
    "3d": 3,
    "7d": 7,
    "14d": 14,
    "21d": 30,  # 退化: 21 會 400, 用 30
    "30d": 30,
}

# MAX_PAGES 跟 LinkedIn/JobStreet 對齊 (邏輯統一); 30d 額外加 50 涵蓋
MAX_PAGES = {
    "1h": 1,
    "24h": 4,
    "3d": 7,
    "7d": 15,
    "14d": 30,
    "21d": 30,
    "30d": 50,  # 30d 用 50 (B 階段實測, 涵蓋 ~14%)
}

DEFAULT_KEYWORDS = [
    "Product Manager",
    "Product Director",
    "Director of Product",
    "Head of product",
    "Product Lead",
    "產品經理",
    "產品總監",
    "產品主管",
    "PM",
]

LOCATION = "Taiwan"  # 104 只抓台灣, 跟 LinkedIn/Jora/JobStreet 限定 SG 不一樣
SHEET_SOURCE_LABEL = "104 / Minimax"

SOURCE = "onezerofour"

#: Backoff ladder shared with the other sources: 30/60/90s, four attempts.
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


# v1.8.0: 104 的請求節奏 (2026-11-24 實測: detail API 0.38s/筆, 59 筆 @0.3s 間隔零失敗)
#
# 104 的 list API 之前**完全沒有**一般性的節奏 sleep (只在 retry 時 backoff) →
# 8 個 keyword 的 worker 會無間隔連打。實測 8 workers 全平行 + 連續 10 次都回 200,
# 但一次密集的 burst 之後確實出現過 403 → 所以給它一組自己的、保守的區間。
# 1.0-2.0s 比全域的 3-10s 快 4 倍, 又留足餘裕。
SLEEP_MIN, SLEEP_MAX = _sleep_range_from_env("ONEZEROFOUR", 1.0, 2.0)


def human_sleep(label: str = "", *, sleep: Callable[[float], None] = time.sleep) -> None:
    """104 的請求節奏 (v1.8.0)。

    `sleep` 在呼叫時才傳進來 → 引擎可以注入自己的 sleep, 測試也可以取代它。
    """
    s = random.uniform(SLEEP_MIN, SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    sleep(s)


_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def keywords() -> list[str]:
    """The keyword set, overridable with the ``ONEZEROFOUR_KEYWORDS`` env var."""
    override = os.getenv("ONEZEROFOUR_KEYWORDS", "").strip()
    if override:
        return [k.strip() for k in override.split(",") if k.strip()]
    return list(DEFAULT_KEYWORDS)


def headers(referer: str = "https://www.104.com.tw/jobs/search/") -> dict[str, str]:
    """104 共用 header, referer 預設 list page (detail API 要換成 /job/{slug})。

    2026-11-24 實測: 少了 `sec-fetch-*` 這組, 104 的 jobs search API 一律回 403
    (首頁 200, 但 /jobs/search/api/jobs 被擋)。瀏覽器的 XHR 會帶這三個
    sec-fetch-* header, 104 的 bot 保護會看它們 → 少了就當成非同源請求擋掉。
    `x-requested-with: XMLHttpRequest` + `origin` 一起補上, 跟真實 XHR 一致。

    另外這台機直連 104 API 也回 403 (經 proxy 才 200) → 走共用 proxy 解析。
    """
    return {
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Origin": BASE_URL,
        "x-requested-with": "XMLHttpRequest",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def build_list_url(keyword: str, page: int, isnew: int, areas: str = AREAS) -> str:
    """組 104 list API URL。RULES §15.2 完整 query spec。

    Args:
        keyword: 搜尋字串 (傳原字中文, Python 自動 URL encode)
        page: 1-indexed (page=1 開始, server 給 22 個, page 6+ 給 20 個)
        isnew: 0/3/7/14/30 (其他 400, 含 21)
        areas: 地區代碼, 預設台北+新北
    """
    params = {
        "area": areas,
        "keyword": keyword,
        "isnew": str(isnew),
        "page": str(page),
        "pagesize": "20",
        "order": "15",
        "mode": "s",  # s = 搜尋模式 (不是 l=列表模式)
        "jobsource": "m_joblist_search",
        "searchJobs": "1",
    }
    return f"{LIST_API}?{urllib.parse.urlencode(params)}"


def hit_list(
    keyword: str,
    page: int,
    isnew: int,
    max_retries: int = 3,
    *,
    session,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict]:
    """List API 帶 30/60/90s retry (跟 Jora 403 retry pattern 同, RULES §15.13 #11)。

    Returns: list of raw job dicts (從 response.data 解出)
    Raises: RuntimeError if all retries fail
    """
    url = build_list_url(keyword, page, isnew)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = session.get(
                url,
                headers=headers(),
                timeout=30,
                impersonate="chrome",
                proxies=resolve_proxies(),
            )
            if r.status_code == 200:
                return r.json().get("data", [])
            last_err = f"http {r.status_code}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < max_retries:
            print(
                f"    [104 LIST RETRY {attempt + 1}/{max_retries}] kw={keyword!r} p{page} 失敗 ({last_err}), sleep {BACKOFF[attempt]}s",
                flush=True,
            )
            sleep(BACKOFF[attempt])
    raise RuntimeError(f"104 list API fail after {max_retries + 1} attempts: {last_err}")


def hit_detail(
    slug: str,
    max_retries: int = 3,
    *,
    session,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Detail API (5-char slug)。Fail-closed: 404 直接 raise (RULES §15.13 #5)。

    Returns: jobDescription 文字 (str), 空字串 if API 沒給
    Raises: RuntimeError on 404 (job 已下架) or retry exhausted
    """
    url = DETAIL_API.format(slug=slug)
    request_headers = headers(referer=f"{BASE_URL}/job/{slug}")
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = session.get(
                url,
                headers=request_headers,
                timeout=30,
                impersonate="chrome",
                proxies=resolve_proxies(),
            )
            if r.status_code == 200:
                d = r.json().get("data", {}).get("jobDetail", {})
                return d.get("jobDescription", "") or ""
            if r.status_code == 404:
                # 404 fail-closed: job 已下架, 直接 raise, 不要 silent skip
                raise RuntimeError(f"104 detail 404 for slug={slug} (job 已下架)")
            last_err = f"http {r.status_code}"
        except RuntimeError:
            raise  # 404 propagate
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < max_retries:
            print(
                f"    [104 DETAIL RETRY {attempt + 1}/{max_retries}] slug={slug} 失敗 ({last_err}), sleep {BACKOFF[attempt]}s",
                flush=True,
            )
            sleep(BACKOFF[attempt])
    raise RuntimeError(f"104 detail API fail after {max_retries + 1} attempts: {last_err}")


def parse_list_page(raw_jobs: Iterable[dict], keyword: str = "") -> list[dict]:
    """從 104 list API 的 data 陣列解 jobs。RULES §15.3 完整欄位對照。

    回傳 dict 格式跟其他 source 對齊 (統一 job_id / source / title / company / location / url 等 key)。
    job_id 用 slug (5-char) 不是 jobNo (8 digit), 因為 sheet E 欄跟 parse_sheet_row_to_key 都用 slug 推斷 source。
    """
    out = []
    for j in raw_jobs:
        job_no = j.get("jobNo")
        slug = (j.get("link") or {}).get("job", "")
        # 拿最後一段 (URL 格式: https://www.104.com.tw/job/xxx → xxx, 注意 trailing slash)
        if "/" in slug:
            slug = slug.rstrip("/").rsplit("/", 1)[-1]
        if not (job_no and slug):
            continue
        # remoteWorkType 對應 work_mode: 0=Onsite / 1=Remote / 2=Hybrid (RULES §15.3)
        rw = j.get("remoteWorkType", 0)
        if rw == 1:
            wm = "Remote"
        elif rw == 2:
            wm = "Hybrid"
        else:
            wm = "Onsite"
        out.append(
            {
                "job_id": slug,  # 用 slug 當 job_id (跟 E 欄 URL 一致, 跟 parse_sheet_row_to_key 對齊)
                "job_no": job_no,  # 8 digit, 留著 debug/audit 用
                "title": j.get("jobName", ""),
                "company": j.get("custName", ""),
                "location": j.get("jobAddrNoDesc", ""),
                "posted_at": j.get("appearDate", ""),
                "url": f"{BASE_URL}/job/{slug}",
                "work_mode": wm,
                "source": SOURCE,
                "keyword_used": keyword,  # debug 用
            }
        )
    return out


def fetch_jd(slug: str, *, hit: Callable[[str], str]) -> dict:
    """抓單一 job 的完整 JD。回傳跟其他 source 對齊的 dict。

    `hit` is the detail fetcher, injected so the caller controls the session.

    Returns: {jd_text, jd_lines, jd_html, company, location, title, error}
    """
    try:
        jd_text = hit(slug)
    except RuntimeError as e:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": str(e),
        }
    if not jd_text:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": "empty JD",
        }
    # 跟其他 source 一樣: jd_lines 給 optional 用, 主要還是 jd_text
    jd_lines = [t.strip() for t in jd_text.split("\n") if t.strip()]
    return {
        "jd_text": jd_text,
        "jd_lines": jd_lines,
        "jd_html": None,
        "company": "",  # 104 list 階段已有, 不再覆寫
        "location": "",
        "title": "",
        "error": None,
    }


def crawl_list(
    daterange: str,
    max_pages: int,
    keywords: list[str] | None = None,
    *,
    hit: Callable[..., list[dict]],
    sleep: Callable[[str], None] | None = None,
    start_page: int = 1,
) -> list[dict]:
    """8 keyword × max_pages list API, ThreadPoolExecutor 8 workers 平行抓 (RULES §15.8, §15.11)。

    跨 kw dedup by slug (slug 跨 kw 不會撞, 但保險起見去重)。

    `hit` is the list fetcher, injected so the caller controls the session and
    so tests can substitute their own.

    `sleep` is the per-page pacing hook (v1.8.0): 104 的 list API 之前完全沒有
    一般性的節奏, 8 個 worker 會無間隔連打 → 密集 burst 之後會出現 403。
    引擎注入自己的 per-source sleep, 測試可以取代它。

    `start_page` (v1.8.0): 只爬第 start_page..max_pages 頁 (頁面區間式切塊)。
    舊的累計式切塊 (第 N 塊爬第 1..N 頁) 會把前面重爬一遍。
    """
    if keywords is None:
        keywords = _module_keywords()
    if sleep is None:
        sleep = _no_sleep
    isnew = TPR[daterange]
    seen: set[str] = set()
    collected: list[tuple[str, dict]] = []  # (keyword, raw_job)

    def _fetch_one_kw(kw: str) -> list[tuple[str, str, dict]]:
        """單 keyword × max_pages (sequential, 一個 worker 跑固定一個 kw)。
        Returns: list of (kw, slug, raw_job) for dedup tracking。
        """
        results = []
        for p in range(start_page, max_pages + 1):
            try:
                raw = hit(kw, p, isnew)
            except RuntimeError as e:
                print(f"  [104 KW FAIL] {kw!r} p{p}: {e}", flush=True)
                continue
            if p < max_pages:
                sleep("list")
            for j in raw:
                slug = (j.get("link") or {}).get("job", "")
                if "/" in slug:
                    slug = slug.rstrip("/").rsplit("/", 1)[-1]
                if slug:
                    results.append((kw, slug, j))
        return results

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch_one_kw, kw): kw for kw in keywords}
        for fut in as_completed(futs):
            kw = futs[fut]
            try:
                kw_results = fut.result()
            except Exception as e:
                print(f"  [104 KW EXCEPTION] {kw!r}: {type(e).__name__}: {e}", flush=True)
                continue
            for _kw, slug, raw in kw_results:
                if slug in seen:
                    continue
                seen.add(slug)
                collected.append((_kw, raw))
    # parse 階段 (拿到原始 jobs 統一轉 dict, keyword 跟著帶進去)
    out = []
    for kw, raw in collected:
        out.extend(parse_list_page([raw], keyword=kw))
    return out


def _no_sleep(label: str = "") -> None:
    """Default pacing hook — the engine injects its own."""
    return None


def _module_keywords() -> list[str]:
    return keywords()
