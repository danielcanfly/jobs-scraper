from __future__ import annotations

import importlib

import job_tracker as JT
from jobs_scraper.tracker import audit, client, initializer, schema


EXPECTED_PUBLIC_NAMES = {
    "Any",
    "COLUMN_WIDTHS",
    "DEFAULT_REGIONS",
    "DEFAULT_ROWS",
    "DEFAULT_SHEET_TITLES",
    "HEADERS",
    "HEADER_HEIGHT_PX",
    "HEADER_NOTES",
    "HEADER_RGB",
    "Iterable",
    "PRIORITY_COLORS",
    "Path",
    "REGION_ALIASES",
    "RP",
    "SCHEMA_COLUMNS",
    "SCHEMA_VERSION",
    "SCOPES_READONLY",
    "SCOPES_WRITE",
    "STATUS_COLORS",
    "TrackerError",
    "VALIDATIONS",
    "WHITE_RGB",
    "annotations",
    "canonical_region",
    "canonical_regions",
    "check_tracker_config",
    "expected_tabs",
    "initialize_job_tracker",
    "open_region_raw",
    "os",
    "plan_initialize",
    "raw_tab",
    "re",
    "read_region_rows",
    "resolve_region_worksheet",
    "selected_tab",
    "validate_worksheet_schema",
    "worksheet_is_blank",
}


class FakeWorksheet:
    def __init__(self, title: str, rows: list[list[str]] | None = None, *, wid: int = 1):
        self.title = title
        self._rows = rows or []
        self.id = wid
        self.row_count = 1000
        self.col_count = 27

    def row_values(self, row: int):
        assert row == 1
        return list(self._rows[0]) if self._rows else []

    def get_all_values(self):
        return [list(row) for row in self._rows]


class FakeSpreadsheet:
    def __init__(self, worksheets: list[FakeWorksheet]):
        self._worksheets = list(worksheets)
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
        return {}


def test_root_public_names_remain_available():
    public = {name for name in dir(JT) if not name.startswith("_")}
    assert EXPECTED_PUBLIC_NAMES <= public


def test_schema_owner_preserves_header_identity_and_region_aliases():
    assert JT.HEADERS is schema.HEADERS
    assert JT.HEADER_NOTES is schema.HEADER_NOTES
    assert JT.VALIDATIONS is schema.VALIDATIONS
    assert JT.COLUMN_WIDTHS is schema.COLUMN_WIDTHS
    assert len(schema.HEADERS) == 27
    assert schema.HEADERS == JT.HEADERS
    assert JT.DEFAULT_REGIONS is schema.DEFAULT_REGIONS
    assert JT.REGION_ALIASES is schema.REGION_ALIASES


def test_root_initializer_uses_initializer_owner_and_preserves_open_monkeypatch(monkeypatch):
    sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [], wid=91)])
    opens = []

    def fake_open(sa_key_path, sheet_id, *, write):
        opens.append((sa_key_path, sheet_id, write))
        return sh

    monkeypatch.setattr(JT, "_open_spreadsheet", fake_open)
    result = JT.initialize_job_tracker("user-sheet", "/tmp/key.json", regions=["SG"], dry_run=False)

    assert opens == [("/tmp/key.json", "user-sheet", True)]
    assert result["ok"] is True
    assert result["created"] == ["SG-Raw", "SG-Selected"]
    assert len(sh.batch_calls) == 1
    assert client._open_spreadsheet is fake_open


def test_root_audit_and_client_wrappers_delegate_to_split_modules(monkeypatch):
    ws = FakeWorksheet("SG-Raw", [list(schema.HEADERS)], wid=314)
    sh = FakeSpreadsheet([ws])

    assert JT.validate_worksheet_schema(ws) == audit.validate_worksheet_schema(ws)
    assert JT.resolve_region_worksheet(sh, "SG") is ws
    assert JT.read_region_rows.__name__ == "read_region_rows"
    assert JT.open_region_raw.__name__ == "open_region_raw"


def test_initializer_owner_exposes_same_batch_request_contract():
    requests = initializer._schema_requests(123, 1000)
    kinds = [next(iter(request)) for request in requests]
    assert kinds.count("setDataValidation") == len(schema.VALIDATIONS)
    assert kinds.count("addConditionalFormatRule") == len(schema.STATUS_COLORS) + len(schema.PRIORITY_COLORS)
    assert kinds.count("updateDimensionProperties") == len(schema.COLUMN_WIDTHS) + 1
    assert requests[0]["updateSheetProperties"]["properties"]["gridProperties"]["frozenRowCount"] == 1


def test_split_modules_are_packaged_importable():
    assert importlib.import_module("jobs_scraper.tracker.schema") is schema
    assert importlib.import_module("jobs_scraper.tracker.client") is client
    assert importlib.import_module("jobs_scraper.tracker.initializer") is initializer
    assert importlib.import_module("jobs_scraper.tracker.audit") is audit
