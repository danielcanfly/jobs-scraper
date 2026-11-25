"""Read-only probe: where does each Shanghai/Shenzhen pool actually bottom out?

The 2026-11-21/22 runs stopped on the MAX_PAGES cap for several city/range
combinations without ever printing the EOF marker, so the pool may have been
truncated. This probe asks the list API for the pages just past the cap.

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

# (label, geoId, location, tpr, [(start, ...)])
CASES = [
    ("shanghai-7d", "107388191", "Shanghai", "r604800", [140, 150, 160]),
    ("shanghai-14d", "107388191", "Shanghai", "r1209600", [290, 300, 310]),
    ("shenzhen-7d", "106750182", "Shenzhen", "r604800", [130, 140, 150]),
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
            print(
                f"  start={start:5d} html_len={len(html):6d} jobs={len(jobs):3d}",
                flush=True,
            )
            if not jobs:
                print(f"  → pool bottom at start={start}", flush=True)
                break
            time.sleep(8)


if __name__ == "__main__":
    main()
