"""LinkedIn (jobs-guest) source adapter.

Owns the LinkedIn Guest API: the source constants, URL construction, list
parsing and JD fetching.

The module holds no global state. The HTTP session and the sleep function are
injected by the caller, so every function here can be exercised without
touching the network — and the 30/60/90s retry ladder stays observable.

`sg_product_jobs.py` keeps the public `build_list_url` / `parse_list_page` /
`fetch_list_page` / `build_jd_url` / `fetch_jd` names as thin wrappers that pass
its own session, sleep and URL builders down, so callers and tests that patch
those module attributes keep working unchanged.
"""

from __future__ import annotations

import os
import random
import time
from typing import Callable
from urllib.parse import urlencode

from scrapling.parser import Adaptor

from jobs_scraper.sources import resolve_proxies

SOURCE = "linkedin"
SHEET_SOURCE_LABEL = "LinkedIn / Minimax"

# ─────────────────────────────────────────────────────────────
# 篩選條件
# ─────────────────────────────────────────────────────────────
KEYWORDS = (
    '"product manager" OR "product director" OR "director of product" '
    'OR "head of product" OR "product lead" OR "chief of staff"'
)
GEO_ID = "102454443"  # Singapore (default; 跑其他國家用 --location/--geo-id 覆寫)
LOCATION = "Singapore"  # 對應 GEO_ID 的顯示文字
# 常用其他 geoId (驗證過)
KNOWN_GEO_IDS = {
    "Singapore": ("102454443", "Singapore"),
    "Taiwan": ("104187078", "Taiwan"),
    "Hong Kong": ("105015875", "Hong Kong"),  # 待驗證
    "Japan": ("105080838", "Japan"),  # 待驗證
    "Shanghai": ("107388191", "Shanghai"),  # 中國城市, 30,000+ jobs
    # 2026-11-19 實抓驗證: geoId 取自 LinkedIn GEO typeahead, 回傳職缺地點為對應城市
    "Hangzhou": ("101821877", "Hangzhou"),  # 中國城市 (杭州, 浙江)
    "Shenzhen": ("106750182", "Shenzhen"),  # 中國城市 (深圳, 廣東)
}
# 不放 f_WT → onsite/remote/hybrid 全收
PAGE_SIZE = 10  # Guest API 實際 page size (不是 25)

# time range 預設值 + 各 range 的 MAX_PAGES 建議
#
# 2026-11-22 v1.6.6 fix: 原本 30d 只給 25 頁 (250 筆), 但上海 30d 的池子有 700 筆
# → 引擎預設值會安靜地截掉七成職缺。
#
# 2026-11-23 v1.6.7 fix: 補測新加坡的池深 — 每個 range 的上限都必須蓋得住
# **該 range 所有已知城市中最大的池子**, 不是只看上海。
#
# 實測池深 (走 list API 逐頁探到空頁為止; 2026-11-22 上海 / 2026-11-23 新加坡):
#
#   range | 上海池深        | 新加坡池深      | 需要頁數 | 本表上限
#   1h    | <50 筆 (<5 頁)  | ~10 筆 (1 頁)   | 5        | 8
#   24h   | ~100 筆 (10 頁) | ~60 筆 (6 頁)   | 10       | 15
#   3d    | ~250 筆 (25 頁) | ~200 筆 (20 頁)  | 25       | 35
#   7d    | ~400 筆 (40 頁) | ~600 筆 (60 頁)  | 60       | 80
#   14d   | ~290 筆 (29 頁) | >900 筆 (90+ 頁) | 98       | 100 ← API 天花板
#   21d   | ~300 筆 (30 頁) | >900 筆 (90+ 頁) | 98       | 100 ← API 天花板
#   30d   | ~700 筆 (70 頁) | ~900-980 筆      | 98       | 100 ← API 天花板
#
# 14d/21d/30d 的上限不是「池子有多大」而是「API 能翻多深」: Guest API 在
# start=1000 回 HTTP 400 (不是空頁), 所以 100 頁 = 1000 筆就是天花板。
# 再往上加只會撞牆 (見 PAGINATION_CEILING 與 crawl_list 的分頁天花板處理)。
#
# 新的頁數上限都留 ~40% 餘裕 (池子會隨新職缺公告而變動)。重點不是「上限要剛好等於池深」,
# 而是 crawl_list 遇到連續 2 頁 0 new 就當作到底 (empty_streak) → 池子小的城市不會多花時間,
# 上限只當天花板用。所以把上限拉寬不會讓小池子變慢, 卻讓大池子不再被截斷。
#
# 舊值 (v1.6.5): 1h=1, 24h=4, 3d=7, 7d=15, 14d=30, 21d=30, 30d=25
# v1.6.6:       1h=5, 24h=15, 3d=35, 7d=55, 14d=40, 21d=45, 30d=95
# → v1.6.6 的 7d/14d/21d/30d 對新加坡來說還是太低。
TIME_RANGES = {
    "1h": ("r3600", 8),
    "24h": ("r86400", 15),
    "3d": ("r259200", 35),
    "7d": ("r604800", 80),
    "14d": ("r1209600", 100),
    "21d": ("r1814400", 100),
    "30d": ("r2592000", 100),
}

