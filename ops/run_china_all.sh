#!/bin/bash
# 三城市依序跑完 → 每個城市一塊一塊寫入 China-Raw
#
# 用法: run_china_all.sh [range]
#
# 為什麼循序跑三個城市而不是並行:
#   LinkedIn Guest API 在這台機的出口 IP 會回 429, 並行只會讓 rate limit 更嚴重。
#   7d 預設 15 頁, 切成 3 個累計塊 (5/10/15), 每塊寫完就落地。

set -u

RANGE="${1:-7d}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$RUNS"
PLUGIN="${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}"
LOG="$RUNS/cn_all_${RANGE}.log"
CITIES="Shanghai Hangzhou Shenzhen"
# launchd label: 跟 launcher 用同一個規則推導, 不要手動拼
JOB="com.mavis.cn${RANGE%d}"

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG" 2>&1; }

log ""
log "=== CHINA ALL START range=$RANGE cities=[$CITIES] ==="

# 30d 的引擎預設 max pages 只有 25, 比 14d 用過的 30 還少 → 上海 14d 的池子就已經
# 打滿 30 頁 (300 筆), 30d 用預設只會重抓同一批 → 0 新增。
# 改成 70 頁: 上海 30 天約 640 筆 ≈ 64 頁, 這樣三城才真的挖得到 30 天。
if [ "$RANGE" = "30d" ]; then
    export CN_MAX_PAGES="${CN_MAX_PAGES:-70}"
    log "  30d 覆寫 max pages → $CN_MAX_PAGES (引擎預設 25)"
fi

FAILED=""
for CITY in $CITIES; do
    log "=== 開始 $CITY ==="
    "$SCRIPT_DIR/run_china_city.sh" "$CITY" "$RANGE"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        log "!!! $CITY 未完整完成 (exit=$rc)"
        FAILED="$FAILED $CITY"
    else
        log "=== $CITY 完成 ==="
    fi
done

# 收尾: 驗證 China-Raw (只讀), 然後卸載 launchd job
"$PLUGIN/.venv/bin/python" "$SCRIPT_DIR/verify_china_sheet.py" >> "$LOG" 2>&1

log ""
if [ -n "$FAILED" ]; then
    log "=== CHINA ALL DONE 但有缺口:$FAILED (state 沒記 → 下次重跑會補) ==="
    launchctl remove "$JOB" 2>/dev/null
    exit 3
fi
log "=== CHINA ALL DONE (三城市皆完整) ==="
launchctl remove "$JOB" 2>/dev/null
exit 0
