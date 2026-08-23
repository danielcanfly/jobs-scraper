"""
jobs-scraper MCP server

Provides 3 tools for SG job scraping and Google Sheet sync:
  - crawl_jobs(source, range, with_jd, to_sheet): 跑爬蟲 + 寫到 sheet
  - audit_sheet(): 跑 dedup / visa / work mode 檢查 (讀現有 sheet)
  - get_stats(): 看 sheet 跟 seen file 統計

這個 server 給 Codex / Claude Code / Cursor / Cline 等 MCP 工具用.
Mavis 本身用 skills/ 下的 SKILL.md (見 ~/.minimax/plugins/jobs-scraper/skills/).

啟動方式:
  - Mavis Plugin: 自動 spawn (見 .minimax-plugin/plugin.json)
  - Codex:       設定 ~/.codex/config.toml 加 [mcp_servers.jobs-scraper] 區塊
  - Claude Code: claude mcp add jobs-scraper -- python /path/to/server.py
  - Cursor:      在 ~/.cursor/mcp.json 加同樣結構

所有 tool 都 wrap 底層的 sg_product_jobs.py + gspread, 不用 LLM token 分析.
"""
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# 確保 ./sg_product_jobs.py 可 import
PLUGIN_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PLUGIN_DIR))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("❌ 沒裝 mcp. 跑: pip install 'mcp>=1.0,<2.0'", file=sys.stderr)
    sys.exit(1)

import sg_product_jobs as M  # noqa: E402

# 確保 GSPREAD_SA_KEY_PATH 是絕對路徑 (不管 CWD 是哪都能找到)
# 預設值 ".secrets/gsheet-sa.json" 是相對路徑, 從 plugin dir 解析
if not Path(M.SHEET_SA_KEY).is_absolute():
    M.SHEET_SA_KEY = str(PLUGIN_DIR / M.SHEET_SA_KEY)

mcp = FastMCP("jobs-scraper")


def _run_cli(args: list[str], timeout: int = 3600) -> str:
    """跑 sg_product_jobs.py 子進程, 收集輸出."""
    cmd = [sys.executable, str(PLUGIN_DIR / "sg_product_jobs.py")] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(PLUGIN_DIR),
        )
    except subprocess.TimeoutExpired:
        return f"❌ 執行超時 ({timeout}s)\n  指令: {' '.join(cmd)}"
    out = result.stdout[-5000:] if result.stdout else ""
    err = result.stderr[-2000:] if result.stderr else ""
    return (
        f"exit_code: {result.returncode}\n"
        f"--- stdout (last 5000 chars) ---\n{out}\n"
        f"--- stderr (last 2000 chars) ---\n{err}\n"
    )


