#!/usr/bin/env python3
"""把「本機 JD 快取有、但 SG-Raw sheet 裡沒有」的職缺補寫回去。

2026-11-24 事故: 寫入起點取「第一個空白 row」→ 一輪要寫 159 列時, 蓋掉了下面
158 列有資料的 row (v1.7.0 已修)。被蓋掉的職缺:
  - 不在 sheet 裡 → pre-dedup 不會擋 → 下次會重抓一次 JD (浪費配額)
  - 而且列本身消失了

本腳本從本機 *_jd.json 快取把這些職缺找出來, 用引擎自己的 push_to_sheet 補寫
(同樣的 dedup / 標題濾器 / visa / work mode / 三段式寫入)。

用法:
  python3 recover_missing_sg.py            # dry-run: 只印會寫什麼
  python3 recover_missing_sg.py --apply    # 真的寫入

只處理 SG 的快取檔 (sg_product_jobs_*.json / jobstreet_sg_*.json) →
中國 (shanghai/shenzhen) 與台灣的職缺各自屬於 China-Raw / TW-Raw, 不會被誤寫。
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

PLUGIN = os.environ.get("JOBS_SCRAPER_DIR", str(Path.home() / ".minimax" / "plugins" / "jobs-scraper"))
sys.path.insert(0, PLUGIN)
os.chdir(PLUGIN)  # .env / .secrets 都是相對路徑 → 一定要在 plugin 目錄跑

import sg_product_jobs as M  # noqa: E402
from jobs_scraper.mcp_services.sheet_config import read_legacy_sheet_rows  # noqa: E402

CACHE_GLOBS = ("sg_product_jobs_*.json", "jobstreet_sg_*.json")
SG_SOURCES = ("linkedin", "jobstreet")
SOURCE_LABEL = {
    "linkedin": "LinkedIn / Minimax",
    "jobstreet": "JobStreet / Minimax",
}


def load_cache_jobs() -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    files: list[str] = []
    for g in CACHE_GLOBS:
        files.extend(sorted(glob.glob(os.path.join(PLUGIN, g))))
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        items = d if isinstance(d, list) else list(d.values())
        for j in items:
            if not isinstance(j, dict):
                continue
            src = (j.get("source") or "").strip()
            jid = str(j.get("job_id") or "").strip()
            if src in SG_SOURCES and jid and j.get("jd_text"):
                out[(src, jid)] = j
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的寫入 (預設 dry-run)")
    args = ap.parse_args()

    rows = read_legacy_sheet_rows(M.SHEET_SA_KEY, M.SG_RAW_SHEET_ID, str(M.SG_RAW_GID))
    sheet_keys = {k for k in (M.parse_sheet_row_to_key(r) for r in rows[1:]) if k}
    print(f"Sheet 目前 {len(rows)} 列 / {len(sheet_keys)} 個 (source, job_id) key")

    cache = load_cache_jobs()
    missing = {k: j for k, j in cache.items() if k not in sheet_keys}
    print(f"本機 SG 快取 {len(cache)} 筆 → sheet 沒有 {len(missing)} 筆")

    # 用引擎同一套 v8.5 標題濾器再篩一次: 那些本來就該被擋掉的職缺不補
    keep: dict[tuple[str, str], dict] = {}
    skipped = 0
    for k, j in missing.items():
        if M.match_skip_reason(j.get("title", ""), source=j.get("source")):
            skipped += 1
            continue
        keep[k] = j
    print(f"  其中通過 v8.5 標題濾器: {len(keep)} 筆 (被濾掉 {skipped} 筆, 本來就不該在表上)")

    by_source: dict[str, list[dict]] = {}
    for (src, _jid), j in keep.items():
        by_source.setdefault(src, []).append(j)
    for src, items in sorted(by_source.items()):
        print(f"  {src}: {len(items)} 筆")

    if not args.apply:
        print("\n=== DRY RUN (沒寫任何東西) ===")
        for src, items in sorted(by_source.items()):
            for j in items[:5]:
                print(f"  [{SOURCE_LABEL[src]}] {j.get('title', '')[:52]:54} | {j.get('company', '')[:24]}")
                print(f"      {j.get('url', '')}")
        print(f"\n要真的寫入: python3 {os.path.basename(__file__)} --apply")
        return 0

    print("\n=== APPLY ===")
    url = M.SG_RAW_URL
    for src, items in sorted(by_source.items()):
        res = M.push_to_sheet(
            items,
            url,
            sa_key_path=M.SHEET_SA_KEY,
            source=SOURCE_LABEL[src],
            gid=M.SG_RAW_GID,
            location="Singapore",
            timeout_s=300,
        )
        print(f"  {SOURCE_LABEL[src]}: {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
