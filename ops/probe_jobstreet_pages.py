"""量 JobStreet list API 的真實分頁行為 (唯讀, 不抓 JD)。

每個 keyword 逐頁抓, 記錄:
  - 該頁筆數
  - 該頁相對「上一頁」重疊幾筆 (看 API 會不會跨頁重複)
  - 累計 unique 筆數 (看 kw_new 的成長曲線 → 決定 50% 軟停門檻)
  - 該頁的 kw_new (本 keyword 尚未回過的筆數)

用法: python probe_jobstreet_pages.py <keyword> <daterange_days> <max_pages>
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


def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "product manager"
    daterange = sys.argv[2] if len(sys.argv) > 2 else "7"
    max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    session = cc_requests.Session(impersonate="chrome")
    seen: set[str] = set()
    prev_ids: set[str] = set()
    print(f"=== keyword={keyword!r} daterange={daterange} max_pages={max_pages} ===")
    print(f"{'p':>3} {'筆數':>4} {'對上頁重疊':>6} {'kw_new':>6} {'kw_cum':>7} {'totalCount':>10}")
    for p in range(1, max_pages + 1):
        try:
            data = JS.fetch_list_page(
                keyword,
                p,
                daterange,
                session=session,
                sleep_seconds=lambda s: None,
            )
        except Exception as e:
            print(f"{p:>3}  FAIL {type(e).__name__}: {e}")
            break
        rows = data.get("data") or []
        ids = [str(r.get("id")) for r in rows if r.get("id")]
        overlap = len(set(ids) & prev_ids)
        kw_new = len([i for i in ids if i not in seen])
        seen.update(ids)
        prev_ids = set(ids)
        print(f"{p:>3} {len(ids):>4} {overlap:>6} {kw_new:>6} {len(seen):>7} {data.get('totalCount', '?'):>10}")
        if len(ids) == 0:
            break
        time.sleep(1.0)
    print(f"--- 最終 kw unique = {len(seen)} (API totalCount={data.get('totalCount', '?')}) ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
