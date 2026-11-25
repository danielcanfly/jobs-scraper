"""Read-only probe: Singapore pool depth for every range, both sources.

Needed for the v1.6.7 budget fix. The v1.6.6 budgets were pinned to Shanghai's
pool depths; Singapore's pools are deeper for 7d (550 vs 400 postings) and
JobStreet was never measured at all (its API reports totalCount=494 for SG 7d
while the engine budget allowed only 15 pages = 300 postings).

Part 1 — LinkedIn: walk the list API per range until it answers with an empty
page, which is the pool bottom.
Part 2 — JobStreet: one page per keyword per range, reading the API's own
totalCount (the API states how many postings match, so one request is enough).

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

from jobs_scraper.sources import jobstreet as JS  # noqa: E402
from jobs_scraper.sources import linkedin as LI  # noqa: E402

GEO = "102454443"
LOC = "Singapore"

# range -> LinkedIn f_TPR ; JobStreet takes the range name directly
RANGES = [
    ("1h", "r3600"),
    ("24h", "r86400"),
    ("3d", "r259200"),
    ("7d", "r604800"),
    ("14d", "r1209600"),
    ("21d", "r1814400"),
    ("30d", "r2592000"),
]
LADDER = [0, 10, 30, 60, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800]


def linkedin_depth(sess, tpr):
    for start in LADDER:
        html = LI.fetch_list_page(tpr, start, LOC, GEO, session=sess, sleep=time.sleep)
        jobs = LI.parse_list_page(html)
        print(f"    start={start:5d} jobs={len(jobs):3d}", flush=True)
        if not jobs:
            return start
        time.sleep(8)
    return None


def main() -> None:
    sess = cc_requests.Session(impersonate="chrome")

    print("=== LinkedIn SG pool depth ===", flush=True)
    for label, tpr in RANGES:
        print(f"  {label} (tpr={tpr}):", flush=True)
        bottom = linkedin_depth(sess, tpr)
        if bottom is None:
            print(f"    → 沒有到底 (start={LADDER[-1]} 還有職缺)", flush=True)
        else:
            print(f"    → 池底 start={bottom} (~{bottom} 筆 = {bottom // 10} 頁)", flush=True)

    print("\n=== JobStreet SG totalCount (每個 keyword 每個 range) ===", flush=True)
    for label, _tpr in RANGES:
        counts = {}
        for kw in JS.DEFAULT_KEYWORDS:
            data = JS.fetch_list_page(kw, 1, label, session=sess, sleep_seconds=time.sleep)
            counts[kw] = data.get("totalCount", "?")
            time.sleep(2)
        biggest = max((v for v in counts.values() if isinstance(v, int)), default=0)
        need = -(-biggest // 20)
        print(f"  {label}: {counts} → 最大 {biggest} 筆 → 需要 {need} 頁", flush=True)


if __name__ == "__main__":
    main()
