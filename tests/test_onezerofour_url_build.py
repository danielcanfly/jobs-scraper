"""Characterization tests: 104 (onezerofour) URL construction.

No upstream spec ever existed for this adapter (the original contract tests
lived in /tmp and were lost), so these tests lock the *current* behaviour of
``sg_product_jobs.py``.  Every assertion is offline: no network, no Sheet.

Assumption: the keyword set is env-overridable (``ONEZEROFOUR_KEYWORDS``), so
the keyword assertion is written to hold in both the default and the
overridden case instead of hard-coding one of them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402

# Default keyword set as baked into sg_product_jobs.py (used when the
# ONEZEROFOUR_KEYWORDS env var is empty, which is the case for the shipped .env).
DEFAULT_104_KEYWORDS = [
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


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


def test_list_api_base_url_constant():
    assert M.ONEZEROFOUR_LIST_API == "https://www.104.com.tw/jobs/search/api/jobs"
    assert M.ONEZEROFOUR_BASE_URL == "https://www.104.com.tw"


def test_list_url_exact_string():
    """Full URL is pinned byte-for-byte (param order comes from dict order)."""
    url = M.build_onezerofour_list_url("Product Manager", 1, 3)
    assert url == (
        "https://www.104.com.tw/jobs/search/api/jobs"
        "?area=6001001000%2C6001002000"
        "&keyword=Product+Manager"
        "&isnew=3"
        "&page=1"
        "&pagesize=20"
        "&order=15"
        "&mode=s"
        "&jobsource=m_joblist_search"
        "&searchJobs=1"
    )


def test_list_url_encodes_non_ascii_keyword():
    """Chinese keywords are percent-encoded UTF-8 by urlencode()."""
    url = M.build_onezerofour_list_url("產品經理", 2, 30)
    assert url == (
        "https://www.104.com.tw/jobs/search/api/jobs"
        "?area=6001001000%2C6001002000"
        "&keyword=%E7%94%A2%E5%93%81%E7%B6%93%E7%90%86"
        "&isnew=30"
        "&page=2"
        "&pagesize=20"
        "&order=15"
        "&mode=s"
        "&jobsource=m_joblist_search"
        "&searchJobs=1"
    )
    assert _query(url)["keyword"] == ["產品經理"]


def test_list_url_area_is_taipei_plus_new_taipei():
    q = _query(M.build_onezerofour_list_url("PM", 1, 0))
    assert q["area"] == ["6001001000,6001002000"]
    assert M.ONEZEROFOUR_AREAS == "6001001000,6001002000"


def test_list_url_fixed_query_params():
    q = _query(M.build_onezerofour_list_url("PM", 1, 0))
    assert q["pagesize"] == ["20"]
    assert q["order"] == ["15"]
    assert q["mode"] == ["s"]
    assert q["jobsource"] == ["m_joblist_search"]
    assert q["searchJobs"] == ["1"]


def test_list_url_page_is_one_indexed():
    for page in (1, 2, 7, 30):
        q = _query(M.build_onezerofour_list_url("PM", page, 7))
        assert q["page"] == [str(page)]


def test_list_url_isnew_values_follow_tpr_map():
    """isnew only accepts 0/3/7/14/30 upstream; 21d degrades to 30."""
    assert M.ONEZEROFOUR_TPR == {
        "1h": 0,
        "24h": 0,
        "3d": 3,
        "7d": 7,
        "14d": 14,
        "21d": 30,
        "30d": 30,
    }
    for rng, isnew in M.ONEZEROFOUR_TPR.items():
        q = _query(M.build_onezerofour_list_url("PM", 1, isnew))
        assert q["isnew"] == [str(isnew)], rng


def test_keyword_set_matches_env_or_default():
    raw = os.getenv("ONEZEROFOUR_KEYWORDS", "")
    expected = [k.strip() for k in raw.split(",") if k.strip()] if raw.strip() else DEFAULT_104_KEYWORDS
    assert M.ONEZEROFOUR_KEYWORDS == expected


def test_parser_accepts_both_cli_aliases():
    ap = M.build_arg_parser()
    choices = next(a.choices for a in ap._actions if "--source" in a.option_strings)
    assert "104" in choices
    assert "onezerofour" in choices
    assert ap.parse_args(["--source", "104"]).source == "104"
    assert ap.parse_args(["--source", "onezerofour"]).source == "onezerofour"


def _run_main(monkeypatch, tmp_path, argv):
    """Run main() with the 104 crawler faked out; returns (104 calls, linkedin calls)."""
    oof_calls: list[dict] = []
    li_calls: list[dict] = []

    def fake_oof(daterange, max_pages, keywords=None):
        oof_calls.append({"daterange": daterange, "max_pages": max_pages, "keywords": list(keywords or [])})
        return []

    def fake_li(tpr, max_pages, location=None, geo_id=None):
        li_calls.append({"tpr": tpr, "max_pages": max_pages})
        return []

    def unreachable(*a, **k):
        raise AssertionError("a non-104 crawler was dispatched")

    monkeypatch.setattr(M, "crawl_onezerofour_list", fake_oof)
    monkeypatch.setattr(M, "crawl_list", fake_li)
    monkeypatch.setattr(M, "crawl_jobstreet_list", unreachable)
    monkeypatch.setattr(M, "crawl_cake_list", unreachable)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["sg_product_jobs.py"] + argv)
    M.main()
    return oof_calls, li_calls


def test_cli_alias_104_and_onezerofour_hit_the_same_adapter(monkeypatch, tmp_path, capsys):
    a_calls, a_li = _run_main(monkeypatch, tmp_path, ["7d", "--source", "104"])
    a_out = capsys.readouterr().out
    b_calls, b_li = _run_main(monkeypatch, tmp_path, ["7d", "--source", "onezerofour"])
    b_out = capsys.readouterr().out

    assert a_calls == b_calls
    assert a_calls == [{"daterange": "7d", "max_pages": 15, "keywords": list(M.ONEZEROFOUR_KEYWORDS)}]
    assert a_li == b_li == []  # the LinkedIn crawler is never used
    assert a_out == b_out  # identical banner => identical routing
    assert "104 Jobs / Taiwan" in a_out


def test_cli_alias_normalisation_is_idempotent(monkeypatch, tmp_path, capsys):
    """'104' is rewritten to 'onezerofour' before any source-specific branch."""
    calls, _ = _run_main(monkeypatch, tmp_path, ["24h", "--source", "104"])
    assert len(calls) == 1
    assert calls[0]["max_pages"] == M.ONEZEROFOUR_MAX_PAGES["24h"] == 4


def test_max_pages_default_comes_from_104_table(monkeypatch, tmp_path):
    calls, _ = _run_main(monkeypatch, tmp_path, ["30d", "--source", "104"])
    assert calls[0]["max_pages"] == M.ONEZEROFOUR_MAX_PAGES["30d"] == 50


def test_explicit_max_pages_overrides_104_table(monkeypatch, tmp_path):
    calls, _ = _run_main(monkeypatch, tmp_path, ["30d", "--source", "104", "--max-pages", "3"])
    assert calls[0]["max_pages"] == 3


def test_crawler_uses_the_module_keyword_set(monkeypatch):
    """crawl_onezerofour_list() fans out over exactly M.ONEZEROFOUR_KEYWORDS."""
    seen_kw: list[str] = []

    def fake_hit(keyword, page, isnew, max_retries=3):
        seen_kw.append(keyword)
        return []

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)
    jobs = M.crawl_onezerofour_list("1h", 1)
    assert jobs == []
    assert sorted(seen_kw) == sorted(M.ONEZEROFOUR_KEYWORDS)


def test_crawler_maps_range_to_isnew(monkeypatch):
    captured: list[tuple[str, int, int]] = []

    def fake_hit(keyword, page, isnew, max_retries=3):
        captured.append((keyword, page, isnew))
        return []

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)
    M.crawl_onezerofour_list("3d", 1)
    assert {isnew for _, _, isnew in captured} == {3}


def test_crawler_pages_from_one_to_max_pages(monkeypatch):
    captured: list[tuple[str, int]] = []

    def fake_hit(keyword, page, isnew, max_retries=3):
        captured.append((keyword, page))
        return []

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)
    M.crawl_onezerofour_list("1h", 3, keywords=["PM"])
    assert captured == [("PM", 1), ("PM", 2), ("PM", 3)]
