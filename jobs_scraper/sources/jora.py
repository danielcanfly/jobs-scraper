"""Jora SG HTML adapter.

This module owns Jora URL construction, list parsing, JD fetching, and list crawl
retry behaviour while `sg_product_jobs` retains compatibility wrappers for the
legacy public surface. Sessions and sleep functions are injected by the
orchestration layer so existing monkeypatch and pacing behaviour remains
observable at the root module boundary.
"""

from __future__ import annotations

import re
import time

from scrapling.parser import Adaptor

DEFAULT_KEYWORD = "product manager"
DEFAULT_LOCATION = "Singapore"
BASE_URL = "https://sg.jora.com"


def build_list_url(
    jora_tpr: str,
    page: int,
    keyword: str = DEFAULT_KEYWORD,
    location: str = DEFAULT_LOCATION,
) -> str:
    """Build the Jora list URL. Page starts from 1, not 0."""
    return f"{BASE_URL}/j?a={jora_tpr}&l={location}&q={keyword.replace(' ', '+')}&p={page}"


def parse_list_page(html: str, location: str = DEFAULT_LOCATION) -> list[dict]:
    """Parse Jora list HTML. job_id is the 32-character hex URL suffix."""
    ap = Adaptor(html)
    seen: set[str] = set()
    jobs: list[dict] = []
    for href in ap.css("a[href*='/job/']::attr(href)").getall():
        match = re.search(r"/job/.+?-([a-f0-9]{32})(?:\?|&|$)", href)
        if not match:
            continue
        job_id = match.group(1)
        if job_id in seen:
            continue
        seen.add(job_id)
        if href.startswith("http"):
            url = href
        else:
            url = f"{BASE_URL}{href}" if href.startswith("/") else f"{BASE_URL}/{href}"
        slug_match = re.search(r"/job/([^?]+)\?", href)
        title_slug = slug_match.group(1) if slug_match else ""
        title = re.sub(r"-[a-f0-9]{32}$", "", title_slug).replace("-", " ")
        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "company": "",
                "location": location,
                "posted_at": "",
                "posted_ago": "",
                "url": url,
                "source": "jora",
            }
        )
    return jobs


def fetch_jd(session, url: str, *, sleep_fn=time.sleep) -> dict:
    """Fetch one Jora detail page and return the v1.1.1 normalized payload."""
    response = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=20, impersonate="chrome")
        except Exception as exc:
            return {
                "jd_text": None,
                "jd_lines": None,
                "jd_html": None,
                "company": "",
                "location": "",
                "title": "",
                "error": str(exc),
            }
        if response.status_code == 200:
            break
        if response.status_code == 403:
            wait = 30 * (attempt + 1)
            print(f"            403 → wait {wait}s (attempt {attempt + 1}/3)")
            sleep_fn(wait)
            continue
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"HTTP {response.status_code}",
        }
    else:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": "HTTP 403 重試失敗",
        }

    if response is None or response.status_code != 200:
        status = response.status_code if response is not None else "unknown"
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"HTTP {status}",
        }

    ap = Adaptor(response.text)
    jd_divs = ap.css("div[class*='job-detail']")
    if not jd_divs:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": "no job-detail div",
        }

    jd_text = " ".join(jd_divs[0].css("::text").getall()).strip()
    jd_lines = [text.strip() for text in jd_divs[0].css("::text").getall() if text.strip() and len(text.strip()) > 1]

    main = ap.css("main")
    h1 = ap.css("h1::text").getall()
    title = h1[0].strip() if h1 else ""
    company = ""
    location_text = ""
    next_el = ap.css("h1 + *")
    if next_el:
        meta_chunks = [text.strip() for text in next_el[0].css("::text").getall() if text.strip()]
        if meta_chunks:
            parts = [part for part in meta_chunks if part not in ("–", "-", "/", "|")]
            if parts:
                company = parts[0]
            if len(parts) > 1:
                location_text = parts[1]

    if not company and main:
        for text in main[0].css("::text").getall()[:20]:
            text = text.strip()
            if not text:
                continue
            if text in ("View or apply for job", "Save job", "–", "-", "/"):
                continue
            if "reviews at" in text.lower():
                continue
            if 1 < len(text) < 80 and not text.startswith(
                (
                    "4.",
                    "5.",
                    "Permanent",
                    "Full",
                    "Part",
                    "Contract",
                    "2d",
                    "3d",
                    "1d",
                    "5d",
                    "6d",
                    "1w",
                    "2w",
                    "Today",
                    "Yesterday",
                )
            ):
                company = text
                break

    return {
        "jd_text": jd_text if jd_text else None,
        "jd_lines": jd_lines if jd_lines else None,
        "jd_html": None,
        "company": company,
        "location": location_text,
        "title": title,
        "error": None if jd_text else "empty JD",
    }


def crawl_list(
    session,
    tpr: str,
    max_pages: int,
    *,
    tpr_map: dict[str, str],
    keyword: str = DEFAULT_KEYWORD,
    location: str = DEFAULT_LOCATION,
    sleep_fn=None,
) -> list[dict]:
    """Crawl Jora list pages with v1.1.1 retry and pagination semantics."""
    seen: set[str] = set()
    all_jobs: list[dict] = []
    for page in range(1, max_pages + 1):
        print(f"\n  [jora list page {page}]")
        response = None
        for attempt in range(3):
            try:
                url = build_list_url(tpr_map[tpr], page, keyword, location)
                response = session.get(url, timeout=20, impersonate="chrome")
            except Exception as exc:
                print(f"            FAIL: {type(exc).__name__}: {exc}")
                return all_jobs
            if response.status_code == 200:
                break
            if response.status_code == 403:
                wait = 30 * (attempt + 1)
                print(f"            403 → wait {wait}s (attempt {attempt + 1}/3)")
                time.sleep(wait)
                continue
            print(f"            FAIL: HTTP {response.status_code}")
            return all_jobs
        if response is None or response.status_code != 200:
            print("            FAIL: HTTP 403 重試失敗, 放棄此頁")
            return all_jobs
        jobs = parse_list_page(response.text, location=location)
        new_jobs = [job for job in jobs if job["job_id"] not in seen]
        for job in new_jobs:
            seen.add(job["job_id"])
            all_jobs.append(job)
        print(
            f"            收 {len(jobs)}, 新增 {len(new_jobs)}, 重複 {len(jobs) - len(new_jobs)}, 累計 {len(all_jobs)}"
        )
        if not new_jobs or len(jobs) == 0 or len(new_jobs) < 10:
            print("            到底了")
            break
        if page < max_pages:
            if sleep_fn is None:
                time.sleep(0)
            else:
                sleep_fn("list")
    return all_jobs
