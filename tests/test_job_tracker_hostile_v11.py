from __future__ import annotations

import inspect

import pytest

import job_tracker as JT
import server_v1_1 as S


class FakeWorksheet:
    def __init__(
        self,
        title: str,
        rows: list[list[str]] | None = None,
        *,
        wid: int = 1,
        row_count: int = 1000,
        col_count: int = 27,
    ):
        self.title = title
        self._rows = rows or []
        self.id = wid
        self.row_count = row_count
        self.col_count = col_count

    def row_values(self, row: int):
        assert row == 1
        return list(self._rows[0]) if self._rows else []

    def get(self, range_name: str):
        if range_name.startswith("A1:"):
            return [list(self._rows[0])] if self._rows else []
        if range_name.startswith("A2:"):
            return [list(r) for r in self._rows[1:]]
        raise AssertionError(f"unexpected range: {range_name}")

    def get_all_values(self):
        return [list(r) for r in self._rows]


class FakeSpreadsheet:
    def __init__(self, worksheets: list[FakeWorksheet], *, fail_batch: bool = False):
        self._worksheets = list(worksheets)
        self.fail_batch = fail_batch
        self.batch_calls: list[dict] = []

    def worksheets(self):
        return list(self._worksheets)

    def worksheet(self, title: str):
        for ws in self._worksheets:
            if ws.title == title:
                return ws
        raise RuntimeError("not found")

    def batch_update(self, body: dict):
        self.batch_calls.append(body)
        if self.fail_batch:
            raise RuntimeError("synthetic batch failure")
        return {"replies": [{} for _ in body.get("requests", [])]}


def _good_rows():
    return [list(JT.HEADERS)]


def _summary(*, written: int = 0):
    return {
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
        "error_code": None,
        "stdout_tail": ('JOBS_SCRAPER_SUMMARY={"written":%d,"skipped_dup":0,"skipped_no_jd":0}\n' % written),
        "stderr_tail": "",
    }


def test_initialize_default_six_tabs_is_one_atomic_batch(monkeypatch):
    sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [], wid=91, col_count=26)])
    opened: list[bool] = []

    def fake_open(_key, _sid, *, write):
        opened.append(write)
        return sh

    monkeypatch.setattr(JT, "_open_spreadsheet", fake_open)
    result = JT.initialize_job_tracker("user-sheet", "/tmp/key.json", dry_run=False)

    assert opened == [True]
    assert result["ok"] is True
    assert result["created"] == JT.expected_tabs()
    assert result["configured"] == JT.expected_tabs()
    assert result["removed_blank_defaults"] == ["Sheet1"]
    assert len(sh.batch_calls) == 1

    requests = sh.batch_calls[0]["requests"]
    adds = [r["addSheet"] for r in requests if "addSheet" in r]
    deletes = [r["deleteSheet"] for r in requests if "deleteSheet" in r]
    assert [r["properties"]["title"] for r in adds] == JT.expected_tabs()
    assert len(deletes) == 1 and deletes[0]["sheetId"] == 91

    new_ids = [int(r["properties"]["sheetId"]) for r in adds]
    assert len(new_ids) == len(set(new_ids)) == 6
    assert 91 not in new_ids
    for add in adds:
        props = add["properties"]
        assert props["gridProperties"] == {"rowCount": 1000, "columnCount": 27}
        sid = props["sheetId"]
        assert any(r.get("updateCells", {}).get("start", {}).get("sheetId") == sid for r in requests)


def test_initialize_existing_blank_resize_and_schema_share_same_batch(monkeypatch):
    sh = FakeSpreadsheet(
        [
            FakeWorksheet("SG-Raw", [], wid=11, row_count=50, col_count=10),
            FakeWorksheet("SG-Selected", _good_rows(), wid=12, row_count=1200, col_count=30),
        ]
    )
    monkeypatch.setattr(JT, "_open_spreadsheet", lambda *_a, **_kw: sh)
    result = JT.initialize_job_tracker("user-sheet", "/tmp/key.json", regions=["SG"], dry_run=False)
    assert result["ok"] is True
    assert result["created"] == []
    assert result["configured"] == ["SG-Raw"]
    assert len(sh.batch_calls) == 1
    requests = sh.batch_calls[0]["requests"]
    resize = next(
        r["updateSheetProperties"]
        for r in requests
        if "updateSheetProperties" in r
        and r["updateSheetProperties"]["properties"]["sheetId"] == 11
        and "rowCount" in r["updateSheetProperties"]["properties"]["gridProperties"]
    )
    assert resize["properties"]["gridProperties"] == {
        "rowCount": JT.DEFAULT_ROWS,
        "columnCount": JT.SCHEMA_COLUMNS,
    }
    assert any(r.get("updateCells", {}).get("start", {}).get("sheetId") == 11 for r in requests)


def test_incompatible_preflight_performs_zero_writes(monkeypatch):
    sh = FakeSpreadsheet(
        [
            FakeWorksheet("SG-Raw", [["wrong", "header"]], wid=11),
            FakeWorksheet("SG-Selected", _good_rows(), wid=12),
        ]
    )
    monkeypatch.setattr(JT, "_open_spreadsheet", lambda *_a, **_kw: sh)
    result = JT.initialize_job_tracker("user-sheet", "/tmp/key.json", regions=["SG"], dry_run=False)
    assert result["ok"] is False
    assert result["error_code"] == "SCHEMA_MISMATCH"
    assert sh.batch_calls == []


