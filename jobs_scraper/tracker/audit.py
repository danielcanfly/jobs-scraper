"""Read-only Job Tracker schema validation helpers."""
from __future__ import annotations

from typing import Any

from .schema import HEADERS, SCHEMA_COLUMNS, SCHEMA_VERSION


def _header_values(ws) -> list[str]:
    values = ws.row_values(1)
    return [str(v) for v in values[:SCHEMA_COLUMNS]]


def worksheet_is_blank(ws) -> bool:
    if any(str(cell).strip() for cell in ws.row_values(1)):
        return False
    return not any(str(cell).strip() for row in ws.get_all_values() for cell in row)


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
