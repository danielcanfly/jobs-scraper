"""Read-only probe: how deep does Shanghai's 30d LinkedIn pool actually go?

The 2026-11-22 30d run stopped at the 70-page cap with page 70 still full
(10/10), so the pool was NOT exhausted at ~700 jobs. This probe walks a few
pages past that point to find out whether jobs keep coming back, so the
30d MAX_PAGES default can be set from evidence instead of a guess.

Read-only: it only issues list-page GETs, it writes nothing to the Sheet.
"""

import os
import sys
import time
from pathlib import Path

PLUGIN = os.environ.get("JOBS_SCRAPER_DIR", str(Path.home() / ".minimax" / "plugins" / "jobs-scraper"))
sys.path.insert(0, PLUGIN)

# Proxy for the scraper path only; CONTROL_PLANE_HTTP_PROXY must not leak in.
os.environ.pop("CONTROL_PLANE_HTTP_PROXY", None)
os.environ["JOBS_SCRAPER_PROXY"] = "http://127.0.0.1:12000"

from curl_cffi import requests as cc_requests  # noqa: E402

from jobs_scraper.sources import linkedin as LI  # noqa: E402

GEO = "107388191"
LOC = "Shanghai"
TPR = "r2592000"

STARTS = [700, 750, 800, 850, 900, 950, 1000, 1100]


def main() -> None:
    sess = cc_requests.Session(impersonate="chrome")
    for start in STARTS:
        try:
            html = LI.fetch_list_page(TPR, start, LOC, GEO, session=sess, sleep=time.sleep)
        except Exception as e:  # noqa: BLE001
            print(f"start={start} ERR {type(e).__name__}: {e}", flush=True)
            break
        jobs = LI.parse_list_page(html)
        ids = [j["job_id"] for j in jobs]
        print(
            f"start={start:5d} html_len={len(html):6d} jobs={len(jobs):3d} sample={ids[:3]}",
            flush=True,
        )
        if not jobs:
            print(f"start={start} → 0 jobs (pool bottom reached here)", flush=True)
            break
        time.sleep(8)


if __name__ == "__main__":
    main()
