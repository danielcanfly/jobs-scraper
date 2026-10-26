"""Characterization tests: Cake search-response parsing.

The Cake search API returns a ``data`` array; each entry carries the job
``path`` (the stable job_id), the hiring company's ``page`` block, a
``locations`` list and a ``description``.

Key behaviour pinned here: the row Location comes from ``locations[0]`` and is
*not* overwritten by the search scope ("Global"), so a Taipei job stays Taipei
in the Sheet.

Offline only: no network, no Sheet.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402


def _entry(
    *,
    path="senior-product-manager-1234",
    page_path="acme-corp",
    page_name="Acme Corp",
    geo_state="Singapore",
    title="Senior Product Manager",
    description="We are hiring a senior product manager to own the roadmap.",
    locations=("Taipei City", "Singapore"),
    updated="2026-08-30T10:00:00Z",
):
    entry = {
        "path": path,
        "page": {"path": page_path, "name": page_name, "geo": {"state_name": geo_state}},
        "title": title,
        "description": description,
        "content_updated_at": updated,
        "job_source": "cake",
        "job_type": "full_time",
        "seniority_level": "director",
    }
    if locations is not None:
        entry["locations"] = list(locations)
    return entry


def _page(*entries):
    return {"data": list(entries)}


def test_job_id_is_the_job_path():
    jobs = M.parse_cake_search_page(_page(_entry()), "product manager")
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "senior-product-manager-1234"
    assert jobs[0]["path"] == "senior-product-manager-1234"


def test_url_is_built_from_page_path_and_job_path():
    jobs = M.parse_cake_search_page(_page(_entry()), "product manager")
    assert jobs[0]["url"] == ("https://www.cake.me/companies/acme-corp/jobs/senior-product-manager-1234")
    assert jobs[0]["page_path"] == "acme-corp"


def test_locations_first_element_is_the_row_location():
    """locations[0] wins over the search scope and over page.geo."""
    jobs = M.parse_cake_search_page(_page(_entry(locations=["Taipei City", "Singapore"])), "pm")
    assert jobs[0]["location"] == "Taipei City"


def test_row_location_is_not_overwritten_by_the_search_scope():
    """The Sheet row keeps the job's own location, not CAKE_LOCATION_SCOPE."""
    jobs = M.parse_cake_search_page(_page(_entry(locations=["Taipei City"])), "pm")
    row = M._build_sheet_row(
        {**jobs[0], "jd_text": "Product manager role in Taipei."},
        M.CAKE_SHEET_SOURCE_LABEL,
        M.CAKE_LOCATION_SCOPE,
        set(),
    )
    assert row[8] == "Taipei City"
    assert row[8] != M.CAKE_LOCATION_SCOPE


def test_location_falls_back_to_page_geo_when_locations_missing():
    jobs = M.parse_cake_search_page(_page(_entry(locations=None)), "pm")
    assert jobs[0]["location"] == "Singapore"


def test_location_falls_back_to_page_geo_when_locations_empty():
    jobs = M.parse_cake_search_page(_page(_entry(locations=[])), "pm")
    assert jobs[0]["location"] == "Singapore"


def test_missing_job_path_is_skipped():
    entry = _entry()
    del entry["path"]
    assert M.parse_cake_search_page(_page(entry), "pm") == []


def test_empty_job_path_is_skipped():
    assert M.parse_cake_search_page(_page(_entry(path="")), "pm") == []


def test_missing_page_path_is_skipped():
    entry = _entry()
    del entry["page"]["path"]
    assert M.parse_cake_search_page(_page(entry), "pm") == []


def test_empty_page_path_is_skipped():
    assert M.parse_cake_search_page(_page(_entry(page_path="")), "pm") == []


def test_empty_response_yields_no_jobs():
    assert M.parse_cake_search_page({"data": []}, "pm") == []
    assert M.parse_cake_search_page({}, "pm") == []


def test_company_comes_from_page_name():
    jobs = M.parse_cake_search_page(_page(_entry(page_name="Acme Corp")), "pm")
    assert jobs[0]["company"] == "Acme Corp"
    assert jobs[0]["page_name"] == "Acme Corp"


def test_title_is_stripped():
    jobs = M.parse_cake_search_page(_page(_entry(title="  Senior Product Manager  ")), "pm")
    assert jobs[0]["title"] == "Senior Product Manager"


def test_source_and_keyword_are_recorded():
    jobs = M.parse_cake_search_page(_page(_entry()), "product manager")
    assert jobs[0]["source"] == "cake"
    assert jobs[0]["keyword_used"] == "product manager"


def test_posted_at_and_content_updated_at_are_kept():
    jobs = M.parse_cake_search_page(_page(_entry(updated="2026-08-30T10:00:00Z")), "pm")
    assert jobs[0]["posted_at"] == "2026-08-30T10:00:00Z"
    assert jobs[0]["content_updated_at"] == "2026-08-30T10:00:00Z"


def test_description_is_preserved_for_the_jd_fallback():
    desc = "We are hiring a senior product manager to own the roadmap."
    jobs = M.parse_cake_search_page(_page(_entry(description=desc)), "pm")
    assert jobs[0]["description"] == desc


def test_job_metadata_fields_are_kept():
    jobs = M.parse_cake_search_page(_page(_entry()), "pm")
    assert jobs[0]["job_source"] == "cake"
    assert jobs[0]["job_type"] == "full_time"
    assert jobs[0]["seniority_level"] == "director"


def test_work_mode_is_derived_from_description_and_title():
    """Title prefix wins: 'Remote - <title>' => Remote."""
    jobs = M.parse_cake_search_page(
        _page(_entry(description="Plain description.", title="Remote - Senior Product Manager")),
        "pm",
    )
    assert jobs[0]["work_mode"] == "Remote"


def test_work_mode_is_derived_from_the_description_fallback():
    jobs = M.parse_cake_search_page(
        _page(_entry(description="This is a fully remote role, work from home.")),
        "pm",
    )
    assert jobs[0]["work_mode"] == "Remote"


def test_work_mode_is_empty_when_nothing_matches():
    jobs = M.parse_cake_search_page(_page(_entry(description="Plain description.")), "pm")
    assert jobs[0]["work_mode"] == ""


def test_sheet_key_for_cake_row_uses_the_job_path():
    jobs = M.parse_cake_search_page(_page(_entry()), "pm")
    row = [
        "New",
        "",
        "2026-08-30",
        "Cake / Minimax",
        jobs[0]["url"],
        "Acme Corp",
        "Senior Product Manager",
        "JD",
        "Taipei City",
        "",
        "",
    ]
    assert M.parse_sheet_row_to_key(row) == ("cake", "senior-product-manager-1234")
