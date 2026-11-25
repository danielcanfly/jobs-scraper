"""Read-only acceptance check for a Google Sheet tab after a run.

Usage: python verify_sheet.py <gid> <baseline_rows>

Checks:
  - how many data rows were added since the baseline
  - duplicate (source, job_id) pairs
  - empty JD column (column H) among the added rows
  - the source labels in column D
  - whether any row was written without a URL/job id
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
    baseline = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    creds = Credentials.from_service_account_file(
        M.SHEET_SA_KEY, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(M.SG_RAW_SHEET_ID)
    ws = sh.get_worksheet_by_id(gid)
    rows = ws.get_all_values()

    keys, next_row = M._load_sheet_keys(rows)
    data_rows = [r for r in rows[1:] if any(c.strip() for c in r)]

    seen: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(rows[1:], start=2):
        k = M.parse_sheet_row_to_key(r)
        if k:
            seen.setdefault(k, []).append(i)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}

    added = rows[baseline : baseline + 4000]
    added = [r for r in added if any(c.strip() for c in r)]
    empty_jd = [r for r in added if len(r) < 8 or not r[7].strip()]
    empty_url = [r for r in added if len(r) < 5 or not r[4].strip()]

    labels: dict[str, int] = {}
    for r in added:
        lab = r[3].strip() if len(r) > 3 else ""
        labels[lab or "(空)"] = labels.get(lab or "(空)", 0) + 1

    print(f"tab={ws.title!r} gid={gid}")
    print(f"total_rows={len(rows)} data_rows={len(data_rows)} next_row={next_row}")
    print(f"baseline={baseline} → 新增列數={len(added)}")
    print(f"(source, job_id) 唯一鍵={len(seen)}  重複組數={len(dupes)}")
    for k, v in list(dupes.items())[:5]:
        print(f"  DUP {k} → rows {v}")
    print(f"新增列中 H 欄(JD)為空={len(empty_jd)}   E 欄(URL)為空={len(empty_url)}")
    print("新增列的 D 欄 source 分佈:")
    for lab, n in sorted(labels.items(), key=lambda x: -x[1]):
        print(f"  {lab}: {n}")


if __name__ == "__main__":
    main()
