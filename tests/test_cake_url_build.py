"""Characterization tests: Cake URL / payload construction.

Cake is a POST-JSON source: the "URL" is really (a) the search endpoint plus a
JSON payload, and (b) the public detail page URL built from the company's page
path and the job path.

Offline only: no network, no Sheet.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402

# Default keyword set as baked into sg_product_jobs.py (used when the
# CAKE_KEYWORDS env var is empty).
DEFAULT_CAKE_KEYWORDS = [
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


def test_api_base_urls():
    assert M.CAKE_API_BASE == "https://api.cake.me/api/client/v2"
    assert M.CAKE_WEB_BASE == "https://www.cake.me"
    assert M.CAKE_LIST_API == "https://api.cake.me/api/client/v2/jobs/search"


def test_detail_page_url_template():
    assert M.CAKE_DETAIL_PAGE_URL == "https://www.cake.me/companies/{page_path}/jobs/{job_path}"


def test_detail_url_uses_companies_page_and_jobs_path():
    assert M.build_cake_detail_url("acme-corp", "senior-product-manager-1234") == (
        "https://www.cake.me/companies/acme-corp/jobs/senior-product-manager-1234"
    )


def test_detail_url_keeps_hyphenated_paths_intact():
    url = M.build_cake_detail_url("some-company-ltd-2", "product-lead-b2b-saas-99")
    assert url == "https://www.cake.me/companies/some-company-ltd-2/jobs/product-lead-b2b-saas-99"
    assert url.count("/") == 6  # https:// + host + companies + page + jobs + job


def test_search_payload_exact_shape():
    payload = M.build_cake_search_payload("product manager", 2)
    assert payload == {
        "query": "product manager",
        "filters": {
            "job_source": ["cake", "external"],
            "job_types": ["full_time"],
            "locations": [
                "香港",
                "Singapore",
                "United States",
                "Taipei City",
                "China",
                "台北市, 台灣",
                "新北市, 台灣",
                "New Taipei City",
            ],
            "seniority_levels": ["mid_senior_level", "executive", "director"],
        },
        "sort_by": "latest",
        "page": 2,
        "per_page": 10,
    }


def test_search_payload_page_is_one_indexed_int():
    for page in (1, 2, 15):
        payload = M.build_cake_search_payload("PM", page)
        assert payload["page"] == page
        assert isinstance(payload["page"], int)


def test_search_payload_per_page_default():
    assert M.CAKE_PAGE_SIZE == 10
    assert M.build_cake_search_payload("PM", 1)["per_page"] == 10
    assert M.build_cake_search_payload("PM", 1, per_page=25)["per_page"] == 25


def test_search_payload_filter_overrides():
    payload = M.build_cake_search_payload(
        "PM",
        1,
        locations=["Taipei City"],
        job_types=["part_time"],
        seniority_levels=["entry_level"],
        job_source=["cake"],
    )
    assert payload["filters"]["locations"] == ["Taipei City"]
    assert payload["filters"]["job_types"] == ["part_time"]
    assert payload["filters"]["seniority_levels"] == ["entry_level"]
    assert payload["filters"]["job_source"] == ["cake"]


def test_sort_by_default_is_latest():
    """CAKE_SORT_BY defaults to 'latest' (popularity cannot prove coverage)."""
    if os.getenv("CAKE_SORT_BY", "").strip():
        assert M.CAKE_SORT_BY == os.getenv("CAKE_SORT_BY").strip()
    else:
        assert M.CAKE_SORT_BY == "latest"
    assert M.build_cake_search_payload("PM", 1)["sort_by"] == M.CAKE_SORT_BY


def test_sort_by_is_passed_through_when_overridden():
    assert M.build_cake_search_payload("PM", 1, sort_by="popularity")["sort_by"] == "popularity"


def test_keyword_set_matches_env_or_default():
    raw = os.getenv("CAKE_KEYWORDS", "")
    expected = [k.strip() for k in raw.split(",") if k.strip()] if raw.strip() else DEFAULT_CAKE_KEYWORDS
    assert M.CAKE_KEYWORDS == expected


def test_location_scope_is_global():
    """Cake's search scope is 'Global'; it is metadata, never a row Location."""
    assert M.CAKE_LOCATION_SCOPE == "Global"
    assert M.CAKE_SHEET_SOURCE_LABEL == "Cake / Minimax"
