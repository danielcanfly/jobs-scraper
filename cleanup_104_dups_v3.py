# ruff: noqa: E402
# One-off maintenance script: sys.path is adjusted for the local module before
# the imports below, so the module-level import order is intentional.
#!/usr/bin/env python3
"""Preview-first dynamic 104 duplicate cleanup on configured TW-Raw."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import gspread
from google.oauth2.service_account import Credentials

import sg_product_jobs as M


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


from collections import defaultdict


def groups(indices):
    out = []
    for n in sorted(indices):
        if not out or n > out[-1][1] + 1:
            out.append([n, n])
        else:
            out[-1][1] = n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()
    sid, sa, _, tw_gid = _cfg(require_tw=True)
    ws = _client(sa, write=args.execute).open_by_key(sid).get_worksheet_by_id(int(tw_gid))
    values = ws.get_all_values()
    seen = defaultdict(list)
    for i, r in enumerate(values[1:], start=2):
        if len(r) > 3 and r[3] == "104 / Minimax":
            key = M.parse_sheet_row_to_key(r)
            if key:
                seen[key].append(i)
    delete = []
    for rows in seen.values():
        delete.extend(rows[1:])
    print(f"tw_gid={tw_gid} duplicate_rows={len(delete)} execute={args.execute}")
    print("delete_groups=", groups(delete))
    if not args.execute:
        print("DRY_RUN_ONLY: rerun with --execute to mutate the configured TW-Raw tab")
        return
    for start, end in reversed(groups(delete)):
        ws.delete_rows(start, end)
    print(f"deleted={len(delete)}")


if __name__ == "__main__":
    main()
