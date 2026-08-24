"""Legacy v1.0 Sheet configuration and read-only row loading."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import runtime_core as RT

SCOPES_READONLY = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SCOPES_WRITE = ["https://www.googleapis.com/auth/spreadsheets"]


def resolve_sa_key_path(repo_root: Path = RT.REPO_ROOT) -> str:
    """Resolve GSPREAD_SA_KEY_PATH to an absolute path."""
    sa = os.getenv("GSPREAD_SA_KEY_PATH", "").strip() or ".secrets/gsheet-sa.json"
    if not Path(sa).is_absolute():
        sa = str(repo_root / sa)
    return sa


def check_legacy_sheet_config(repo_root: Path = RT.REPO_ROOT) -> tuple[str, str, str] | dict[str, Any]:
    """Return (sa_key_path, sheet_id, sheet_gid) or a structured fail-closed error."""
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
        return {
            "ok": False,
            "error_code": "CONFIG_MISSING",
            "message": f"missing env: {', '.join(missing)} — set them in .env or pass via MCP host env. The server never falls back to the package author's Sheet.",
        }
    sa = resolve_sa_key_path(repo_root)
    if not Path(sa).exists():
        return {
            "ok": False,
            "error_code": "CREDENTIAL_FILE_MISSING",
            "message": f"credential file not found: {sa}",
        }
    return sa, sid, gid


def read_legacy_sheet_rows(sa_key_path: str, sheet_id: str, gid: str) -> list[list[str]]:
    """Read legacy GID-addressed rows using readonly OAuth scope."""
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(sa_key_path, scopes=SCOPES_READONLY)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(sheet_id).get_worksheet_by_id(int(gid))
    return ws.get_all_values()[1:]
