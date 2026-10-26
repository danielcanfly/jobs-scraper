"""Characterization tests: 104 (onezerofour) list-page parsing.

Locks the current behaviour of ``parse_onezerofour_list_page``.  The 104 list
API returns a JSON ``data`` array; each entry carries both a 5-char job slug
(``link.job``) and an 8-digit job number (``jobNo``).  The *slug* is the
``job_id`` used everywhere else (Sheet E column, dedup keys); ``jobNo`` is
kept aside as ``job_no``.

Offline only: no network, no Sheet.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402


def _raw(
    *,
    job_no="12345678",
    job_name="Product Manager",
    cust_name="Acme Ltd",
    addr="台北市信義區",
    appear="2026-08-30",
    remote=0,
    link_job="https://www.104.com.tw/job/abcde",
):
    job = {
        "jobNo": job_no,
        "jobName": job_name,
        "custName": cust_name,
        "jobAddrNoDesc": addr,
        "appearDate": appear,
        "remoteWorkType": remote,
    }
    if link_job is not None:
        job["link"] = {"job": link_job}
    else:
        job["link"] = {}
    return job


def test_slug_is_the_job_id_and_job_no_is_kept_apart():
    """job_id == 5-char slug; the 8-digit jobNo lives in job_no."""
    out = M.parse_onezerofour_list_page([_raw()], keyword="Product Manager")
    assert len(out) == 1
    job = out[0]
    assert job["job_id"] == "abcde"
    assert job["job_no"] == "12345678"
    assert job["job_id"] != job["job_no"]


def test_required_fields_are_mapped():
    out = M.parse_onezerofour_list_page([_raw()], keyword="Product Manager")
    job = out[0]
    assert job["title"] == "Product Manager"
    assert job["company"] == "Acme Ltd"
    assert job["location"] == "台北市信義區"
    assert job["posted_at"] == "2026-08-30"
    assert job["url"] == "https://www.104.com.tw/job/abcde"
    assert job["source"] == "onezerofour"
    assert job["keyword_used"] == "Product Manager"


def test_trailing_slash_is_stripped():
    out = M.parse_onezerofour_list_page([_raw(link_job="https://www.104.com.tw/job/xyz12/")])
    job = out[0]
    assert job["job_id"] == "xyz12"
    assert job["url"] == "https://www.104.com.tw/job/xyz12"


def test_multiple_trailing_slashes_are_stripped():
    out = M.parse_onezerofour_list_page([_raw(link_job="https://www.104.com.tw/job/xyz12///")])
    assert out[0]["job_id"] == "xyz12"


def test_bare_slug_without_path_is_kept():
    out = M.parse_onezerofour_list_page([_raw(link_job="abcde")])
    assert out[0]["job_id"] == "abcde"
    assert out[0]["url"] == "https://www.104.com.tw/job/abcde"


def test_six_char_slug_is_supported():
    out = M.parse_onezerofour_list_page([_raw(link_job="https://www.104.com.tw/job/a1b2c3")])
    assert out[0]["job_id"] == "a1b2c3"


def test_missing_job_no_is_skipped():
    out = M.parse_onezerofour_list_page([_raw(job_no=None)])
    assert out == []


def test_empty_job_no_is_skipped():
    out = M.parse_onezerofour_list_page([_raw(job_no="")])
    assert out == []


def test_missing_link_is_skipped():
    out = M.parse_onezerofour_list_page([_raw(link_job=None)])
    assert out == []


def test_missing_link_job_is_skipped():
    out = M.parse_onezerofour_list_page([_raw(link_job="")])
    assert out == []


def test_empty_input_returns_empty_list():
    assert M.parse_onezerofour_list_page([]) == []


def test_work_mode_mapping_from_remote_work_type():
    """remoteWorkType: 0=Onsite / 1=Remote / 2=Hybrid (anything else => Onsite)."""
    out = M.parse_onezerofour_list_page([_raw(remote=0), _raw(remote=1), _raw(remote=2)])
    assert [j["work_mode"] for j in out] == ["Onsite", "Remote", "Hybrid"]


def test_unknown_remote_work_type_falls_back_to_onsite():
    out = M.parse_onezerofour_list_page([_raw(remote=7)])
    assert out[0]["work_mode"] == "Onsite"


def test_missing_remote_work_type_defaults_to_onsite():
    raw = _raw()
    del raw["remoteWorkType"]
    out = M.parse_onezerofour_list_page([raw])
    assert out[0]["work_mode"] == "Onsite"


def test_keyword_defaults_to_empty_string():
    out = M.parse_onezerofour_list_page([_raw()])
    assert out[0]["keyword_used"] == ""


def test_sheet_key_uses_the_slug_not_the_job_number():
    """The sheet dedup key for a 104 row is (onezerofour, <slug>)."""
    job = M.parse_onezerofour_list_page([_raw()])[0]
    # Rendered E-column value (gspread get_all_values() returns the rendered
    # HYPERLINK display text, not the formula source).
    row = ["New", "", "2026-08-30", "104 / Minimax", job["url"], "Acme Ltd", "PM", "JD", "TW", "Onsite", ""]
    key = M.parse_sheet_row_to_key(row)
    assert key == ("onezerofour", "abcde")
    assert key != ("onezerofour", "12345678")


def test_sheet_key_tolerates_a_trailing_slash_url():
    """A trailing slash is now tolerated, matching the list parser.

    ``parse_onezerofour_list_page`` strips a trailing slash off the 104 URL.
    ``parse_sheet_row_to_key`` used to require the slug to be followed by ``?``
    or end-of-string, so a hand-written trailing-slash E cell yielded no key —
    an asymmetry between the two parsers for the same URL shape. v1.4.0 makes
    the sheet-key parser accept the optional slash as well.
    """
    row = ["New", "", "2026-08-30", "104 / Minimax", "https://www.104.com.tw/job/xyz12/"]
    assert M.parse_sheet_row_to_key(row) == ("onezerofour", "xyz12")
    # ...and the slash-less form round-trips the same way.
    row_ok = ["New", "", "2026-08-30", "104 / Minimax", "https://www.104.com.tw/job/xyz12"]
    assert M.parse_sheet_row_to_key(row_ok) == ("onezerofour", "xyz12")


def test_sheet_key_rejects_slugs_outside_the_four_to_six_char_range():
    """The sheet-key regex only accepts a 4-6 char slug."""
    for too_short in ("abc", "ab"):
        row = ["New", "", "2026-08-30", "104 / Minimax", f"https://www.104.com.tw/job/{too_short}"]
        assert M.parse_sheet_row_to_key(row) is None
    for too_long in ("abcdefg", "abcdefgh"):
        row = ["New", "", "2026-08-30", "104 / Minimax", f"https://www.104.com.tw/job/{too_long}"]
        assert M.parse_sheet_row_to_key(row) is None
    # ...and a 4- and 6-char slug are fine.
    for ok in ("abcd", "abcdef"):
        row = ["New", "", "2026-08-30", "104 / Minimax", f"https://www.104.com.tw/job/{ok}"]
        assert M.parse_sheet_row_to_key(row) == ("onezerofour", ok)


def test_crawler_dedups_the_same_slug_across_keywords(monkeypatch):
    """The same job found under two keywords is collected once."""

    def fake_hit(keyword, page, isnew, max_retries=3):
        return [_raw(job_no="11111111", link_job="https://www.104.com.tw/job/dup01")]

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)
    jobs = M.crawl_onezerofour_list("1h", 1, keywords=["PM", "Product Manager"])
    assert [j["job_id"] for j in jobs] == ["dup01"]
