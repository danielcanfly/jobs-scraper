"""量 JobStreet 每個 range × 每個 keyword 的池深 (API 自報 totalCount, 只抓第 1 頁)。

用來驗證 per-keyword 爬完後, MAX_PAGES 預算是否還蓋得住最大的那個 keyword。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(
    0, os.environ.get("UPSTREAM_DIR", str(Path.home() / ".minimax-agent" / "projects" / "jobs-scraper-unified"))
)

from curl_cffi import requests as cc_requests  # noqa: E402

from jobs_scraper.sources import jobstreet as JS  # noqa: E402

RANGES = [("1h", "1"), ("24h", "1"), ("3d", "3"), ("7d", "7"), ("14d", "14"), ("21d", "21"), ("30d", "30")]
KEYWORDS = JS.DEFAULT_KEYWORDS


def main() -> int:
    session = cc_requests.Session(impersonate="chrome")
    print(f"{'range':>5} {'kw 池深 (totalCount)':>52} {'最大':>6} {'需要頁數':>8} {'MAX_PAGES':>9} {'夠?':>4}")
    for label, days in RANGES:
        counts = []
        for kw in KEYWORDS:
            data = JS.fetch_list_page(kw, 1, days, session=session, sleep_seconds=lambda s: None)
            counts.append(int(data.get("totalCount") or 0))
            time.sleep(0.8)
        biggest = max(counts)
        need = biggest // 20 + 2  # +1 EOF page, +1 safety
        budget = JS.MAX_PAGES[label]
        cells = " ".join(f"{c:>5}" for c in counts)
        print(f"{label:>5} {cells:>52} {biggest:>6} {need:>8} {budget:>9} {'OK' if budget >= need else 'SHORT':>4}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