def test_initialize_dry_run_is_read_only_and_zero_write(monkeypatch):
    sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [], wid=91, col_count=26)])
    writes: list[bool] = []

    def fake_open(_key, _sid, *, write):
        writes.append(write)
        return sh

    monkeypatch.setattr(JT, "_open_spreadsheet", fake_open)
    result = JT.initialize_job_tracker("user-sheet", "/tmp/key.json", dry_run=True)
    assert result["ok"] is True and result["dry_run"] is True
    assert writes == [False]
    assert sh.batch_calls == []
    assert result["create"] == JT.expected_tabs()


def test_initializer_has_single_failure_boundary(monkeypatch):
    sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [], wid=91, col_count=26)], fail_batch=True)
    monkeypatch.setattr(JT, "_open_spreadsheet", lambda *_a, **_kw: sh)
    with pytest.raises(RuntimeError, match="synthetic batch failure"):
        JT.initialize_job_tracker("user-sheet", "/tmp/key.json", dry_run=False)
    assert len(sh.batch_calls) == 1
    # No sequential add_worksheet/del_worksheet methods exist on this fake: reaching one
    # batch call proves the implementation has a single remote mutation boundary.


def test_config_v11_does_not_require_gid(monkeypatch, tmp_path):
    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHEET_ID", "user-owned-sheet")
    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(key))
    monkeypatch.delenv("SHEET_GID", raising=False)
    assert JT.check_tracker_config() == (str(key), "user-owned-sheet")


def test_sync_public_signature_has_region_but_no_gid():
    params = inspect.signature(S.sync_jobs_to_sheet).parameters
    assert "region" in params
    assert "gid" not in params
    assert "sheet_id" not in params


def test_missing_region_blocks_subprocess(monkeypatch):
    monkeypatch.setattr(S, "_cfg_or_error", lambda: ("/tmp/key.json", "user-sheet"))

    def fail_open(*_a, **_kw):
        raise JT.TrackerError("REGION_NOT_INITIALIZED", "missing SG-Raw")

    monkeypatch.setattr(S.JT, "open_region_raw", fail_open)
    monkeypatch.setattr(S.RT, "run_scraper_subprocess", lambda _args: pytest.fail("subprocess must not run"))
    result = S.sync_jobs_to_sheet(region="SG", source="linkedin", range="7d")
    assert result.ok is False
    assert result.error_code == "REGION_NOT_INITIALIZED"


def test_schema_mismatch_blocks_subprocess(monkeypatch):
    monkeypatch.setattr(S, "_cfg_or_error", lambda: ("/tmp/key.json", "user-sheet"))

    def fail_open(*_a, **_kw):
        raise JT.TrackerError("SCHEMA_MISMATCH", "bad header")

    monkeypatch.setattr(S.JT, "open_region_raw", fail_open)
    monkeypatch.setattr(S.RT, "run_scraper_subprocess", lambda _args: pytest.fail("subprocess must not run"))
    result = S.sync_jobs_to_sheet(region="SG", source="linkedin", range="7d")
    assert result.ok is False
    assert result.error_code == "SCHEMA_MISMATCH"


def test_unsupported_source_region_blocks_before_config_or_subprocess(monkeypatch):
    monkeypatch.setattr(S, "_cfg_or_error", lambda: pytest.fail("config must not be consulted"))
    monkeypatch.setattr(S.RT, "run_scraper_subprocess", lambda _args: pytest.fail("subprocess must not run"))
    result = S.sync_jobs_to_sheet(region="TW", source="jobstreet", range="7d")
    assert result.ok is False
    assert result.error_code == "SOURCE_REGION_UNSUPPORTED"


def test_sync_dry_run_resolves_readonly_and_uses_internal_gid(monkeypatch):
    class WS:
        id = 314
        title = "SG-Raw"

    opens: list[bool] = []
    seen_args: list[list[str]] = []
    monkeypatch.setattr(S, "_cfg_or_error", lambda: ("/tmp/key.json", "user-sheet"))

    def fake_open(_sid, _key, _region, *, write):
        opens.append(write)
        return object(), WS()

    def fake_run(args):
        seen_args.append(list(args))
        return _summary()

    monkeypatch.setattr(S.JT, "open_region_raw", fake_open)
    monkeypatch.setattr(S.RT, "run_scraper_subprocess", fake_run)
    result = S.sync_jobs_to_sheet(region="SG", source="linkedin", range="7d", with_jd=False, dry_run=True)
    assert result.ok is True
    assert opens == [False]
    args = seen_args[0]
    assert args[args.index("--gid") + 1] == "314"
    assert args[args.index("--to-sheet") + 1] == "user-sheet"
    assert args[args.index("--location") + 1] == "Singapore"
    assert "--dry-run-sheet" in args


def test_sync_real_write_resolves_with_write_scope(monkeypatch):
    class WS:
        id = 2718
        title = "China-Raw"

    opens: list[bool] = []
    seen_args: list[list[str]] = []
    monkeypatch.setattr(S, "_cfg_or_error", lambda: ("/tmp/key.json", "user-sheet"))

    def fake_open(_sid, _key, _region, *, write):
        opens.append(write)
        return object(), WS()

    def fake_run(args):
        seen_args.append(list(args))
        return _summary(written=2)

    monkeypatch.setattr(S.JT, "open_region_raw", fake_open)
    monkeypatch.setattr(S.RT, "run_scraper_subprocess", fake_run)
    result = S.sync_jobs_to_sheet(region="China", source="linkedin", range="24h", with_jd=False, dry_run=False)
    assert result.ok is True and result.written == 2
    assert opens == [True]
    args = seen_args[0]
    assert args[args.index("--gid") + 1] == "2718"
    assert args[args.index("--location") + 1] == "Shanghai"
    assert "--dry-run-sheet" not in args
