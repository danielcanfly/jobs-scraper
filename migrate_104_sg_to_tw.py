# ruff: noqa: E402
# One-off maintenance script: sys.path is adjusted for the local module before
# the imports below, so the module-level import order is intentional.
#!/usr/bin/env python3
"""Preview-first migration of legacy 104 rows from configured SG-Raw to TW-Raw."""

from __future__ import annotations

import argparse
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    sid, sa, sg_gid, tw_gid = _cfg(require_sg=True, require_tw=True)
    sh = _client(sa, write=args.execute).open_by_key(sid)
    sg = sh.get_worksheet_by_id(int(sg_gid))
    tw = sh.get_worksheet_by_id(int(tw_gid))
    sgv = sg.get_all_values()
    legacy = [
        (i, (list(r[:11]) + [""] * 11)[:11])
        for i, r in enumerate(sgv[1:], start=2)
        if len(r) > 3 and r[3] == "104 / Minimax"
    ]
    print(f"sg_gid={sg_gid} tw_gid={tw_gid} legacy_104_rows={len(legacy)} execute={args.execute}")
    if not legacy:
        return
    if not args.execute:
        print(
            "DRY_RUN_ONLY: no Sheet mutation. Rerun with --execute after reviewing audit_104_before_migration.py output."
        )
        return
    # Preserve complete A:K row values. E is formula/user-entered; remaining columns are RAW text for injection safety.
    tv = tw.get_all_values()
    start = len(tv) + 1
    end = start + len(legacy) - 1
    if end > tw.row_count:
        tw.add_rows(end - tw.row_count + 20)
    rows = [r for _, r in legacy]
    tw.update(f"E{start}:E{end}", [[r[4]] for r in rows], value_input_option="USER_ENTERED")
    tw.update(f"A{start}:D{end}", [r[:4] for r in rows], value_input_option="RAW")
    tw.update(f"F{start}:K{end}", [r[5:11] for r in rows], value_input_option="RAW")
    # Delete exact legacy rows from bottom to top, robust even if they are not contiguous.
    for i, _ in reversed(legacy):
        sg.delete_rows(i)
    print(f"migrated={len(legacy)}")


if __name__ == "__main__":
    main()
