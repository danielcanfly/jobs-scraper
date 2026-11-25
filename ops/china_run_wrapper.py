#!/usr/bin/env python3
"""China run wrapper — 不改 repo 程式碼，只在執行期調整節奏。

v1.6.5 起 repo 本身已經處理：
  - 合法空 list page → 解析成 0 筆（不會 crash，連續兩頁空才判定到底）
  - JD 抓取 429/5xx/連線錯誤 → 30/60/90s 階梯重試

所以這個 wrapper 只負責「節奏」：
  - list 頁之間的 sleep (預設 7-16s, 可用 CN_LIST_SLEEP_MIN/MAX 覆寫)
    限流是被請求速度觸發的 → 對被限流的 geoId 放慢 list 節奏最有效。
  - JD 之間的 sleep (預設 7-16s, 可用 CN_SLEEP_MIN/MAX 覆寫)

用法: 跟原本 sg_product_jobs.py 的 CLI 完全一樣, 只是換成這個入口。
  python run_china_wrapper.py 14d --source linkedin --location Hangzhou --with-jd ...
"""

import os
import random
import sys
import time
from pathlib import Path

PLUGIN = os.environ.get("JOBS_SCRAPER_DIR", str(Path.home() / ".minimax" / "plugins" / "jobs-scraper"))
os.chdir(PLUGIN)
sys.path.insert(0, PLUGIN)

import sg_product_jobs as M  # noqa: E402

LIST_SLEEP_MIN = float(os.environ.get("CN_LIST_SLEEP_MIN", "7"))
LIST_SLEEP_MAX = float(os.environ.get("CN_LIST_SLEEP_MAX", "16"))
JD_SLEEP_MIN = float(os.environ.get("CN_SLEEP_MIN", "7"))
JD_SLEEP_MAX = float(os.environ.get("CN_SLEEP_MAX", "16"))

M.SLEEP_MIN = JD_SLEEP_MIN
M.SLEEP_MAX = JD_SLEEP_MAX


def human_sleep(label: str = ""):
    """list 與 JD 可以各自用不同的節奏。"""
    if label == "list":
        lo, hi = LIST_SLEEP_MIN, LIST_SLEEP_MAX
    else:
        lo, hi = JD_SLEEP_MIN, JD_SLEEP_MAX
    s = random.uniform(lo, hi)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    time.sleep(s)


M.human_sleep = human_sleep

if __name__ == "__main__":
    print(
        f"==== [wrapper] list sleep={LIST_SLEEP_MIN}-{LIST_SLEEP_MAX}s, "
        f"jd sleep={JD_SLEEP_MIN}-{JD_SLEEP_MAX}s "
        f"(空頁與 JD 429 由 v1.6.5 的 repo 邏輯處理) ====",
        flush=True,
    )
    M.main()
