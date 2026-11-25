"""Read-only baseline for a Google Sheet tab: row count + (source, job_id) keys.

Usage: python sheet_baseline.py <gid>
Prints the numbers a later verification run compares against.
"""

import os
import sys
from pathlib import Path

PLUGIN = os.environ.get("JOBS_SCRAPER_DIR", str(Path.home() / ".minimax" / "plugins" / "jobs-scraper"))
sys.path.insert(0, PLUGIN)
os.chdir(PLUGIN)

os.environ.pop("CONTROL_PLANE_HTTP_PROXY", None)

import gspread  # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

import sg_product_jobs as M  # noqa: E402


def main() -> None:
    gid = int(sys.argv[1]) if len(sys.argv) > 1 else M.SG_RAW_GID
    creds = Credentials.from_service_account_file(
        M.SHEET_SA_KEY, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(M.SG_RAW_SHEET_ID)
    ws = sh.get_worksheet_by_id(gid)
    rows = ws.get_all_values()
    keys = M._load_sheet_keys(rows)
    data_rows = len([r for r in rows[1:] if any(c.strip() for c in r)])
    by_source: dict[str, int] = {}
    for r in rows[1:]:
        if len(r) > 3 and r[3].strip():
            by_source[r[3].strip()] = by_source.get(r[3].strip(), 0) + 1
    print(f"gid={gid} title={ws.title!r} total_rows={len(rows)} data_rows={data_rows}")
    print(f"(source, job_id) keys={len(keys[0])} next_row={keys[1]}")
    for label, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {label}: {n}")


if __name__ == "__main__":
    main()
