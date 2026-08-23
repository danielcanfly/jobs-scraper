"""Portable Google Sheet Job Tracker schema and region-pair bootstrap for jobs-scraper v1.1.0."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

SCOPES_READONLY = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_WRITE = ["https://www.googleapis.com/auth/spreadsheets"]

SCHEMA_VERSION = "job-tracker-v1"
DEFAULT_ROWS = 1000
SCHEMA_COLUMNS = 27

HEADERS = (
    "Status｜狀態",
    "Priority｜優先級",
    "加入日期｜Added At",
    "Source｜來源",
    "Job URL｜職缺連結",
    "Company｜公司",
    "Job Title｜職稱",
    "JD | 描述",
    "Location｜地點",
    "Work Mode｜工作型態",
    "Visa / Constraint｜簽證限制",
    "Domain｜產品產業",
    "CV Version｜履歷版本",
    "Total /100",
    "Verdict｜評語",
    "Decision｜決策",
    "Application Strategy｜投遞策略",
    "Role Fit /25",
    "CV Proof /15",
    "AI / Tech Leverage /15",
    "Seniority Scope /10",
    "Company Quality /10",
    "Domain Advantage /10",
    "Application ROI /10",
    "Practical Constraints /5",
    "Positioning / Selling Points｜定位賣點",
    "Risks / Next Action｜風險下一步",
)

HEADER_NOTES = (
    "工作流狀態：New / Scored / Applied / Interviewing / Pending。",
    "投遞優先級：P0 / P1 / P2 / Low。用來排序實際處理順序，不只看總分。",
    "職缺加入或最近完成評分的日期。",
    "例如 LinkedIn、Jora、JobStreet、referral、company site。",
    "原始職缺 URL 或 jobs-scraper 產生的安全 HYPERLINK。",
    "公司名稱。",
    "職缺標題。",
    "完整職缺描述（JD）。",
    "職缺地點，例如 Singapore、Taipei、Shanghai、Remote。",
    "Remote / Hybrid / Onsite / Unknown。",
    "Work authorization、sponsorship、timezone、language、salary 等現實限制。",
    "AI SaaS、B2B SaaS、Marketplace、Travel-tech、Hospitality、Growth、Ads、Data Product 等。",
    "這份職缺應使用的履歷包裝版本。",
    "總分，滿分 100。",
    "整體投遞評語。",
    "Apply / Maybe / Skip。",
    "Do not apply / Quick apply only / Apply with tailored CV / Tailored CV + recruiter message / Tailored CV + hiring manager outreach。",
    "職務方向匹配度，滿分 25。",
    "履歷證據匹配度，滿分 15。",
    "AI 與技術槓桿，滿分 15。",
    "職級與職責範圍，滿分 10。",
    "公司品質與時機，滿分 10。",
    "Market / Domain Advantage，滿分 10。",
    "投遞報酬率，滿分 10。",
    "現實限制，滿分 5。",
    "一句定位角度 + 最該主打的 3 個候選人賣點。可直接用於 CV summary 或 recruiter message。",
    "主要弱點、公司/簽證/JD 風險、面試補強、下一步行動，例如找 HM、改 CV、補公司研究。",
)

VALIDATIONS: dict[int, tuple[str, ...]] = {
    0: ("New", "Scored", "Applied", "Interviewing", "Pending"),
    1: ("P0", "P1", "P2", "Low"),
    9: ("Remote", "Hybrid", "Onsite", "Unknown"),
    12: (
        "AI PM", "Growth PM", "Travel / Hospitality", "Founder / 0→1",
        "Strategy Ops", "Platform / Workflow", "General PM", "Web3 / Fintech",
    ),
    14: ("強烈值得投", "值得投", "邊緣", "不太建議", "不值得投"),
    15: ("Apply", "Maybe", "Skip"),
    16: (
        "Do not apply", "Quick apply only", "Apply with tailored CV",
        "Tailored CV + recruiter message", "Tailored CV + hiring manager outreach",
    ),
}

REGION_ALIASES = {
    "sg": "SG", "singapore": "SG",
    "tw": "TW", "taiwan": "TW", "台灣": "TW", "台湾": "TW",
    "cn": "China", "china": "China", "mainland china": "China",
    "中國": "China", "中国": "China", "shanghai": "China",
}

DEFAULT_REGIONS = ("SG", "TW", "China")
DEFAULT_SHEET_TITLES = {"sheet1", "工作表1", "工作表 1"}

# Pixel widths derived from the exported reference Job List_New workbook:
# A:B=15.13, C:E=17.0, F:H=23.88, I:M=18.88, N:Q=18.25,
# R:Y=14.88, Z:AA=40.13 Excel width units.
# Conversion follows the effective exported Google-Sheets-to-XLSX dimensions.
COLUMN_WIDTHS = (
    111, 111,                       # A:B
    124, 124, 124,                  # C:E
    172, 172, 172,                  # F:H
    137, 137, 137, 137, 137,        # I:M
    133, 133, 133, 133,             # N:Q
    109, 109, 109, 109, 109, 109, 109, 109,  # R:Y
    286, 286,                       # Z:AA
)
HEADER_HEIGHT_PX = 52  # Reference export: 39 pt ~= 52 px at 96 dpi.

HEADER_RGB = {"red": 0.101960786, "green": 0.21568628, "blue": 0.33333334}
WHITE_RGB = {"red": 1.0, "green": 1.0, "blue": 1.0}

STATUS_COLORS = {
    "Pending": {"red": 1.0, "green": 1.0, "blue": 1.0},
    "Interviewing": {"red": 0.96862745, "green": 0.92941177, "blue": 0.64705884},
    "Applied": {"red": 0.95686275, "green": 0.7764706, "blue": 0.7764706},
    "Scored": {"red": 0.7764706, "green": 0.8980392, "blue": 0.9490196},
    "New": {"red": 0.81960785, "green": 0.9490196, "blue": 0.7764706},
}
PRIORITY_COLORS = {
    "P0": {"red": 0.9490196, "green": 0.6, "blue": 0.6},
    "P1": {"red": 0.96862745, "green": 0.7764706, "blue": 0.49803922},
}


class TrackerError(RuntimeError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def canonical_region(region: str) -> str:
    raw = (region or "").strip()
    if not raw:
        raise TrackerError("INVALID_REGION", "region must be non-empty")
    alias = REGION_ALIASES.get(raw.casefold())
    if alias:
        return alias
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,31}", raw):
        raise TrackerError(
            "INVALID_REGION",
            "region may contain only letters, digits, spaces, '_' or '-' and must be <= 32 chars",
        )
    return raw


def canonical_regions(regions: Iterable[str] | None) -> list[str]:
    values = list(regions or DEFAULT_REGIONS)
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        region = canonical_region(value)
        key = region.casefold()
        if key not in seen:
            seen.add(key)
            out.append(region)
    if not out:
        raise TrackerError("INVALID_REGION", "at least one region is required")
    return out


def raw_tab(region: str) -> str:
    return f"{canonical_region(region)}-Raw"


def selected_tab(region: str) -> str:
    return f"{canonical_region(region)}-Selected"


def expected_tabs(regions: Iterable[str] | None = None) -> list[str]:
    tabs: list[str] = []
    for region in canonical_regions(regions):
        tabs.extend([raw_tab(region), selected_tab(region)])
    return tabs


def _resolve_sa_key_path(repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).parent.resolve()
    value = os.getenv("GSPREAD_SA_KEY_PATH", "").strip() or ".secrets/gsheet-sa.json"
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return str(path)


def check_tracker_config(repo_root: Path | None = None) -> tuple[str, str] | dict[str, Any]:
    sid = os.getenv("SHEET_ID", "").strip()
    placeholder_ids = {"your_google_sheet_id_here", "your-sheet-id", "replace_me"}
    if not sid or sid.lower() in placeholder_ids:
        return {
            "ok": False,
            "error_code": "CONFIG_MISSING",
            "message": "missing env: SHEET_ID — set the user's own spreadsheet ID. v1.1.0 resolves worksheet IDs by region.",
        }
    sa = _resolve_sa_key_path(repo_root)
    if not Path(sa).exists():
        return {
            "ok": False,
            "error_code": "CREDENTIAL_FILE_MISSING",
            "message": f"credential file not found: {sa}",
        }
    return sa, sid


def _open_spreadsheet(sa_key_path: str, sheet_id: str, *, write: bool):
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = SCOPES_WRITE if write else SCOPES_READONLY
    creds = Credentials.from_service_account_file(sa_key_path, scopes=scopes)
    gc = gspread.authorize(creds)
    return gc.open_by_key(sheet_id)


def _header_values(ws) -> list[str]:
    values = ws.row_values(1)
    return [str(v) for v in values[:SCHEMA_COLUMNS]]


def worksheet_is_blank(ws) -> bool:
    # Fast path: a populated first row is enough to prove non-blank.
    if any(str(cell).strip() for cell in ws.row_values(1)):
        return False
    # A custom workbook may have row 1 blank but data lower down. Only then do the broader read.
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


def resolve_region_worksheet(sh, region: str, *, selected: bool = False):
    title = selected_tab(region) if selected else raw_tab(region)
    try:
        ws = sh.worksheet(title)
    except Exception as exc:
        raise TrackerError(
            "REGION_NOT_INITIALIZED",
            f"worksheet {title!r} does not exist; run initialize_job_tracker first",
        ) from exc
    validation = validate_worksheet_schema(ws)
    if not validation["ok"]:
        raise TrackerError(
            "SCHEMA_MISMATCH",
            f"worksheet {title!r} does not match {SCHEMA_VERSION}: {validation['first_mismatch']}",
        )
    return ws


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
        header_cells.append({
            "userEnteredValue": {"stringValue": header},
            "note": note,
            "userEnteredFormat": {
                "backgroundColor": HEADER_RGB,
                "textFormat": {"foregroundColor": WHITE_RGB, "bold": True, "fontFamily": "Arial"},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            },
        })

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
        requests.append({
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
        })

    for value, color in STATUS_COLORS.items():
        requests.append({
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
        })

    for value, color in PRIORITY_COLORS.items():
        requests.append({
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
        })

    for col, width in enumerate(COLUMN_WIDTHS):
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": int(sheet_id), "dimension": "COLUMNS",
                    "startIndex": col, "endIndex": col + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    requests.append({
        "updateDimensionProperties": {
            "range": {"sheetId": int(sheet_id), "dimension": "ROWS", "startIndex": 0, "endIndex": 1},
            "properties": {"pixelSize": HEADER_HEIGHT_PX},
            "fields": "pixelSize",
        }
    })
    return requests


def _apply_schema(sh, ws) -> None:
    # Existing blank user tabs can be smaller than the A:AA/1000-row contract.
    # Grow them before raw Sheets API requests so updateCells/ranges stay in-bounds.
    if int(ws.col_count) < SCHEMA_COLUMNS:
        ws.add_cols(SCHEMA_COLUMNS - int(ws.col_count))
    if int(ws.row_count) < DEFAULT_ROWS:
        ws.add_rows(DEFAULT_ROWS - int(ws.row_count))
    sh.batch_update({"requests": _schema_requests(ws.id, ws.row_count)})


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


def initialize_job_tracker(
    sheet_id: str,
    sa_key_path: str,
    regions: Iterable[str] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    sh = _open_spreadsheet(sa_key_path, sheet_id, write=not dry_run)
    plan = plan_initialize(sh, regions)
    if plan["incompatible"]:
        return {
            "ok": False, "dry_run": dry_run, "error_code": "SCHEMA_MISMATCH",
            "message": "one or more target region sheets already contain incompatible data; no changes made",
            **plan,
        }
    if dry_run:
        return {
            "ok": True, "dry_run": True,
            "message": "initialization preview only; no Sheet writes performed",
            **plan,
        }

    worksheets = {ws.title: ws for ws in sh.worksheets()}
    configured: list[str] = []
    created: list[str] = []

    for title in plan["create"]:
        ws = sh.add_worksheet(title=title, rows=DEFAULT_ROWS, cols=SCHEMA_COLUMNS)
        _apply_schema(sh, ws)
        worksheets[title] = ws
        created.append(title)
        configured.append(title)

    for title in plan["configure_blank"]:
        ws = worksheets[title]
        _apply_schema(sh, ws)
        configured.append(title)

    removed_blank_defaults: list[str] = []
    protected = set(expected_tabs(plan["regions"]))
    for ws in _find_blank_default_sheets(sh, protected):
        sh.del_worksheet(ws)
        removed_blank_defaults.append(ws.title)

    return {
        "ok": True,
        "dry_run": False,
        "schema_version": SCHEMA_VERSION,
        "regions": plan["regions"],
        "created": created,
        "configured": configured,
        "already_compatible": plan["already_compatible"],
        "removed_blank_defaults": removed_blank_defaults,
        "message": "job tracker initialized",
    }


def open_region_raw(sheet_id: str, sa_key_path: str, region: str, *, write: bool = False):
    sh = _open_spreadsheet(sa_key_path, sheet_id, write=write)
    return sh, resolve_region_worksheet(sh, region, selected=False)


def read_region_rows(sheet_id: str, sa_key_path: str, region: str) -> list[list[str]]:
    _sh, ws = open_region_raw(sheet_id, sa_key_path, region, write=False)
    return ws.get_all_values()[1:]