# ─────────────────────────────────────────────────────────────
# URL
# ─────────────────────────────────────────────────────────────
LIST_API = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JD_API = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"  # {job_id} placeholder
JOB_VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}"

# ─────────────────────────────────────────────────────────────
# 列表頁 CSS selector
# ─────────────────────────────────────────────────────────────
JOB_CARD_SEL = "div.base-card"
TITLE_SEL = ".base-search-card__title"
COMPANY_SEL = "a.hidden-nested-link"
LOC_SEL = ".job-search-card__location"
TIME_SEL = "time"
LINK_SEL = "a.base-card__full-link"

# ─────────────────────────────────────────────────────────────
# JD CSS selector
# ─────────────────────────────────────────────────────────────
JD_DESC_SEL = "div.description__text"
JD_BLOCK_SEL = (
    "div.description__text p, div.description__text li, "
    "div.description__text h1, div.description__text h2, "
    "div.description__text h3, div.description__text h4, "
    "div.description__text strong, div.description__text span"
)

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


# v1.8.0: LinkedIn 的請求節奏 (2026-11-24 實測純網路只要 0.92s, 舊的 3-10s sleep
# 讓 wall time 有 88% 是等待)。
# 沒有像 JobStreet 那樣降到 0.5-1.0s: Guest API 會真的 429,
# 所以保守地降到 1.5-3.0s, 30/60/90 的 backoff ladder 仍然保留。
SLEEP_MIN, SLEEP_MAX = _sleep_range_from_env("LINKEDIN", 1.5, 3.0)


