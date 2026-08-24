"""Job Tracker initialization planning and batch mutation orchestration."""

from __future__ import annotations

from typing import Any, Iterable

from . import client
from .audit import validate_worksheet_schema, worksheet_is_blank
from .schema import (
    COLUMN_WIDTHS,
    DEFAULT_ROWS,
    DEFAULT_SHEET_TITLES,
    HEADER_HEIGHT_PX,
    HEADER_NOTES,
    HEADER_RGB,
    HEADERS,
    PRIORITY_COLORS,
    SCHEMA_COLUMNS,
    SCHEMA_VERSION,
    STATUS_COLORS,
    VALIDATIONS,
    WHITE_RGB,
    TrackerError,
    canonical_regions,
    expected_tabs,
)


def _grid_range(sheet_id: int, start_col: int, end_col: int, *, start_row: int = 0, end_row: int = DEFAULT_ROWS):
    return {
        "sheetId": int(sheet_id),
        "startRowIndex": start_row,
        "endRowIndex": end_row,
        "startColumnIndex": start_col,
        "endColumnIndex": end_col,
    }


def _schema_requests(sheet_id: int, row_count: int) -> list[dict[str, Any]]:
    end_row = max(int(row_count), DEFAULT_ROWS)
    header_cells = []
    for header, note in zip(HEADERS, HEADER_NOTES, strict=True):
        header_cells.append(
            {
                "userEnteredValue": {"stringValue": header},
                "note": note,
                "userEnteredFormat": {
                    "backgroundColor": HEADER_RGB,
                    "textFormat": {"foregroundColor": WHITE_RGB, "bold": True, "fontFamily": "Arial"},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                    "wrapStrategy": "WRAP",
                },
            }
        )

    requests: list[dict[str, Any]] = [
        {
            "updateSheetProperties": {
                "properties": {"sheetId": int(sheet_id), "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
        {
            "updateCells": {
                "start": {"sheetId": int(sheet_id), "rowIndex": 0, "columnIndex": 0},
                "rows": [{"values": header_cells}],
                "fields": "userEnteredValue,note,userEnteredFormat",
            }
        },
        {
            "repeatCell": {
                "range": _grid_range(sheet_id, 0, SCHEMA_COLUMNS, start_row=1, end_row=end_row),
                "cell": {"userEnteredFormat": {"verticalAlignment": "TOP", "wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.verticalAlignment,userEnteredFormat.wrapStrategy",
            }
        },
        {
            "repeatCell": {
                "range": _grid_range(sheet_id, 6, 7, start_row=1, end_row=end_row),
                "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }
        },
        {
            "repeatCell": {
                "range": _grid_range(sheet_id, 2, 3, start_row=1, end_row=end_row),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        },
    ]

    for col, values in VALIDATIONS.items():
        requests.append(
            {
                "setDataValidation": {
                    "range": _grid_range(sheet_id, col, col + 1, start_row=1, end_row=end_row),
                    "rule": {
                        "condition": {
                            "type": "ONE_OF_LIST",
                            "values": [{"userEnteredValue": value} for value in values],
                        },
                        "strict": True,
                        "showCustomUi": True,
                    },
                }
            }
        )

    for value, color in STATUS_COLORS.items():
        requests.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [_grid_range(sheet_id, 0, 1, start_row=1, end_row=end_row)],
                        "booleanRule": {
                            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": value}]},
                            "format": {"backgroundColor": color},
                        },
                    },
                    "index": 0,
                }
            }
        )

    for value, color in PRIORITY_COLORS.items():
        requests.append(
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [_grid_range(sheet_id, 1, 2, start_row=1, end_row=end_row)],
                        "booleanRule": {
                            "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": value}]},
                            "format": {"backgroundColor": color},
                        },
                    },
                    "index": 0,
                }
            }
        )

    for col, width in enumerate(COLUMN_WIDTHS):
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": int(sheet_id),
                        "dimension": "COLUMNS",
                        "startIndex": col,
                        "endIndex": col + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    requests.append(
        {
            "updateDimensionProperties": {
                "range": {"sheetId": int(sheet_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
                "properties": {"pixelSize": HEADER_HEIGHT_PX},
                "fields": "pixelSize",
            }
        }
    )
    return requests


def _grid_resize_request(sheet_id: int, row_count: int, col_count: int) -> dict[str, Any]:
    return {
        "updateSheetProperties": {
            "properties": {
                "sheetId": int(sheet_id),
                "gridProperties": {
                    "rowCount": max(int(row_count), DEFAULT_ROWS),
                    "columnCount": max(int(col_count), SCHEMA_COLUMNS),
                },
            },
            "fields": "gridProperties.rowCount,gridProperties.columnCount",
        }
    }


def _apply_schema(sh, ws) -> None:
    requests = [
        _grid_resize_request(ws.id, ws.row_count, ws.col_count),
        *_schema_requests(ws.id, max(int(ws.row_count), DEFAULT_ROWS)),
    ]
    sh.batch_update({"requests": requests})


def _find_blank_default_sheets(sh, protected_titles: set[str]) -> list[Any]:
    out = []
    for ws in sh.worksheets():
        if ws.title in protected_titles:
            continue
        if ws.title.casefold() not in DEFAULT_SHEET_TITLES:
            continue
        if worksheet_is_blank(ws):
            out.append(ws)
    return out


def plan_initialize(sh, regions: Iterable[str] | None = None) -> dict[str, Any]:
    region_list = canonical_regions(regions)
    worksheets = {ws.title: ws for ws in sh.worksheets()}
    create: list[str] = []
    configure_blank: list[str] = []
    already_compatible: list[str] = []
    incompatible: list[dict[str, Any]] = []

    for title in expected_tabs(region_list):
        ws = worksheets.get(title)
        if ws is None:
            create.append(title)
            continue
        if worksheet_is_blank(ws):
            configure_blank.append(title)
            continue
        check = validate_worksheet_schema(ws)
        if check["ok"]:
            already_compatible.append(title)
        else:
            incompatible.append(check)

    protected = set(expected_tabs(region_list))
    blank_defaults = [ws.title for ws in _find_blank_default_sheets(sh, protected)]
    return {
        "schema_version": SCHEMA_VERSION,
        "regions": region_list,
        "create": create,
        "configure_blank": configure_blank,
        "already_compatible": already_compatible,
        "incompatible": incompatible,
        "remove_blank_defaults": blank_defaults,
    }


def _allocate_sheet_ids(worksheets: dict[str, Any], titles: list[str]) -> dict[str, int]:
    used = {int(ws.id) for ws in worksheets.values()}
    out: dict[str, int] = {}
    candidate = 1
    for title in titles:
        while candidate in used:
            candidate += 1
        if candidate > 2_147_483_647:
            raise TrackerError("SHEET_ID_ALLOCATION_FAILED", "no available Google Sheet tab ID")
        out[title] = candidate
        used.add(candidate)
        candidate += 1
    return out


def _build_initialization_requests(sh, plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    worksheets = {ws.title: ws for ws in sh.worksheets()}
    new_ids = _allocate_sheet_ids(worksheets, list(plan["create"]))
    requests: list[dict[str, Any]] = []

    for title in plan["create"]:
        sheet_id = new_ids[title]
        requests.append(
            {
                "addSheet": {
                    "properties": {
                        "sheetId": sheet_id,
                        "title": title,
                        "gridProperties": {"rowCount": DEFAULT_ROWS, "columnCount": SCHEMA_COLUMNS},
                    }
                }
            }
        )
        requests.extend(_schema_requests(sheet_id, DEFAULT_ROWS))

    for title in plan["configure_blank"]:
        ws = worksheets[title]
        requests.append(_grid_resize_request(ws.id, ws.row_count, ws.col_count))
        requests.extend(_schema_requests(ws.id, max(int(ws.row_count), DEFAULT_ROWS)))

    for title in plan["remove_blank_defaults"]:
        ws = worksheets.get(title)
        if ws is not None:
            requests.append({"deleteSheet": {"sheetId": int(ws.id)}})

    return requests, new_ids


def initialize_job_tracker(
    sheet_id: str,
    sa_key_path: str,
    regions: Iterable[str] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    sh = client._open_spreadsheet(sa_key_path, sheet_id, write=not dry_run)
    plan = plan_initialize(sh, regions)
    if plan["incompatible"]:
        return {
            "ok": False,
            "dry_run": dry_run,
            "error_code": "SCHEMA_MISMATCH",
            "message": "one or more target region sheets already contain incompatible data; no changes made",
            **plan,
        }
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "message": "initialization preview only; no Sheet writes performed",
            **plan,
        }

    requests, _new_ids = _build_initialization_requests(sh, plan)
    if requests:
        sh.batch_update({"requests": requests})

    created = list(plan["create"])
    configured = [*plan["create"], *plan["configure_blank"]]
    removed_blank_defaults = list(plan["remove_blank_defaults"])
    return {
        "ok": True,
        "dry_run": False,
        "schema_version": SCHEMA_VERSION,
        "regions": plan["regions"],
        "created": created,
        "configured": configured,
        "already_compatible": plan["already_compatible"],
        "removed_blank_defaults": removed_blank_defaults,
        "message": "job tracker initialized atomically",
    }
