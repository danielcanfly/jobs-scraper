#!/bin/bash
# 接續 supervisor: 等本輪 (com.mavis.cn7) 結束後, 用修好的 wrapper 補跑失敗的塊
#
# 背景: 2026-11-21 14:55 杭州三個塊全部 crash —
#   LinkedIn 在 throttle 狀態下回 HTTP 200 但 body 沒有 job card,
#   原版 parse_list_page 直接 raise → 整個 chunk 中斷。
#   已修 wrapper (china_run_wrapper.py): list page 降級 → 30/60/90s 階梯重試;
#   parse 爆掉 → 當 0 筆, 不讓 chunk 死掉。
#
# 上海三塊已完成 (state 有記錄) → 會被跳過, 不重跑。
# 深圳只補失敗的塊 (state 只記錄成功過的)。

set -u

RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$RUNS"
PLUGIN="${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}"
LOG="$RUNS/cn_fix_7d.log"
JOB="com.mavis.cn7fix"
WAIT_JOB="com.mavis.cn7"

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG" 2>&1; }

log ""
log "=== CN FIX START (等待 $WAIT_JOB 結束) ==="

# 1) 等本輪結束
#    注意: 不能用 `launchctl list | grep "com.mavis.cn7"` → 會匹配到自己的 label
#    (com.mavis.cn7fix 包含 com.mavis.cn7) → 永遠等不到。用精確 label 查詢。
waited=0
while launchctl list "$WAIT_JOB" >/dev/null 2>&1; do
    sleep 30
    waited=$((waited + 30))
    [ $((waited % 300)) -eq 0 ] && log "仍在等 $WAIT_JOB (已等 ${waited}s)"
done
log "=== $WAIT_JOB 已結束 (等 ${waited}s) ==="

# 2) 補跑: 杭州 (全塊) → 深圳 (只補失敗塊)
for CITY in Hangzhou Shenzhen; do
    log "=== 補跑 $CITY ==="
    "$SCRIPT_DIR/run_china_city.sh" "$CITY" "7d"
    rc=$?
    log "=== $CITY 結束 exit=$rc ==="
done

# 3) 驗收
"$PLUGIN/.venv/bin/python" "$SCRIPT_DIR/verify_china_sheet.py" >> "$LOG" 2>&1

log "=== CN FIX DONE ==="
launchctl remove "$JOB" 2>/dev/null
exit 0
