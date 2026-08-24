"""Read-only Job Tracker schema validation helpers."""
from __future__ import annotations

from typing import Any

from .schema import DEFAULT_ROWS, HEADERS, SCHEMA_COLUMNS, SCHEMA_VERSION

TRACKER_HEADER_RANGE = "A1:AA1"
TRACKER_DATA_RANGE = "A2:AA"


def _col_name(index: int) -> str:
    out = ""
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _worksheet_get(ws, range_name: str) -> list[list[str]]:
    if hasattr(ws, "get"):
        rows = ws.get(range_name)
    else:
        rows = ws.get_values(range_name)
    return [list(row) for row in rows]


def read_header_values(ws, *, columns: int = SCHEMA_COLUMNS) -> list[str]:
    end_col = _col_name(columns)
    values = _worksheet_get(ws, f"A1:{end_col}1")
    first_row = values[0] if values else []
    return [str(value) for value in first_row[:columns]]


def read_tracker_rows(ws) -> list[list[str]]:
    return _worksheet_get(ws, TRACKER_DATA_RANGE)


def read_blank_probe_rows(ws) -> list[list[str]]:
    row_count = min(max(int(getattr(ws, "row_count", DEFAULT_ROWS) or DEFAULT_ROWS), 1), DEFAULT_ROWS)
    end_col = _col_name(SCHEMA_COLUMNS)
    return _worksheet_get(ws, f"A2:{end_col}{row_count}")


def _header_values(ws) -> list[str]:
    return read_header_values(ws)


def worksheet_is_blank(ws) -> bool:
    if any(str(cell).strip() for cell in read_header_values(ws)):
        return False
    return not any(str(cell).strip() for row in read_blank_probe_rows(ws) for cell in row)


def validate_worksheet_schema(ws) -> dict[str, Any]:
    observed = _header_values(ws)
    expected = list(HEADERS)
    if observed == expected:
        return {"ok": True, "sheet": ws.title, "schema_version": SCHEMA_VERSION}
    first_mismatch = None
    for idx, expected_value in enumerate(expected):
        observed_value = observed[idx] if idx < len(observed) else ""
        if observed_value != expected_value:
            first_mismatch = {
                "column_index": idx + 1,
                "expected": expected_value,
                "observed": observed_value,
            }
            break
    return {
        "ok": False,
        "sheet": ws.title,
        "schema_version": SCHEMA_VERSION,
        "error_code": "SCHEMA_MISMATCH",
        "first_mismatch": first_mismatch,
        "observed_header_count": len(observed),
        "expected_header_count": len(expected),
    }
