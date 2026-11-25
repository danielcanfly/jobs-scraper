"""量 JobStreet 5 個 keyword 之間的結果集重疊率 (唯讀)。

每個 keyword 只抓第 1 頁 (20 筆), 算兩兩重疊。
重疊高 → 5 個 keyword 的池子幾乎是同一批職缺, per-keyword 爬完的邊際產出低。
"""

from __future__ import annotations

import itertools
import os
import sys
import time
from pathlib import Path

sys.path.insert(
    0, os.environ.get("UPSTREAM_DIR", str(Path.home() / ".minimax-agent" / "projects" / "jobs-scraper-unified"))
)

from curl_cffi import requests as cc_requests  # noqa: E402

from jobs_scraper.sources import jobstreet as JS  # noqa: E402

KEYWORDS = [
    "product manager",
    "product director",
    "director of product",
    "head of product",
    "product lead",
]


def main() -> int:
    daterange = sys.argv[1] if len(sys.argv) > 1 else "7"
    session = cc_requests.Session(impersonate="chrome")
    sets: dict[str, set[str]] = {}
    totals: dict[str, object] = {}
    for kw in KEYWORDS:
        data = JS.fetch_list_page(kw, 1, daterange, session=session, sleep_seconds=lambda s: None)
        ids = {str(r.get("id")) for r in (data.get("data") or []) if r.get("id")}
        sets[kw] = ids
        totals[kw] = data.get("totalCount")
        print(f"{kw!r:24} p1={len(ids):3}  totalCount={totals[kw]}")
        time.sleep(1.0)

    print("\n=== 兩兩重疊 (交集 / 聯集) ===")
    for a, b in itertools.combinations(KEYWORDS, 2):
        inter = len(sets[a] & sets[b])
        union = len(sets[a] | sets[b])
        print(f"{a!r:22} vs {b!r:22} 交 {inter:3} / 聯 {union:3}  ({inter / union:.0%})")

    all_union = set().union(*sets.values())
    print(f"\n5 個 keyword 第 1 頁聯集 = {len(all_union)} 筆")
    return 0


if __name__ == "__main__":
    sys.exit(main())