def human_sleep(label: str = "", *, sleep: Callable[[float], None] = time.sleep) -> None:
    """LinkedIn 的請求節奏 (v1.8.0)。

    `sleep` 在呼叫時才傳進來 → 引擎可以注入自己的 sleep, 測試也可以取代它。
    """
    s = random.uniform(SLEEP_MIN, SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    sleep(s)


#: The Guest API refuses to paginate past this `start` offset: it answers HTTP
#: 400 instead of an empty page (measured 2026-11-23: start=990 → 200 with an
#: empty body, start=1000 → HTTP 400). So 100 pages — 1000 postings — is the
#: most a crawl can ever collect, and asking for more hits an API boundary
#: rather than a bug.
PAGINATION_CEILING = 1000


class FatalListPageError(RuntimeError):
    """A non-retryable list-page response (any 4xx other than 429).

    Mirrors the JobStreet adapter: a 4xx that is not a rate limit is a caller
    bug or an API boundary, and retrying it only burns the backoff ladder.
    """


def _clean(text_list) -> str:
    return " ".join(t.strip() for t in text_list if t and t.strip()).strip()


def build_list_url(tpr: str, start: int, location: str = LOCATION, geo_id: str = GEO_ID) -> str:
    """組 LinkedIn Guest API list URL (RULES §4 query spec)。

    Args:
        tpr: LinkedIn f_TPR 值 (r3600 / r86400 / r259200 / r604800 / r1209600 / r1814400 / r2592000)
        start: 分頁 offset (0, 10, 20, ...)
        location: 顯示用城市/國家文字
        geo_id: LinkedIn geoId (預設 Singapore)
    """
    params = {
        "keywords": KEYWORDS,
        "location": location,
        "geoId": geo_id,
        "f_TPR": tpr,
        "sortBy": "DD",
        "start": str(start),
    }
    return LIST_API + "?" + urlencode(params)


def parse_list_page(html: str) -> list[dict]:
    """從 LinkedIn list HTML 解 jobs (RULES §4 欄位對照)。

    2026-11-21 fix: LinkedIn 的「合法空頁」是 26 bytes 的
    `<!DOCTYPE html>\\n\\n<!---->`; scrapling 對這種 body 建出的 root 是 None,
    `page.css(...)` 會直接 raise AttributeError → 整個 list crawl 中斷,
    該 city 的所有 chunk 全死 (2026-11-21 杭州三塊都是這樣死的, 0 列入表)。

    改成: body 解析不出 root → 當 0 筆, 讓 crawl_list 的 empty_streak 接手,
    後續頁繼續抓。這裡不對空頁做重試 — 空頁是合法的 EOF 訊號, 不是暫時性故障。
    """
    if not html or not html.strip():
        return []
    page = Adaptor(html)
    try:
        cards = page.css(JOB_CARD_SEL)
    except Exception:
        # 空頁 / 建不出 root → 0 筆, 不要讓整個 crawl 中斷
        return []
    jobs = []
    for card in cards:
        urn = (card.attrib.get("data-entity-urn") or "").strip()
        job_id = urn.rsplit(":", 1)[-1] if urn else ""

        title = _clean(card.css(TITLE_SEL + "::text").getall())
        company = _clean(card.css(COMPANY_SEL + "::text").getall())
        loc = _clean(card.css(LOC_SEL + "::text").getall())

        time_node = card.css(TIME_SEL)
        posted_at = ""
        posted_ago = ""
        if time_node:
            t = time_node[0]
            posted_at = (t.attrib.get("datetime") or "").strip()
            posted_ago = _clean(t.css("::text").getall())

        link_nodes = card.css(LINK_SEL)
        href = (link_nodes[0].attrib.get("href") if link_nodes else "") or ""

        if not job_id and not title:
            continue
        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": loc,
                "posted_at": posted_at,
                "posted_ago": posted_ago,
                "url": href or JOB_VIEW_URL.format(job_id=job_id),
                "source": SOURCE,  # 讓 push_to_sheet / enrich_with_jd 知道
            }
        )
    return jobs


def fetch_list_page(
    tpr: str,
    start: int,
    location: str = LOCATION,
    geo_id: str = GEO_ID,
    *,
    session,
    sleep: Callable[[float], None] = time.sleep,
    build_url: Callable[..., str] | None = None,
) -> str:
    """LinkedIn list page 帶 30/60/90s retry (對齊 cake/104 pattern, RULES §15.13 #11)。

    2026-10-07 fix: 原本沒 retry, list page 撞 429 → r.raise_for_status() → HTTPError
    → crawl_list line 2053 return all_jobs → 整個 list crawl hard abort。
    Sep 30 14d run 撞 page 13 abort, Oct 07 14d 撞 page 7 abort, 兩次都只跑 6-12 頁 (~57 jobs),
    coverage 嚴重不完整。Retry 後單頁最多撐 3.5 分鐘 (30+60+90 backoff)。

    429 / 5xx / connection error → sleep 30/60/90s → retry (共 4 次 attempt)。
    4xx (非 429) 直接 raise (`FatalListPageError`), 視為 caller bug 或 API 分頁天花板。

    2026-11-23 fix: 原本非 429 的 4xx 走 `r.raise_for_status()`, 而那個 HTTPError
    被 `except Exception` 接走 → 被重試 4 次 (白等 3 分鐘) 才 abort。start=1000 的
    分頁天花板 (HTTP 400) 就這樣拖慢整塊 crawl。

    Raises: FatalListPageError for a non-429 4xx; RuntimeError if all retries exhausted.
    """
    backoff = BACKOFF
    last_err = None
    url = (build_url or build_list_url)(tpr, start, location, geo_id)
    for attempt in range(4):
        try:
            r = session.get(
                url,
                impersonate="chrome",
                timeout=20,
                headers={"Accept-Language": "en-US,en;q=0.9"},
                proxies=resolve_proxies(),
            )
            if r.status_code == 200:
                return r.text
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                # 2026-11-23 fix: 原本在這裡 r.raise_for_status(), 而 HTTPError 會被
                # 下面的 `except Exception` 接走 → 非 429 的 4xx 被重試 4 次
                # (白等 30+60+90s) 才 abort, 跟 docstring 與凍結契約寫的
                # 「4xx (非 429) 直接 raise」都不符。改成跟 JobStreet adapter 一樣,
                # 用專屬例外立刻往外拋。
                raise FatalListPageError(f"linkedin list fetch failed: http {r.status_code}")
        except FatalListPageError:
            raise
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < 3:
            print(
                f"    [LINKEDIN LIST RETRY {attempt + 1}/3] start={start} 失敗 ({last_err}), sleep {backoff[attempt]}s",
                flush=True,
            )
            sleep(backoff[attempt])
    raise RuntimeError(f"linkedin list fetch failed after 4 attempts: {last_err}")


