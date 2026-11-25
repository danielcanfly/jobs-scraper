"""驗證 China-Raw 寫入結果 (只讀)。

用法: python verify_china_sheet.py [baseline_rows]
  baseline_rows: 跑之前的筆數 (預設 305), 用來算新增幾列
"""

import os
import sys
from collections import Counter
from pathlib import Path

REPO = Path(os.environ.get("JOBS_SCRAPER_DIR", str(Path.home() / ".minimax" / "plugins" / "jobs-scraper")))
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

import os  # noqa: E402

import gspread  # noqa: E402
from google.oauth2.service_account import Credentials  # noqa: E402

BASELINE = int(sys.argv[1]) if len(sys.argv) > 1 else 0
CHINA_GID = 488353479

sid = os.environ["SHEET_ID"]
sa = os.environ["GSPREAD_SA_KEY_PATH"]
if not os.path.isabs(sa):
    sa = str(REPO / sa)
creds = Credentials.from_service_account_file(sa, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
gc = gspread.authorize(creds)
ws = gc.open_by_key(sid).get_worksheet_by_id(CHINA_GID)

rows = ws.get_all_values()
data = [r for r in rows[1:] if any(c.strip() for c in r)]
new = data[BASELINE:]

print(f"China-Raw 現況: 總資料列 {len(data)} (基準 {BASELINE} → 新增 {len(new)})")

if not new:
    print("沒有新增列。")
    raise SystemExit(0)

print("\n--- 新增列: D 欄 source ---")
for k, v in Counter(r[3] if len(r) > 3 else "" for r in new).most_common():
    print(f"  {k!r}: {v}")

print("\n--- 新增列: I 欄 location ---")
for k, v in Counter(r[8] if len(r) > 8 else "" for r in new).most_common():
    print(f"  {k!r}: {v}")

print("\n--- 新增列: J 欄 work mode ---")
for k, v in Counter(r[9] if len(r) > 9 else "" for r in new).most_common():
    print(f"  {k!r}: {v}")

visa_nonempty = [(i, r[10]) for i, r in enumerate(new) if len(r) > 10 and r[10].strip()]
print(f"\n--- 新增列: K 欄簽證訊號 (中國應全空) --- 非空 {len(visa_nonempty)} 筆 {visa_nonempty[:5]}")

no_jd = [i for i, r in enumerate(new) if len(r) < 8 or not r[7].strip()]
print(f"--- 新增列: H 欄 JD 為空 --- {len(no_jd)} 筆")

keys = [(r[3] if len(r) > 3 else "", r[4] if len(r) > 4 else "") for r in new]
dup = [k for k, c in Counter(keys).items() if c > 1]
print(f"--- 新增列: (source, job_id) 重複 --- {len(dup)} 組 {dup[:5]}")

print("\n--- 前 5 列樣本 ---")
for r in new[:5]:
    title = r[6] if len(r) > 6 else ""
    comp = r[5] if len(r) > 5 else ""
    loc = r[8] if len(r) > 8 else ""
    jd_len = len(r[7]) if len(r) > 7 else 0
    print(f"  {comp[:28]:28} | {title[:38]:38} | {loc[:30]:30} | JD {jd_len} chars")
