"""Google Sheets client and worksheet boundary helpers for Job Tracker."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .audit import read_tracker_rows, validate_worksheet_schema
from .schema import SCHEMA_VERSION, TrackerError, raw_tab, selected_tab

SCOPES_READONLY = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_WRITE = ["https://www.googleapis.com/auth/spreadsheets"]


def _resolve_sa_key_path(repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[2]
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


def open_region_raw(sheet_id: str, sa_key_path: str, region: str, *, write: bool = False):
    sh = _open_spreadsheet(sa_key_path, sheet_id, write=write)
    return sh, resolve_region_worksheet(sh, region, selected=False)


def read_region_rows(sheet_id: str, sa_key_path: str, region: str) -> list[list[str]]:
    _sh, ws = open_region_raw(sheet_id, sa_key_path, region, write=False)
    return read_tracker_rows(ws)
