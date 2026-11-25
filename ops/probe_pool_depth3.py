"""Read-only probe: pin down where Shanghai's 7d pool bottoms.

Known so far (Shanghai, the largest city):
  30d → bottom at start=700 (700 jobs)
  21d → bottom at start=300 (300 jobs)
  14d → bottom at start=290 (290 jobs)
   7d → start=240 still returns 10 jobs → deeper than 250

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


def main() -> None:
    sess = cc_requests.Session(impersonate="chrome")
    for start in (250, 260, 270, 280, 290, 300):
        html = LI.fetch_list_page("r604800", start, "Shanghai", "107388191", session=sess, sleep=time.sleep)
        jobs = LI.parse_list_page(html)
        print(f"  start={start:5d} html_len={len(html):6d} jobs={len(jobs):3d}", flush=True)
        if not jobs:
            print(f"  → pool bottom at start={start}", flush=True)
            break
        time.sleep(12)


if __name__ == "__main__":
    main()