def _read_sheet() -> list[list[str]]:
    """讀 sheet 全部 data rows (扣 header)."""
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(
        M.SHEET_SA_KEY, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    ws = gc.open_by_url(M.SG_RAW_URL).get_worksheet_by_id(M.SG_RAW_GID)
    return ws.get_all_values()[1:]


@mcp.tool()
def crawl_jobs(
    source: str = "linkedin",
    range: str = "7d",
    with_jd: bool = False,
    to_sheet: str = "",
) -> str:
    """
    跑 SG 職缺爬蟲, 選 source + time range, 可選抓 JD 跟寫到 Google Sheet.

    Args:
        source: linkedin | jora | jobstreet (default: linkedin)
        range:  1h | 24h | 3d | 7d | 14d | 21d | 30d (default: 7d)
        with_jd: True 抓 JD 全文 (慢, 50-100 分鐘); False 只抓 list (快, 30 秒)
        to_sheet: Google Sheet URL (含 gid). 空字串 = 不寫 sheet, 只 print 到 stdout.

    Returns: 跑完的 summary (exit code, 最後 stdout, stderr).
    """
    args = [range, "--source", source]
    if with_jd:
        args.append("--with-jd")
    if to_sheet:
        args.extend(["--to-sheet", to_sheet])
    return _run_cli(args)


@mcp.tool()
def audit_sheet() -> str:
    """
    對現有 Google Sheet 跑 5 種健全度檢查 (不重新爬, 直接讀 sheet 分析).

    檢查項目:
      1. (source, job_id) tuple 有沒有重複
      2. E 欄 URL 有沒有重複
      3. Cross-source 數字 ID 碰撞 (LinkedIn vs JobStreet)
      4. 同 (src, jid) 但 title/company 有沒有不一致
      5. Sheet 跟 seen_jds.jsonl 一致性
      6. Work mode 分布
      7. Visa HARD/SOFT 計數

    Returns: audit 報告 (純文字, 給 LLM 讀).
    """
    try:
        rows = _read_sheet()
    except Exception as e:
        return f"❌ 讀 sheet 失敗: {type(e).__name__}: {e}"

    lines = []
    lines.append(f"=== SG-Raw Audit (讀 {len(rows)} 列) ===\n")

    # 1. (source, job_id) tuple 重複
    keys = []
    no_key = 0
    for r in rows:
        k = M.parse_sheet_row_to_key(r)
        if k:
            keys.append(k)
        else:
            no_key += 1
    key_counts = Counter(keys)
    dups = {k: v for k, v in key_counts.items() if v > 1}
    lines.append(f"1. (source, job_id) tuple 重複: {len(dups)} (應為 0)")
    for k, v in list(dups.items())[:5]:
        lines.append(f"   ❌ {k}: {v} 次")

    # 2. E 欄 URL 重複
    url_counts = Counter(r[4].strip() for r in rows if len(r) > 4 and r[4].strip())
    url_dups = {k: v for k, v in url_counts.items() if v > 1}
    lines.append(f"\n2. E 欄 URL 重複: {len(url_dups)} (應為 0)")

    # 3. Cross-source 數字 ID 碰撞
    li_ids = {jid for (s, jid) in keys if s == "linkedin" and jid.isdigit()}
    js_ids = {jid for (s, jid) in keys if s == "jobstreet" and jid.isdigit()}
    collisions = li_ids & js_ids
    lines.append(f"\n3. LinkedIn vs JobStreet 數字 ID 碰撞: {len(collisions)} (統計罕見)")

    # 4. 同 (src, jid) 但 title/company 不一致
    key_to_meta = {}
    for r in rows:
        k = M.parse_sheet_row_to_key(r)
        if k:
            key_to_meta.setdefault(k, set()).add((r[5][:30] if len(r) > 5 else "", r[6][:50] if len(r) > 6 else ""))
    mismatches = {k: v for k, v in key_to_meta.items() if len(v) > 1}
    lines.append(f"\n4. 同 (src, jid) 但 title/company 不一致: {len(mismatches)} (應為 0)")

    # 5. Sheet 跟 seen 一致性
    try:
        seen_path = PLUGIN_DIR / "seen_jds.jsonl"
        if not seen_path.exists():
            lines.append(f"\n5. seen_jds.jsonl: ⚠️ 不存在於 {seen_path} (Plugin 內, 通常在 sg_product_jobs.py 跑的目錄)")
        else:
            seen = M.load_seen_ids(seen_path)
            sheet_keys = set(keys)
            in_sheet_not_seen = sheet_keys - seen
            lines.append(f"\n5. Sheet 跟 seen_jds.jsonl 一致性: sheet 內 {len(sheet_keys)}, seen 內 {len(seen)}, sheet 沒在 seen: {len(in_sheet_not_seen)} (應為 0)")
    except Exception as e:
        lines.append(f"\n5. seen_jds.jsonl 檢查: ⚠️ {e}")

    # 6. Work mode 分布
    wm_counter = Counter(r[9] for r in rows if len(r) > 9)
    lines.append(f"\n6. Work mode 分布:")
    for k, v in wm_counter.most_common():
        lines.append(f"   {k or '(空)':10}: {v}")

    # 7. Visa HARD/SOFT
    hard = sum(1 for r in rows if len(r) > 10 and r[10].startswith("⚠️ HARD"))
    soft = sum(1 for r in rows if len(r) > 10 and r[10] and not r[10].startswith("⚠️ HARD"))
    lines.append(f"\n7. Visa 統計: HARD={hard}, SOFT/POSITIVE={soft}")

    # Source 分布
    src_counter = Counter(r[3] for r in rows if len(r) > 3)
    lines.append(f"\n[Source 分布]")
    for k, v in src_counter.most_common():
        lines.append(f"   {k:22}: {v}")

    return "\n".join(lines)


@mcp.tool()
def get_stats() -> str:
    """
    看 Google Sheet 統計 + seen_jds.jsonl 數量.

    Returns: 來源分布, total rows, seen file size 等 (純文字, 給 LLM 讀).
    """
    try:
        rows = _read_sheet()
    except Exception as e:
        return f"❌ 讀 sheet 失敗: {type(e).__name__}: {e}"

    lines = []
    lines.append(f"=== Sheet Stats ({len(rows)} data rows) ===\n")

    # Source 分布
    src_counter = Counter(r[3] for r in rows if len(r) > 3)
    lines.append("[Source 分布]")
    for k, v in src_counter.most_common():
        lines.append(f"  {k:22}: {v}")

    # Work mode
    wm_counter = Counter(r[9] for r in rows if len(r) > 9)
    lines.append(f"\n[Work Mode 分布]")
    for k, v in wm_counter.most_common():
        lines.append(f"  {k or '(empty)':10}: {v}")

    # Date 分布
    date_counter = Counter(r[2] for r in rows if len(r) > 2 and r[2])
    lines.append(f"\n[Date 分布 (top 10)]")
    for k, v in date_counter.most_common(10):
        lines.append(f"  {k:12}: {v}")

    # seen_jds.jsonl
    seen_path = PLUGIN_DIR / "seen_jds.jsonl"
    if seen_path.exists():
        seen = M.load_seen_ids(seen_path)
        lines.append(f"\n[seen_jds.jsonl]")
        lines.append(f"  unique (source, job_id): {len(seen)}")
        src_seen = Counter(s for s, _ in seen)
        for k, v in src_seen.most_common():
            lines.append(f"  {k:10}: {v}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
