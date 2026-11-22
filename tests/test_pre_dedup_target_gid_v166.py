"""v1.6.6: the pre-detail dedup reads the tab the run is about to write to.

Before v1.6.6 the pre-detail dedup resolved its worksheet from a
label→gid table in which ``"LinkedIn / Minimax"`` always pointed at
SG-Raw. A China run therefore compared its jobs against Singapore's tab,
kept every China job, and paid for a full JD fetch round that the Sheet
write was going to discard anyway. Only the cross-run JSON cache hid the
cost; a cache miss meant a whole extra JD crawl for jobs that were never
new.

v1.6.6 threads the target gid (explicit ``--gid``, else the ``#gid=``
inside ``--to-sheet``) into the loader, into the subprocess worker and
into main(). With no target given, the old label→gid mapping still
applies, so the SG and TW flows behave exactly as before.

No test touches the real Google Sheet: gspread is replaced by a fake
client and the worksheet by a recorder object.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import gspread  # noqa: E402
from google.oauth2 import service_account  # noqa: E402

import sg_product_jobs as M  # noqa: E402

CHINA_RAW_GID = 488353479


class _RecordingWorksheet:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else []
        self.requested_gid = None

    def get_all_values(self):
        return self.rows


class _FakeSpreadsheet:
    def __init__(self, ws):
        self.ws = ws

    def get_worksheet_by_id(self, gid):
        self.ws.requested_gid = gid
        return self.ws


class _FakeClient:
    def __init__(self, ws):
        self.sh = _FakeSpreadsheet(ws)

    def open_by_key(self, key):
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


def _job(job_id, source="linkedin"):
    return {
        "job_id": job_id,
        "title": "Product Manager",
        "company": "Acme Ltd",
        "location": "Shanghai, Shanghai, China",
        "source": source,
        "url": f"https://www.linkedin.com/jobs/view/{job_id}",
    }


# ── loader: an explicit gid wins over the label table ───────────────────────
def test_explicit_gid_reads_that_worksheet(monkeypatch):
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("LinkedIn / Minimax", gid=CHINA_RAW_GID)
    assert ws.requested_gid == CHINA_RAW_GID


def test_explicit_gid_beats_the_sg_raw_default(monkeypatch):
    """The whole bug: "LinkedIn / Minimax" used to force SG-Raw."""
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("LinkedIn / Minimax", gid=CHINA_RAW_GID)
    assert ws.requested_gid != M.SG_RAW_GID


def test_label_mapping_still_applies_without_a_gid(monkeypatch):
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("LinkedIn / Minimax")
    assert ws.requested_gid == M.SG_RAW_GID


def test_unknown_label_is_still_rejected_without_a_gid(monkeypatch):
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    try:
        M._load_sheet_keys_for_source("Bogus / Minimax")
    except ValueError as e:
        assert "未知 sheet_source_label" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_explicit_gid_does_not_need_a_known_label(monkeypatch):
    """An explicit target is authoritative; a label typo cannot silently
    redirect the read to another tab."""
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("Bogus / Minimax", gid=CHINA_RAW_GID)
    assert ws.requested_gid == CHINA_RAW_GID


def test_gid_may_be_a_string(monkeypatch):
    """--to-sheet URLs carry the gid as text; int() conversion happens later."""
    ws = _RecordingWorksheet(rows=[])
    _install_fake_gspread(monkeypatch, ws)
    M._load_sheet_keys_for_source("LinkedIn / Minimax", gid=str(CHINA_RAW_GID))
    assert ws.requested_gid == CHINA_RAW_GID


# ── pre-dedup: the target gid reaches the loader ────────────────────────────
def test_pre_dedup_forwards_the_target_gid(monkeypatch):
    seen: list[dict] = []

    def fake_loader(label, sa_key_path="", sheet_id="", gid=None):
        seen.append({"label": label, "gid": gid, "sheet_id": sheet_id})
        return {("linkedin", "bbb22")}, 10

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", fake_loader)
    out = M.pre_dedup_jobs_against_sheet(
        [_job("aaa11"), _job("bbb22")], "LinkedIn / Minimax", timeout_s=0, gid=CHINA_RAW_GID
    )
    assert seen == [{"label": "LinkedIn / Minimax", "gid": CHINA_RAW_GID, "sheet_id": ""}]
    assert [j["job_id"] for j in out] == ["aaa11"]


def test_pre_dedup_without_a_target_keeps_the_old_call_shape(monkeypatch):
    """No target → no gid kwarg at all, so existing loaders stay compatible."""
    seen: list[dict] = []

    def fake_loader(label, sa_key_path="", sheet_id="", **kwargs):
        seen.append({"label": label, "kwargs": kwargs})
        return set(), 10

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", fake_loader)
    M.pre_dedup_jobs_against_sheet([_job("aaa11")], "LinkedIn / Minimax", timeout_s=0)
    assert seen == [{"label": "LinkedIn / Minimax", "kwargs": {}}]


def test_pre_dedup_reads_the_target_tab_end_to_end(monkeypatch):
    """The job already on China-Raw is dropped before any JD fetch."""
    ws = _RecordingWorksheet(
        rows=[
            # row 1 is the header; _load_sheet_keys skips it
            ["New", "", "Date", "Source", "URL"],
            [
                "New",
                "",
                "2026-11-22",
                "LinkedIn / Minimax",
                '=HYPERLINK("https://www.linkedin.com/jobs/jobPosting/22222","22222")',
            ],
            ["", "", "", "", ""],
        ]
    )
    _install_fake_gspread(monkeypatch, ws)
    out = M.pre_dedup_jobs_against_sheet(
        [_job("11111"), _job("22222")],
        "LinkedIn / Minimax",
        timeout_s=0,
        gid=CHINA_RAW_GID,
    )
    assert ws.requested_gid == CHINA_RAW_GID
    assert [j["job_id"] for j in out] == ["11111"]


# ── subprocess worker: the gid is embedded as a Python literal ─────────────
def test_worker_code_embeds_the_gid():
    code = M._build_pre_dedup_worker_code("LinkedIn / Minimax", "key.json", "/tmp/out.json", gid=CHINA_RAW_GID)
    assert f"gid={CHINA_RAW_GID}" in code
    ast.parse(code)


def test_worker_code_omits_the_gid_when_unset():
    code = M._build_pre_dedup_worker_code("LinkedIn / Minimax", "key.json", "/tmp/out.json")
    assert "gid=" not in code
    ast.parse(code)


def test_worker_code_embeds_a_string_gid_as_a_literal():
    code = M._build_pre_dedup_worker_code("LinkedIn / Minimax", "key.json", "/tmp/out.json", gid="12345")
    assert "gid='12345'" in code
    ast.parse(code)


# ── main(): the target gid is resolved and handed to pre-dedup ──────────────
class _Args:
    def __init__(self, gid=None, to_sheet=None):
        self.gid = gid
        self.to_sheet = to_sheet


def test_target_resolution_prefers_the_explicit_flag():
    gid, sheet_id = M._resolve_pre_dedup_target(
        _Args(gid=111, to_sheet="https://docs.google.com/spreadsheets/d/abc/edit#gid=222")
    )
    assert gid == 111


def test_target_resolution_falls_back_to_the_url():
    gid, _ = M._resolve_pre_dedup_target(
        _Args(gid=None, to_sheet="https://docs.google.com/spreadsheets/d/abc/edit#gid=222")
    )
    assert gid == "222"


def test_target_resolution_without_a_target():
    gid, sheet_id = M._resolve_pre_dedup_target(_Args(gid=None, to_sheet=None))
    assert gid is None
    assert sheet_id == ""


def test_target_resolution_reads_the_sheet_id_from_the_url():
    _, sheet_id = M._resolve_pre_dedup_target(
        _Args(
            gid=None,
            to_sheet="https://docs.google.com/spreadsheets/d/FAKE-SHEET-ID/edit#gid=1",
        )
    )
    assert sheet_id == "FAKE-SHEET-ID"


def test_main_hands_the_resolved_gid_to_pre_dedup(monkeypatch, tmp_path):
    captured: dict = {}

    def fake_pre_dedup(jobs, sheet_source_label, **kwargs):
        captured.update(kwargs)
        captured["label"] = sheet_source_label
        return jobs

    monkeypatch.setattr(M, "crawl_list", lambda *a, **k: [_job("aaa11")])
    monkeypatch.setattr(M, "pre_dedup_jobs_against_sheet", fake_pre_dedup)
    monkeypatch.setattr(
        M,
        "enrich_with_jd",
        lambda jobs, **kwargs: (jobs, {"total": 1, "skipped": 0, "cached": 0, "fetched": 0, "failed": 0}),
    )
    monkeypatch.setattr(M, "load_jd_cache_from_jsons", lambda **kw: {})
    monkeypatch.setattr(M, "load_seen_ids", lambda *a, **k: set())
    monkeypatch.setattr(
        M,
        "push_to_sheet",
        lambda *a, **k: {"written": 0, "skipped_dup": 0, "dry_run": True},
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sg_product_jobs.py",
            "7d",
            "--with-jd",
            "--to-sheet",
            "https://docs.google.com/spreadsheets/d/fake-sheet-id/edit#gid=488353479",
        ],
    )
    M.main()
    assert captured["gid"] == "488353479"
    assert captured["label"] == "LinkedIn / Minimax"
