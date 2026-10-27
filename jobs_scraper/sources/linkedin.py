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

import time
from typing import Callable
from urllib.parse import urlencode

from scrapling.parser import Adaptor

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
}
# 不放 f_WT → onsite/remote/hybrid 全收
PAGE_SIZE = 10  # Guest API 實際 page size (不是 25)

# time range 預設值 + 各 range 的 MAX_PAGES 建議
TIME_RANGES = {
    "1h": ("r3600", 1),
    "24h": ("r86400", 4),
    "3d": ("r259200", 7),
    "7d": ("r604800", 15),
    "14d": ("r1209600", 30),
    "21d": ("r1814400", 30),  # 3 週
    "30d": ("r2592000", 25),
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
    """從 LinkedIn list HTML 解 jobs (RULES §4 欄位對照)。"""
    page = Adaptor(html)
    jobs = []
    for card in page.css(JOB_CARD_SEL):
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
    4xx (非 429) 直接 raise, 視為 caller bug。
    Raises: RuntimeError if all retries exhausted.
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
            )
            if r.status_code == 200:
                return r.text
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                r.raise_for_status()
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
) -> dict:
    """抓單一職缺的 JD 純文字。

    `session` 與 `build_url` 由 caller 注入, 所以這個模組不持有任何全域狀態。
    """
    try:
        r = session.get(
            (build_url or build_jd_url)(job_id),
            impersonate="chrome",
            timeout=20,
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )
    except Exception as e:
        return {"jd_text": None, "jd_html": None, "error": f"{type(e).__name__}: {e}"}

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
