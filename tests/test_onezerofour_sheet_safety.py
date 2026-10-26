"""Characterization tests: 104 (onezerofour) Sheet routing + write safety.

Three guarantees are pinned here:

1. 104 always lands on the TW-Raw worksheet gid 764063873 (it is a
   Taiwan-intake source, not an SG one).
2. The 104 area list is hard-wired to Taipei + New Taipei; ``--location`` can
   never change it.
3. The E column is a HYPERLINK formula built with the "104 / Minimax" source
   label, and it is the *last* thing written (USER_ENTERED), after every
   scraped text column has been written RAW.

No test touches the real Google Sheet: gspread is replaced by a fake client and
the worksheet by a recorder object.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gspread  # noqa: E402
from google.oauth2 import service_account  # noqa: E402

import sg_product_jobs as M  # noqa: E402


class _RecordingWorksheet:
    """Fake gspread worksheet: records update() calls, never talks to Google."""

    def __init__(self, rows=None, row_count=100):
        self.rows = rows if rows is not None else []
        self.row_count = row_count
        self.updates: list[dict] = []
        self.added_rows = 0
        self.requested_gid = None

    def get_all_values(self):
        return self.rows

    def add_rows(self, n):
        self.added_rows += n
        self.row_count += n

    def update(self, range_name=None, values=None, value_input_option=None):
        self.updates.append({"range": range_name, "values": values, "value_input_option": value_input_option})


class _FakeSpreadsheet:
    def __init__(self, ws):
        self.ws = ws

    def get_worksheet_by_id(self, gid):
        self.ws.requested_gid = gid
        return self.ws


class _FakeClient:
    def __init__(self, ws):
        self.sh = _FakeSpreadsheet(ws)
        self.opened_key = None

    def open_by_key(self, key):
        self.opened_key = key
        return self.sh


def _install_fake_gspread(monkeypatch, ws):
    client = _FakeClient(ws)
    monkeypatch.setattr(gspread, "authorize", lambda creds, session=None: client)
    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_file",
        staticmethod(lambda *a, **k: object()),
    )
    monkeypatch.setattr(M, "SG_RAW_SHEET_ID", "fake-sheet-id")
    return client


def _job(**overrides):
    job = {
        "job_id": "abcde",
        "job_no": "12345678",
        "title": "Product Manager",
        "company": "Acme Ltd",
        "location": "台北市信義區",
        "source": "onezerofour",
        "work_mode": "Onsite",
        "url": "https://www.104.com.tw/job/abcde",
        "jd_text": "We are hiring a product manager in Taipei.",
    }
    job.update(overrides)
    return job


# ── 1) TW-Raw routing ────────────────────────────────────────────────────────
def test_tw_raw_gid_constant():
    assert M.ONEZEROFOUR_TW_RAW_GID == 764063873
    assert M.CAKE_TW_RAW_GID == 764063873


def test_104_label_reads_the_tw_raw_tab(monkeypatch):
    ws = _RecordingWorksheet(rows=[["Status", "Source", "URL"]])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("104 / Minimax")
    assert ws.requested_gid == 764063873


def test_104_and_cake_share_the_tw_raw_tab(monkeypatch):
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("104 / Minimax")
    gid_104 = ws.requested_gid
    M._load_sheet_keys_for_source("Cake / Minimax")
    assert ws.requested_gid == gid_104 == 764063873


def test_linkedin_label_reads_a_different_tab(monkeypatch):
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("LinkedIn / Minimax")
    assert ws.requested_gid == M.SG_RAW_GID
    assert ws.requested_gid != 764063873


def test_unknown_sheet_label_is_rejected(monkeypatch):
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    try:
        M._load_sheet_keys_for_source("Bogus / Minimax")
    except ValueError as e:
        assert "未知 sheet_source_label" in str(e)
    else:
        raise AssertionError("expected ValueError")


def _run_104_main_with_sheet(monkeypatch, tmp_path, extra_argv):
    """Drive main() up to the push_to_sheet call with everything faked."""
    captured: dict = {}

    def fake_crawl(daterange, max_pages, keywords=None):
        return [_job()]

    def fake_push(jobs, sheet_url, **kwargs):
        captured.update(kwargs)
        captured["sheet_url"] = sheet_url
        return {"written": 0}

    def fake_enrich(jobs, **kwargs):
        return jobs, {"total": len(jobs), "skipped": 0, "cached": 0, "fetched": 0, "failed": 0}

    def unreachable(*a, **k):
        # Any other source crawler reaching main() means the routing regressed;
        # fail loudly instead of letting a real request escape.
        raise AssertionError("a non-104 crawler was dispatched")

    monkeypatch.setattr(M, "crawl_onezerofour_list", fake_crawl)
    monkeypatch.setattr(M, "push_to_sheet", fake_push)
    monkeypatch.setattr(M, "enrich_with_jd", fake_enrich)
    monkeypatch.setattr(M, "load_jd_cache_from_jsons", lambda **kw: {})
    monkeypatch.setattr(M, "crawl_list", unreachable)
    monkeypatch.setattr(M, "crawl_jobstreet_list", unreachable)
    monkeypatch.setattr(M, "crawl_cake_list", unreachable)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["sg_product_jobs.py", "1h", "--source", "104", "--with-jd"] + extra_argv)
    M.main()
    return captured


def test_main_routes_104_to_the_tw_raw_gid(monkeypatch, tmp_path, capsys):
    """main() defaults --gid to the TW-Raw gid for 104 (unless --gid given)."""
    captured = _run_104_main_with_sheet(
        monkeypatch,
        tmp_path,
        ["--to-sheet", "https://docs.google.com/spreadsheets/d/FAKE/edit#gid=1"],
    )
    assert captured["gid"] == 764063873
    assert captured["source"] == "104 / Minimax"
    assert captured["location"] == "Taiwan"
    # The banner carries the hard-wired area + Taiwan location.
    out = capsys.readouterr().out
    assert "104 Jobs / Taiwan" in out
    assert "area=6001001000,6001002000" in out


def test_explicit_gid_overrides_the_tw_raw_default(monkeypatch, tmp_path):
    captured = _run_104_main_with_sheet(
        monkeypatch,
        tmp_path,
        ["--gid", "42", "--to-sheet", "https://docs.google.com/spreadsheets/d/FAKE/edit#gid=1"],
    )
    assert captured["gid"] == 42


# ── 2) Area list is hard-wired ──────────────────────────────────────────────
def test_area_constant_is_taipei_plus_new_taipei():
    assert M.ONEZEROFOUR_AREAS == "6001001000,6001002000"


def test_area_is_not_derivable_from_location():
    """--location never reaches the 104 area parameter."""
    from urllib.parse import parse_qs, urlsplit

    for location in ("Singapore", "Japan", "Taipei City", "Taiwan"):
        url = M.build_onezerofour_list_url("PM", 1, 0)
        assert parse_qs(urlsplit(url).query)["area"] == ["6001001000,6001002000"]
        assert M.ONEZEROFOUR_LOCATION == "Taiwan"


def test_crawler_never_overrides_the_area_parameter(monkeypatch):
    """crawl_onezerofour_list -> hit_onezerofour_list -> default areas only."""
    from urllib.parse import parse_qs, urlsplit

    urls: list[str] = []

    def fake_hit(keyword, page, isnew, max_retries=3):
        urls.append(M.build_onezerofour_list_url(keyword, page, isnew))
        return []

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)
    M.crawl_onezerofour_list("1h", 1, keywords=["PM"])
    assert urls
    for u in urls:
        assert parse_qs(urlsplit(u).query)["area"] == ["6001001000,6001002000"]


def test_main_with_foreign_location_still_uses_tw_area(monkeypatch, tmp_path, capsys):
    urls: list[str] = []

    def fake_hit(keyword, page, isnew, max_retries=3):
        urls.append(M.build_onezerofour_list_url(keyword, page, isnew))
        return []

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["sg_product_jobs.py", "1h", "--source", "104", "--location", "Singapore"])
    M.main()
    out = capsys.readouterr().out
    assert "104 Jobs / Taiwan" in out  # location is overridden to Taiwan
    assert "area=6001001000,6001002000" in out  # area is untouched
    assert urls
    from urllib.parse import parse_qs, urlsplit

    for u in urls:
        assert parse_qs(urlsplit(u).query)["area"] == ["6001001000,6001002000"]


# ── 3) E-column formula + row build ────────────────────────────────────────
def test_e_formula_for_104():
    assert M.build_e_formula("onezerofour", "abcde", "") == (
        '=HYPERLINK("https://www.104.com.tw/job/abcde","https://www.104.com.tw/job/abcde")'
    )


def test_e_formula_for_104_uses_the_job_url_when_given():
    assert M.build_e_formula("onezerofour", "abcde", "https://www.104.com.tw/job/abcde") == (
        '=HYPERLINK("https://www.104.com.tw/job/abcde","https://www.104.com.tw/job/abcde")'
    )


def test_sheet_row_uses_104_source_label_and_formula():
    row = M._build_sheet_row(_job(), M.ONEZEROFOUR_SHEET_SOURCE_LABEL, "Taiwan", set())
    assert row is not None
    assert len(row) == 11
    assert row[0] == "New"
    assert row[3] == "104 / Minimax"
    assert row[4] == ('=HYPERLINK("https://www.104.com.tw/job/abcde","https://www.104.com.tw/job/abcde")')
    assert row[5] == "Acme Ltd"
    assert row[6] == "Product Manager"
    assert row[8] == "台北市信義區"
    assert row[9] == "Onsite"


def test_sheet_row_visa_column_stays_empty_for_taiwan():
    """Visa detection only runs for Singapore rows."""
    row = M._build_sheet_row(
        _job(jd_text="Applicants must be a Singapore citizen."),
        "104 / Minimax",
        "Taiwan",
        set(),
    )
    assert row[10] == ""


def test_sheet_row_is_skipped_when_already_present():
    assert M._build_sheet_row(_job(), "104 / Minimax", "Taiwan", {("onezerofour", "abcde")}) is None


def test_sheet_row_is_skipped_without_jd():
    assert M._build_sheet_row(_job(jd_text=""), "104 / Minimax", "Taiwan", set()) is None


def test_sheet_row_jd_is_collapsed_to_one_line():
    row = M._build_sheet_row(_job(jd_text="Line one\n\nLine   two\t"), "104 / Minimax", "Taiwan", set())
    assert row[7] == "Line one Line two"


def test_write_order_writes_raw_first_and_formula_last():
    """E column (the only formula) must be written last, as USER_ENTERED."""
    ws = _RecordingWorksheet(row_count=10)
    row = M._build_sheet_row(_job(), "104 / Minimax", "Taiwan", set())
    stats = M._write_rows_to_sheet(ws, 2, [row], skipped_dup=0, skipped_no_jd=0)
    assert stats["written"] == 1
    assert stats["next_row"] == 2
    assert stats["end_row"] == 2
    assert len(ws.updates) == 3
    a_d, f_k, e_only = ws.updates
    assert a_d["range"] == "A2:D2"
    assert a_d["value_input_option"] == "RAW"
    assert a_d["values"] == [["New", "", row[2], "104 / Minimax"]]
    assert f_k["range"] == "F2:K2"
    assert f_k["value_input_option"] == "RAW"
    assert e_only["range"] == "E2:E2"
    assert e_only["value_input_option"] == "USER_ENTERED"
    assert e_only["values"] == [[row[4]]]
    assert e_only["values"][0][0].startswith("=HYPERLINK(")


def test_write_expands_sheet_when_rows_are_insufficient():
    ws = _RecordingWorksheet(row_count=2)
    row = M._build_sheet_row(_job(), "104 / Minimax", "Taiwan", set())
    M._write_rows_to_sheet(ws, 5, [row])
    assert ws.added_rows > 0
    assert ws.row_count >= 5
