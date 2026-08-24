"""JobStreet SG API + GraphQL adapter.

This module owns JobStreet URL construction, list API parsing, JD fetching, and
multi-keyword crawl behaviour. The legacy root module injects network sessions
and sleep functions so monkeypatch and pacing boundaries remain observable.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

TPR = {
    "1h": "1",
    "24h": "1",
    "3d": "3",
    "7d": "7",
    "14d": "14",
    "21d": "21",
    "30d": "30",
}

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
DEFAULT_LOCATION = "Singapore"
LIST_API = "https://sg.jobstreet.com/api/jobsearch/v5/search"
GRAPHQL = "https://sg.jobstreet.com/graphql"
BASE_URL = "https://sg.jobstreet.com"
WORKTYPE_FT = "242"
DEFAULT_PAGE_SIZE = 20

JOBSTREET_DETAIL_QUERY = """
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


def build_list_url(
    keyword: str,
    page: int,
    daterange: str,
    *,
    worktype: str = WORKTYPE_FT,
    where: str = DEFAULT_LOCATION,
    page_size: int = DEFAULT_PAGE_SIZE,
    list_api: str = LIST_API,
) -> str:
    """Build the JobStreet list API URL."""
    params = {
        "siteKey": "SG-Main",
        "keywords": keyword,
        "where": where,
        "worktype": worktype,
        "daterange": str(daterange),
        "page": str(page),
        "pageSize": str(page_size),
    }
    return f"{list_api}?{urlencode(params)}"


def parse_list_page(data: dict, keyword: str) -> list[dict]:
    """Parse JobStreet list API JSON into the v1.1.1 normalized row shape."""
    jobs_raw = data.get("data") or []
    out = []
    for job in jobs_raw:
        job_id = job.get("id")
        if not job_id:
            continue

        emp = job.get("employer") or {}
        adv = job.get("advertiser") or {}
        company = emp.get("name") or adv.get("description") or job.get("companyName") or ""

        locations = job.get("locations") or []
        location_label = locations[0].get("label", "") if locations else ""

        work_mode = ""
        arrangements = (job.get("workArrangements") or {}).get("data") or []
        if arrangements and isinstance(arrangements, list) and arrangements[0].get("label"):
            work_mode = arrangements[0]["label"].get("text", "")
            work_mode = work_mode.replace("On-site", "Onsite")

        out.append(
            {
                "job_id": str(job_id),
                "title": job.get("title", ""),
                "company": company,
                "location": location_label,
                "posted_at": job.get("listingDate", ""),
                "posted_ago": job.get("listingDateDisplay", ""),
                "work_mode": work_mode,
                "teaser": job.get("teaser", ""),
                "url": "",
                "keyword_used": keyword,
                "source": "jobstreet",
            }
        )
    return out


def fetch_jd(
    session,
    job_id: str,
    *,
    graphql_url: str = GRAPHQL,
    query: str = JOBSTREET_DETAIL_QUERY,
) -> dict:
    """Fetch one JobStreet GraphQL JD and return the v1.1.1 payload shape."""
    try:
        response = session.post(
            graphql_url,
            json={"query": query, "variables": {"jobId": str(job_id)}},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=30,
            impersonate="chrome",
        )
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

    if response.status_code != 200:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"HTTP {response.status_code}",
        }

    try:
        data = response.json()
    except Exception as exc:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"JSON fail: {exc}",
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

    content_html = job.get("content") or ""
    if content_html:
        soup = BeautifulSoup(content_html, "html.parser")
        jd_text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()
        jd_lines = [text.strip() for text in soup.stripped_strings if len(text.strip()) > 1]
    else:
        jd_text = None
        jd_lines = None

    advertiser = job.get("advertiser") or {}
    location = job.get("location") or {}
    return {
        "jd_text": jd_text,
        "jd_lines": jd_lines,
        "jd_html": content_html or None,
        "company": advertiser.get("name", ""),
        "location": (location.get("label") if isinstance(location, dict) else "") or "",
        "title": job.get("title", ""),
        "error": None if jd_text else "empty JD",
    }


def crawl_list(
    session,
    daterange: str,
    max_pages: int,
    *,
    keywords: list[str] | None = None,
    worktype: str = WORKTYPE_FT,
    where: str = DEFAULT_LOCATION,
    page_size: int = DEFAULT_PAGE_SIZE,
    list_api: str = LIST_API,
    sleep_fn=None,
) -> list[dict]:
    """Crawl multiple JobStreet keywords with v1.1.1 dedup and soft-stop rules."""
    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    seen: set[str] = set()
    all_jobs: list[dict] = []
    for keyword in keywords:
        keyword_seen: set[str] = set()
        for page in range(1, max_pages + 1):
            url = build_list_url(
                keyword,
                page,
                daterange,
                worktype=worktype,
                where=where,
                page_size=page_size,
                list_api=list_api,
            )
            try:
                response = session.get(url, timeout=20, impersonate="chrome")
            except Exception as exc:
                print(f"  [jobstreet {keyword} p{page}] FAIL: {type(exc).__name__}: {exc}")
                return all_jobs
            if response.status_code != 200:
                print(f"  [jobstreet {keyword} p{page}] FAIL: HTTP {response.status_code}")
                return all_jobs
            try:
                data = response.json()
            except Exception as exc:
                print(f"  [jobstreet {keyword} p{page}] FAIL JSON: {exc}")
                return all_jobs

            jobs = parse_list_page(data, keyword)
            new_jobs = [job for job in jobs if job["job_id"] not in seen and job["job_id"] not in keyword_seen]
            for job in new_jobs:
                keyword_seen.add(job["job_id"])
                seen.add(job["job_id"])
                all_jobs.append(job)

            total_count = data.get("totalCount", "?")
            print(
                f"  [jobstreet {keyword} p{page}] 收 {len(jobs):3} | 新增 {len(new_jobs):3} "
                f"| kw 累計 {len(keyword_seen):3} | 跨 kw 累計 {len(all_jobs):3} "
                f"| totalCount={total_count}"
            )

            if not new_jobs or len(new_jobs) < 10 or len(jobs) == 0:
                print("            50% 軟停 (新增 < 10 或 jobs 空)")
                break
            if page < max_pages:
                if sleep_fn is not None:
                    sleep_fn("list")
    return all_jobs
