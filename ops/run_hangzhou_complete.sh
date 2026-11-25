#!/bin/bash
# 杭州 14d 補跑到「真的抓滿」— 2026-11-22
#
# 為什麼需要這支:
#   杭州的 geoId 會被 LinkedIn 限流。2026-11-21 的 14d run 三個塊都「成功」了
#   (exit 0、有寫入、沒有 listFAIL), 但最後一塊只抓到 7 頁就停 —
#   因為空頁被當成「到底了」, crawl 判定結果用完就結束。
#   → 舊的 state 機制只看 exit code / listFAIL, 看不出「覆蓋率太薄」,
#     state 被標記成完成 → 直接重跑會全部跳過。
#
# 這支做的事:
#   1. 清掉杭州 14d 的 state (三塊都要重跑)
#   2. 每一塊都檢查「實際抓到幾頁」; 沒抓到 max_pages 就算覆蓋率不足,
#      降溫等待後重試 (最多 4 次), 而不是假裝完成
#   3. list 節奏放慢 (CN_LIST_SLEEP_*) — 限流是被請求速度觸發的
#   4. 收尾做一次 China-Raw 驗收
#
# 用法: run_hangzhou_complete.sh [range]

set -u

RANGE="${1:-14d}"
PLUGIN="${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$RUNS"
LOG="$RUNS/cn_hangzhou_complete_${RANGE}.log"
STATE="$RUNS/cn_hangzhou_${RANGE}_chunk_state.txt"
TMPLOG="$RUNS/cn_hangzhou_complete_${RANGE}_attempt.log"
JOB="com.mavis.cnhz"
CHINA_GID=488353479
SHEET_ID="${SHEET_ID:?請設定 SHEET_ID 環境變數 (fail-closed: 沒有就不跑)}"
URL="https://docs.google.com/spreadsheets/d/${SHEET_ID}/edit?gid=${CHINA_GID}#gid=${CHINA_GID}"

cd "$PLUGIN" || exit 1

export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:12000}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:12000}"
unset CONTROL_PLANE_HTTP_PROXY
# 放慢 list 節奏: 限流是被請求速度觸發的
export CN_LIST_SLEEP_MIN="${CN_LIST_SLEEP_MIN:-18}"
export CN_LIST_SLEEP_MAX="${CN_LIST_SLEEP_MAX:-38}"
export CN_SLEEP_MIN="${CN_SLEEP_MIN:-7}"
export CN_SLEEP_MAX="${CN_SLEEP_MAX:-16}"

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG" 2>&1; }

mem_free_mb() { vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/[.]/,"",$3); print int($3*16384/1048576)}'; }
swap_used_mb() { sysctl -n vm.swapusage 2>/dev/null | sed 's/.*used = \([0-9]*\).*/\1/'; }

log ""
log "=== HANGZHOU COMPLETE START range=$RANGE ==="

# 1) state 清掉 (三塊都要重跑); 舊的搬去備份
if [ -f "$STATE" ]; then
    mv "$STATE" "$STATE.bak-$(date '+%Y%m%d_%H%M%S')"
    log "  舊 state 已備份"
fi
: > "$STATE"

# 2) 從引擎讀 max pages 再切成 3 個累計塊
_split_py='
import sys
def split(m):
    if m <= 3:
        return [m]
    step = -(-m // 3)
    return list(range(step, m, step)) + [m]
print(" ".join(map(str, split(int(sys.argv[1])))))
'
MAXP=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.TIME_RANGES['$RANGE'][1])")
CHUNKS=$(.venv/bin/python -c "$_split_py" "$MAXP")
log "chunks=[$CHUNKS] max_pages=$MAXP list_sleep=${CN_LIST_SLEEP_MIN}-${CN_LIST_SLEEP_MAX}s"

THIN=""
for MP in $CHUNKS; do
    attempt=0
    while true; do
        attempt=$((attempt + 1))
        log "--- CHUNK Hangzhou max-pages=$MP attempt=$attempt 開始 ---"

        .venv/bin/python -u "$SCRIPT_DIR/china_run_wrapper.py" "$RANGE" --source linkedin \
            --location Hangzhou --with-jd --max-pages "$MP" \
            --to-sheet "$URL" --gid "$CHINA_GID" > "$TMPLOG" 2>&1
        rc=$?

        pages=$(grep -c "\[list page " "$TMPLOG")
        wrote=$(grep -oE "'written': [0-9]+" "$TMPLOG" | tail -1 | grep -oE "[0-9]+" | tail -1)
        wrote=${wrote:-0}
        dup=$(grep -oE "'skipped_dup': [0-9]+" "$TMPLOG" | tail -1 | grep -oE "[0-9]+" | tail -1)
        dup=${dup:-0}
        listfail=$(grep -c "FAIL: " "$TMPLOG")
        jdfail=$(grep -oE "failed=[0-9]+" "$TMPLOG" | tail -1 | grep -oE "[0-9]+" | tail -1)
        jdfail=${jdfail:-0}

        log "CHUNK $MP attempt=$attempt EXIT=$rc pages=$pages/$MP wrote=$wrote dup=$dup listFAIL=$listfail jdfailed=$jdfail mem_free=$(mem_free_mb)MB swap=$(swap_used_mb)MB"

        # 覆蓋率判定: 這一塊必須真的抓到 MP 頁, 否則就是被限流截斷
        if [ "$rc" -eq 0 ] && [ "$listfail" -eq 0 ] && [ "$pages" -ge "$MP" ]; then
            if [ -f "hangzhou_product_jobs_${RANGE}_jd.json" ]; then
                cp "hangzhou_product_jobs_${RANGE}_jd.json" "hangzhou_product_jobs_${RANGE}chunk${MP}_jd.json"
            fi
            echo "linkedin:$MP" >> "$STATE"
            log "  ✓ chunk $MP 抓滿 $pages 頁, 標記完成"
            break
        fi

        if [ "$attempt" -ge 4 ]; then
            log "--- chunk $MP 連試 4 次仍未抓滿 (pages=$pages/$MP), 不標記完成 → 下次會再補 ---"
            THIN="$THIN $MP"
            break
        fi

        wait_s=$((420 * attempt))
        log "--- chunk $MP 覆蓋率不足 (pages=$pages/$MP), 降溫 ${wait_s}s 後重試 ---"
        sleep "$wait_s"
    done
done

log ""
if [ -n "$THIN" ]; then
    log "=== HANGZHOU COMPLETE DONE, 仍有覆蓋率不足的塊:$THIN (state 未記錄 → 下次自動補) ==="
else
    log "=== HANGZHOU COMPLETE DONE, 三塊都抓滿 ==="
fi

"$PLUGIN/.venv/bin/python" "$SCRIPT_DIR/verify_china_sheet.py" 510 >> "$LOG" 2>&1

launchctl remove "$JOB" 2>/dev/null
exit 0
