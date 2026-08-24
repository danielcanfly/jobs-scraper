from __future__ import annotations

import job_tracker as JT
from jobs_scraper.mcp_services import sheet_config
from jobs_scraper.tracker import audit as tracker_audit
from jobs_scraper.tracker import client as tracker_client


class RecordingWorksheet:
    def __init__(self, rows: list[list[str]], *, title: str = "SG-Raw", row_count: int = 1000):
        self.title = title
        self._rows = rows
        self.row_count = row_count
        self.id = 7
        self.calls: list[str] = []

    def get(self, range_name: str):
        self.calls.append(range_name)
        if range_name == "A1:AA1":
            return [list(self._rows[0])] if self._rows else []
        if range_name == "A2:AA":
            return [list(row) for row in self._rows[1:]]
        if range_name.startswith("A2:AA"):
            return [list(row) for row in self._rows[1:]]
        if range_name == "A2:K":
            return [list(row[:11]) for row in self._rows[1:]]
        raise AssertionError(f"unexpected range: {range_name}")

    def get_all_values(self):
        raise AssertionError("broad get_all_values must not be called")

    def row_values(self, _row: int):
        raise AssertionError("broad row_values must not be called")


def test_legacy_rows_use_bounded_a_to_k_range():
    rows = [
        ["h"] * 27,
        list(range(27)),
    ]
    ws = RecordingWorksheet(rows)
    observed = sheet_config.read_legacy_rows_from_worksheet(ws)
    assert ws.calls == ["A2:K"]
    assert observed == [list(range(11))]


def test_tracker_schema_validation_uses_bounded_header_range():
    ws = RecordingWorksheet([list(JT.HEADERS)])
    result = tracker_audit.validate_worksheet_schema(ws)
    assert result["ok"] is True
    assert ws.calls == ["A1:AA1"]


def test_tracker_region_rows_use_bounded_a_to_aa_range(monkeypatch):
    rows = [list(JT.HEADERS), list(range(27))]
    ws = RecordingWorksheet(rows)
    monkeypatch.setattr(tracker_client, "open_region_raw", lambda *_args, **_kwargs: (object(), ws))
    observed = tracker_client.read_region_rows("sheet", "/tmp/key.json", "SG")
    assert ws.calls == ["A2:AA"]
    assert observed == [list(range(27))]


def test_blank_detection_uses_bounded_header_and_data_probe():
    ws = RecordingWorksheet([[""] * 27, [""] * 27, ["value", *[""] * 26]], row_count=25)
    assert tracker_audit.worksheet_is_blank(ws) is False
    assert ws.calls == ["A1:AA1", "A2:AA25"]


def test_row_shape_remains_compatible_with_existing_analysis_columns():
    rows = [
        list(JT.HEADERS),
        ["New", "", "2026-08-24", "LinkedIn / jobs-scraper", "https://example.com/1", "Acme", "PM", "", "Singapore", "Hybrid", "", *[""] * 16],
    ]
    ws = RecordingWorksheet(rows)
    tracker_rows = tracker_audit.read_tracker_rows(ws)
    assert len(tracker_rows[0]) == 27
    legacy_rows = sheet_config.read_legacy_rows_from_worksheet(ws)
    assert len(legacy_rows[0]) == 11
