"""Read-only probe: SG 7d pool depth for LinkedIn and JobStreet.

Context: v1.6.6 raised the LinkedIn per-range page budgets from measured pool
depths (Shanghai). Singapore was never measured — the 7d budget used to be 15
pages and is now 55. This probe finds out where Singapore's pools actually
bottom, so the run can be sized instead of guessed.

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

GEO = "102454443"
LOC = "Singapore"
TPR = "r604800"
LADDER = [0, 50, 100, 150, 200, 250, 300, 400, 500, 550]


def main() -> None:
    sess = cc_requests.Session(impersonate="chrome")
    print("=== LinkedIn SG 7d ===", flush=True)
    for start in LADDER:
        try:
            html = LI.fetch_list_page(TPR, start, LOC, GEO, session=sess, sleep=time.sleep)
        except Exception as e:  # noqa: BLE001
            print(f"  start={start} ERR {type(e).__name__}: {e}", flush=True)
            break
        jobs = LI.parse_list_page(html)
        print(f"  start={start:5d} jobs={len(jobs):3d}", flush=True)
        if not jobs:
            print(f"  → pool bottom at start={start} (~{start} jobs)", flush=True)
            break
        time.sleep(8)


if __name__ == "__main__":
    main()
