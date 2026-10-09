"""LinkedIn Guest API adapter.

This module owns LinkedIn URL construction, list parsing, and JD fetching while
`sg_product_jobs` retains compatibility wrappers for the v1.1.1 public surface.
Network sessions are injected by the orchestration layer so existing monkeypatch
and connection-pool behaviour remains observable at the legacy boundary.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

from scrapling.parser import Adaptor

DEFAULT_KEYWORDS = (
    '"product manager" OR "product director" OR "director of product" '
    'OR "head of product" OR "product lead" OR "chief of staff"'
)
DEFAULT_LOCATION = "Singapore"
DEFAULT_GEO_ID = "102454443"

JOB_CARD_SEL = "div.base-card"
TITLE_SEL = ".base-search-card__title"
COMPANY_SEL = "a.hidden-nested-link"
LOC_SEL = ".job-search-card__location"
TIME_SEL = "time"
LINK_SEL = "a.base-card__full-link"

JD_DESC_SEL = "div.description__text"
JD_BLOCK_SEL = (
    "div.description__text p, div.description__text li, "
    "div.description__text h1, div.description__text h2, "
    "div.description__text h3, div.description__text h4, "
    "div.description__text strong, div.description__text span"
)


def _clean(text_list) -> str:
    return " ".join(t.strip() for t in text_list if t and t.strip()).strip()


def build_list_url(
    tpr: str,
    start: int,
    location: str = DEFAULT_LOCATION,
    geo_id: str = DEFAULT_GEO_ID,
    *,
    keywords: str = DEFAULT_KEYWORDS,
) -> str:
    params = {
        "keywords": keywords,
        "location": location,
        "geoId": geo_id,
        "f_TPR": tpr,
        "sortBy": "DD",
        "start": str(start),
    }
    return "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)


def parse_list_page(html: str) -> list[dict]:
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
                "url": href or f"https://www.linkedin.com/jobs/view/{job_id}",
                "source": "linkedin",
            }
        )
    return jobs


def fetch_list_page(
    session,
    tpr: str,
    start: int,
    location: str = DEFAULT_LOCATION,
    geo_id: str = DEFAULT_GEO_ID,
    *,
    keywords: str = DEFAULT_KEYWORDS,
) -> str:
    """LinkedIn list page 帶 30/60/90s retry (對齊 cake/104 pattern).

    2026-10-07 fix: 原本沒 retry, list page 撞 429 → r.raise_for_status() → HTTPError
    → crawler 整個 list crawl hard abort, 只跑 6-12 頁 (~57 jobs) coverage 嚴重不完整。
    429 / 5xx / connection error → sleep 30/60/90s → retry (共 4 次 attempt)。
    4xx (非 429) 直接 raise, 視為 caller bug。
    Raises: RuntimeError if all retries exhausted.
    """
    backoff = [30, 60, 90]
    last_err = None
    url = build_list_url(tpr, start, location, geo_id, keywords=keywords)
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
                f"    [LINKEDIN LIST RETRY {attempt+1}/3] start={start} 失敗 ({last_err}), sleep {backoff[attempt]}s",
                flush=True,
            )
            time.sleep(backoff[attempt])
    raise RuntimeError(f"linkedin list fetch failed after 4 attempts: {last_err}")


def build_jd_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


def fetch_jd(session, job_id: str) -> dict:
    """Fetch one LinkedIn JD and return the v1.1.1 normalized payload."""
    try:
        r = session.get(
            build_jd_url(job_id),
            impersonate="chrome",
            timeout=20,
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )
    except Exception as exc:
        return {
            "jd_text": None,
            "jd_html": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if r.status_code == 429:
        return {"jd_text": None, "jd_html": None, "error": "429 rate limited"}
    if r.status_code != 200:
        return {"jd_text": None, "jd_html": None, "error": f"HTTP {r.status_code}"}

    ap = Adaptor(r.text)
    desc_nodes = ap.css(JD_DESC_SEL)
    if not desc_nodes:
        return {"jd_text": None, "jd_html": None, "error": "no description node found"}

    desc = desc_nodes[0]
    all_text = desc.css("::text").getall()
    lines = []
    for text in all_text:
        text = text.strip()
        if text and len(text) > 1:
            lines.append(text)

    structured_lines = []
    for node in desc.css(JD_BLOCK_SEL):
        text = (node.css("::text").get() or "").strip()
        if text and len(text) > 1:
            structured_lines.append(text)

    return {
        "jd_text": "\n".join(lines) if lines else None,
        "jd_lines": structured_lines if structured_lines else lines,
        "jd_html": None,
        "error": None,
    }
