"""Read-only probe: pool depth for every Shanghai time range.

Measured so far (Shanghai / geoId 107388191, 2026-11-22):
  30d → bottom at start=700 (700 jobs)
  21d → bottom at start=300 (300 jobs)
  14d → bottom at start=290 (290 jobs)
   7d → start=300 still returns 10 jobs → deeper than 310

The 7d pool being deeper than 14d means the guest API's date filter is not a
strict subset, so each range needs its own measured budget.

This walks a coarse ladder per range and stops at the first empty page.

Read-only: list-page GETs only, nothing is written to the Sheet.
"""

import os
import sys
import time
from pathlib import Path

PLUGIN = os.environ.get("JOBS_SCRAPER_DIR", str(Path.home() / ".minimax" / "plugins" / "jobs-scraper"))
sys.path.insert(0, PLUGIN)

os.environ.pop("CONTROL_PLANE_HTTP_PROXY", None)
os.environ["JOBS_SCRAPER_PROXY"] = "http://127.0.0.1:12000"

from curl_cffi import requests as cc_requests  # noqa: E402

from jobs_scraper.sources import linkedin as LI  # noqa: E402

GEO = "107388191"
LOC = "Shanghai"
LADDER = [0, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500, 600, 700, 800]
RANGES = [
    ("1h", "r3600"),
    ("24h", "r86400"),
    ("3d", "r259200"),
    ("7d", "r604800"),
]


def main() -> None:
    sess = cc_requests.Session(impersonate="chrome")
    for label, tpr in RANGES:
        print(f"\n=== {label} (tpr={tpr}) ===", flush=True)
        bottom = None
        for start in LADDER:
            try:
                html = LI.fetch_list_page(tpr, start, LOC, GEO, session=sess, sleep=time.sleep)
            except Exception as e:  # noqa: BLE001
                print(f"  start={start} ERR {type(e).__name__}: {e}", flush=True)
                break
            jobs = LI.parse_list_page(html)
            print(f"  start={start:5d} jobs={len(jobs):3d}", flush=True)
            if not jobs:
                bottom = start
                break
            time.sleep(12)
        if bottom is None:
            print(f"  → still non-empty at start={LADDER[-1]} (pool deeper)", flush=True)
        else:
            print(f"  → pool bottom at start={bottom} (~{bottom} jobs)", flush=True)


if __name__ == "__main__":
    main()
