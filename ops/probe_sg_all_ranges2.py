"""Read-only probe: Singapore pool depth, corrected.

Two fixes over the first attempt:
  1. JobStreet's `daterange` parameter takes a **number of days** ("7"), not the
     CLI range name ("7d"). The engine maps it via JOBSTREET_TPR; the first
     probe passed "7d" directly, so the API ignored the filter and answered
     with the unfiltered total (2466 instead of 494).
  2. The LinkedIn ladder is extended past 800 — Singapore's 14d/21d/30d pools
     were deeper than the first ladder could reach.

Output goes to a file as it happens, so progress can be watched.

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
OUT = str(
    Path(os.environ.get("JOBS_SCRAPER_RUNTIME_DIR", str(Path.home() / ".minimax-agent" / "projects" / ".runs")))
    / "probe_sg_all_ranges2.log"
)

# range -> (LinkedIn f_TPR, JobStreet daterange in DAYS)
RANGES = [
    ("1h", "r3600", "1"),
    ("24h", "r86400", "1"),
    ("3d", "r259200", "3"),
    ("7d", "r604800", "7"),
    ("14d", "r1209600", "14"),
    ("21d", "r1814400", "21"),
    ("30d", "r2592000", "30"),
]
LADDER = [0, 10, 30, 60, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1300, 1400]


def log(msg: str) -> None:
    print(msg, flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


def linkedin_depth(sess, tpr):
    for start in LADDER:
        try:
            html = LI.fetch_list_page(tpr, start, LOC, GEO, session=sess, sleep=time.sleep)
        except Exception as e:  # noqa: BLE001
            log(f"    start={start} ERR {type(e).__name__}: {e}")
            return None
        jobs = LI.parse_list_page(html)
        log(f"    start={start:5d} jobs={len(jobs):3d}")
        if not jobs:
            return start
        time.sleep(8)
    return None


def main() -> None:
    open(OUT, "w", encoding="utf-8").close()
    sess = cc_requests.Session(impersonate="chrome")

    log("=== LinkedIn SG pool depth ===")
    for label, tpr, _js_days in RANGES:
        log(f"  {label} (tpr={tpr}):")
        bottom = linkedin_depth(sess, tpr)
        if bottom is None:
            log(f"    → 沒有到底 (start={LADDER[-1]} 還有職缺 → 池 >{LADDER[-1]} 筆)")
        else:
            log(f"    → 池底 start={bottom} (~{bottom} 筆 = {bottom // 10} 頁)")

    log("\n=== JobStreet SG totalCount (每個 keyword 每個 range, daterange=天數) ===")
    for label, _tpr, js_days in RANGES:
        counts = {}
        for kw in JS.DEFAULT_KEYWORDS:
            data = JS.fetch_list_page(kw, 1, js_days, session=sess, sleep_seconds=time.sleep)
            counts[kw] = data.get("totalCount", "?")
            time.sleep(2)
        biggest = max((v for v in counts.values() if isinstance(v, int)), default=0)
        need = -(-biggest // 20)
        log(f"  {label} (daterange={js_days}): {counts} → 最大 {biggest} 筆 → 需要 {need} 頁")
    log("\nDONE")


if __name__ == "__main__":
    main()
