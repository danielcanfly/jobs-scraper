# ruff: noqa: E402
# One-off maintenance script: sys.path is adjusted for the local module before
# the imports below, so the module-level import order is intentional.
#!/usr/bin/env python3
"""Read-only audit of any legacy 104 rows still present in configured SG-Raw."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import gspread
from google.oauth2.service_account import Credentials


def _cfg(require_sg: bool = False, require_tw: bool = False):
    sid = os.getenv("SHEET_ID", "").strip()
    sa = os.getenv("GSPREAD_SA_KEY_PATH", ".secrets/gsheet-sa.json").strip()
    if not Path(sa).is_absolute():
        sa = str(ROOT / sa)
    sg = os.getenv("SG_RAW_GID", "").strip() or os.getenv("SHEET_GID", "").strip()
    tw = os.getenv("TW_RAW_GID", "").strip()
    missing = []
    if not sid:
        missing.append("SHEET_ID")
    if not Path(sa).exists():
        missing.append("GSPREAD_SA_KEY_PATH(file)")
    if require_sg and not sg:
        missing.append("SG_RAW_GID")
    if require_tw and not tw:
        missing.append("TW_RAW_GID")
    if missing:
        raise SystemExit("CONFIG_MISSING: " + ", ".join(missing))
    for label, val in (("SG_RAW_GID", sg), ("TW_RAW_GID", tw)):
        if val and not val.isdigit():
            raise SystemExit(f"CONFIG_INVALID: {label} must be numeric")
    return sid, sa, sg, tw


def _client(sa: str, write: bool = False):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets"
        if write
        else "https://www.googleapis.com/auth/spreadsheets.readonly"
    ]
    return gspread.authorize(Credentials.from_service_account_file(sa, scopes=scopes))


from collections import Counter


def main():
    sid, sa, sg_gid, _ = _cfg(require_sg=True)
    ws = _client(sa).open_by_key(sid).get_worksheet_by_id(int(sg_gid))
    values = ws.get_all_values()
    rows = [(i, r) for i, r in enumerate(values[1:], start=2) if len(r) > 3 and r[3] == "104 / Minimax"]
    print(f"legacy_104_rows_in_sg={len(rows)}")
    print("status_distribution=", dict(Counter((r[0] if len(r) > 0 else "") for _, r in rows)))
    print("priority_nonempty=", sum(1 for _, r in rows if len(r) > 1 and r[1].strip()))
    print("notes_nonempty=", sum(1 for _, r in rows if len(r) > 10 and r[10].strip()))
    print("row_numbers=", [i for i, _ in rows[:25]], "..." if len(rows) > 25 else "")


if __name__ == "__main__":
    main()
