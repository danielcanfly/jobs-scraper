#!/bin/bash
# 用 launchd 啟動中國職缺 run → 不受 session / bash tool 時限影響, 可跑 2-3 小時。
#
# 用法: launch_china_run.sh [range]   (預設 7d)
#
# 做完之後:
#   看進度 → tail -f ${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}/cn_all_<range>.log
#   看單城 → tail -f .../cn_shanghai_<range>.log
#   驗收   → .venv/bin/python .../verify_china_sheet.py
#   手動收 → launchctl remove com.mavis.cn<range>

set -u

RANGE="${1:-7d}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$RUNS"
JOB="com.mavis.cn${RANGE%d}"

# 已經在跑就不重複開
# 注意: 不能用 `launchctl list | grep "$JOB"` → label 有前綴關係時會匹配到自己
# (例 com.mavis.cn7fix 包含 com.mavis.cn7) → 誤判成「已經在跑」而拒絕啟動。
# 用精確 label 查詢。
if launchctl list "$JOB" >/dev/null 2>&1; then
    echo "⚠️  $JOB 已經在跑了, 不重複啟動"
    launchctl list "$JOB"
    exit 1
fi

# 先清掉舊的 state, 避免以為上一輪做過的塊已完成
for CITY in shanghai hangzhou shenzhen; do
    STATE="$RUNS/cn_${CITY}_${RANGE}_chunk_state.txt"
    if [ -f "$STATE" ]; then
        mv "$STATE" "$STATE.bak-$(date '+%Y%m%d_%H%M%S')"
        echo "舊 state 已備份: $STATE.bak-*"
    fi
done

launchctl submit -l "$JOB" -- /bin/bash "$SCRIPT_DIR/run_china_all.sh" "$RANGE"
echo "✅ 已啟動: label=$JOB range=$RANGE"
launchctl list | grep "$JOB"
