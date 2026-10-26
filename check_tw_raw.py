# ruff: noqa: E402
# One-off maintenance script: sys.path is adjusted for the local module before
# the imports below, so the module-level import order is intentional.
#!/usr/bin/env python3
"""Read-only SG/TW tab inventory for the configured Sheet."""

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
    sid, sa, sg_gid, tw_gid = _cfg(require_tw=True)
    sh = _client(sa).open_by_key(sid)
    tw = sh.get_worksheet_by_id(int(tw_gid))
    values = tw.get_all_values()
    print(f"TW target title={tw.title!r} gid={tw_gid} rows={max(0, len(values) - 1)}")
    src = Counter(r[3] for r in values[1:] if len(r) > 3)
    print("source_distribution=", dict(src))
    if sg_gid:
        sg = sh.get_worksheet_by_id(int(sg_gid))
        sv = sg.get_all_values()
        print(f"SG target title={sg.title!r} gid={sg_gid} rows={max(0, len(sv) - 1)}")
        if values and sv:
            print("headers_equal=", values[0] == sv[0])


if __name__ == "__main__":
    main()
