"""Read-only probe: find the true pool bottom for Shanghai 7d and 21d.

Round 1 established:
  - Shanghai 30d: bottom at start=700 (700 jobs)
  - Shanghai 14d: bottom at start=290 (290 jobs)
  - Shanghai 7d:  start=140/150/160 all still return 10 jobs → deeper than 160
  - Shenzhen 7d:  bottom at start=150 (150 jobs)

Round 2 pins the two open numbers: where Shanghai 7d ends, and where 21d ends.

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

CASES = [
    ("shanghai-7d", "107388191", "Shanghai", "r604800", [170, 180, 190, 200, 220, 240]),
    ("shanghai-21d", "107388191", "Shanghai", "r1814400", [300, 350, 400, 450, 500, 550]),
]


def main() -> None:
    sess = cc_requests.Session(impersonate="chrome")
    for label, geo, loc, tpr, starts in CASES:
        print(f"\n=== {label} (geo={geo}, tpr={tpr}) ===", flush=True)
        for start in starts:
            try:
                html = LI.fetch_list_page(tpr, start, loc, geo, session=sess, sleep=time.sleep)
            except Exception as e:  # noqa: BLE001
                print(f"  start={start} ERR {type(e).__name__}: {e}", flush=True)
                break
            jobs = LI.parse_list_page(html)
            print(f"  start={start:5d} html_len={len(html):6d} jobs={len(jobs):3d}", flush=True)
            if not jobs:
                print(f"  → pool bottom at start={start}", flush=True)
                break
            time.sleep(12)


if __name__ == "__main__":
    main()