def build_jd_url(job_id: str) -> str:
    """LinkedIn JD API URL。"""
    return JD_API.format(job_id=job_id)


def fetch_jd(
    job_id: str,
    *,
    session,
    build_url: Callable[[str], str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """抓單一職缺的 JD 純文字。

    `session` 與 `build_url` 由 caller 注入, 所以這個模組不持有任何全域狀態。

    2026-11-21 fix: 429 原本一次就放棄 → 那一筆沒有 JD, 寫 Sheet 時會被整列跳過,
    職缺就這樣静默消失 (2026-11-21 上海 10 筆裡有 4 筆是這樣掉的)。
    改成跟 list fetch 同一套 30/60/90s 階梯 (共 4 次 attempt):
    429 / 5xx / 連線錯誤才重試, 其他 4xx 照舊立刻回錯誤。
    """
    url = (build_url or build_jd_url)(job_id)
    last_err = ""
    for attempt in range(4):
        try:
            r = session.get(
                url,
                impersonate="chrome",
                timeout=20,
                headers={"Accept-Language": "en-US,en;q=0.9"},
                proxies=resolve_proxies(),
            )
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            r = None

        if r is not None:
            if r.status_code == 200:
                break
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                # 其他 4xx 是 caller bug, 不重試
                return {"jd_text": None, "jd_html": None, "error": f"HTTP {r.status_code}"}

        if attempt < 3:
            sleep(BACKOFF[attempt])

    if r is None:
        return {"jd_text": None, "jd_html": None, "error": last_err}
    if r.status_code == 429:
        return {"jd_text": None, "jd_html": None, "error": "429 rate limited"}
    if r.status_code != 200:
        return {"jd_text": None, "jd_html": None, "error": f"HTTP {r.status_code}"}

    ap = Adaptor(r.text)
    desc_nodes = ap.css(JD_DESC_SEL)
    if not desc_nodes:
        return {"jd_text": None, "jd_html": None, "error": "no description node found"}

    desc = desc_nodes[0]
    # ★ 抓全部 ::text (包含裸文字節點，不只 p/li/h*/strong)
    all_text = desc.css("::text").getall()
    lines = []
    for t in all_text:
        t = t.strip()
        if t and len(t) > 1:
            lines.append(t)
    # 結構化版本 (給想看分段的)
    structured_lines = []
    for p in desc.css(JD_BLOCK_SEL):
        t = (p.css("::text").get() or "").strip()
        if t and len(t) > 1:
            structured_lines.append(t)

    return {
        "jd_text": "\n".join(lines) if lines else None,
        "jd_lines": structured_lines if structured_lines else lines,
        "jd_html": None,
        "error": None,
    }
