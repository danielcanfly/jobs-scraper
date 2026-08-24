"""Legacy v1.0 Sheet configuration and read-only row loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import runtime_core as RT
from jobs_scraper.mcp_services import errors

SCOPES_READONLY = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_WRITE = ["https://www.googleapis.com/auth/spreadsheets"]
LEGACY_READ_RANGE = "A2:K"


def resolve_sa_key_path(repo_root: Path = RT.REPO_ROOT) -> str:
    """Resolve GSPREAD_SA_KEY_PATH to an absolute path."""
    sa = os.getenv("GSPREAD_SA_KEY_PATH", "").strip() or ".secrets/gsheet-sa.json"
    if not Path(sa).is_absolute():
        sa = str(repo_root / sa)
    return sa


def check_legacy_sheet_config_or_raise(repo_root: Path = RT.REPO_ROOT) -> tuple[str, str, str]:
    """Return (sa_key_path, sheet_id, sheet_gid) or raise a typed internal error."""
    sid = os.getenv("SHEET_ID", "").strip()
    gid = os.getenv("SHEET_GID", "").strip()
    placeholder_ids = {"your_google_sheet_id_here", "your-sheet-id", "replace_me"}
    placeholder_gids = {"your_sheet_gid_here", "your-gid", "replace_me"}
    sid_missing = not sid or sid.lower() in placeholder_ids
    gid_missing = not gid or gid.lower() in placeholder_gids
    if sid_missing or gid_missing:
        missing = []
        if sid_missing:
            missing.append("SHEET_ID")
        if gid_missing:
            missing.append("SHEET_GID")
        raise errors.ConfigMissing(
            f"missing env: {', '.join(missing)} — set them in .env or pass via MCP host env. The server never falls back to the package author's Sheet."
        )
    sa = resolve_sa_key_path(repo_root)
    if not Path(sa).exists():
        raise errors.CredentialFileMissing(f"credential file not found: {sa}")
    return sa, sid, gid


def check_legacy_sheet_config(repo_root: Path = RT.REPO_ROOT) -> tuple[str, str, str] | dict[str, Any]:
    """Return (sa_key_path, sheet_id, sheet_gid) or a structured fail-closed error."""
    try:
        return check_legacy_sheet_config_or_raise(repo_root)
    except errors.ServiceError as exc:
        return {"ok": False, **errors.public_error(exc)}


def _worksheet_get(ws, range_name: str) -> list[list[str]]:
    if hasattr(ws, "get"):
        rows = ws.get(range_name)
    else:
        rows = ws.get_values(range_name)
    return [list(row) for row in rows]


def read_legacy_rows_from_worksheet(ws) -> list[list[str]]:
    """Read only the v1.0 audit/stat columns A:K after the header row."""
    return _worksheet_get(ws, LEGACY_READ_RANGE)


def read_legacy_sheet_rows(sa_key_path: str, sheet_id: str, gid: str) -> list[list[str]]:
    """Read legacy GID-addressed rows using readonly OAuth scope."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(sa_key_path, scopes=SCOPES_READONLY)
    gc = gspread.authorize(creds)
    try:
        ws = gc.open_by_key(sheet_id).get_worksheet_by_id(int(gid))
        return read_legacy_rows_from_worksheet(ws)
    except errors.ServiceError:
        raise
    except Exception as exc:
        raise errors.SheetNotFound(f"could not read sheet: {type(exc).__name__}: {exc}") from exc
