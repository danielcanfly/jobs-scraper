#!/bin/bash
# China city runner — 逐城市抓 LinkedIn 職缺, 寫入 China-Raw (gid 488353479)
#
# 用法: run_china_city.sh <City> [range]
#   City:  Shanghai | Hangzhou | Shenzhen
#   range: 7d (預設) | 3d | 14d ...
#
# 設計:
#  1. 分塊: 7d 的預設 max pages 切成 3 個「累計」塊 (例 5 → 10 → 15),
#     每塊抓完立刻寫入 Sheet → 被殺也保留已寫入的進度, 不整段白跑。
#  2. 跨塊 JD cache: 每塊結束把輸出檔另存成 <prefix>_product_jobs_<range>chunk<N>_jd.json,
#     這個檔名符合 load_jd_cache_from_jsons 的 glob (*_product_jobs_*_jd.json) 且不是
#     當前輸出的檔名 → 下一塊重抓到同一批職缺時命中 cache, 不會重抓 JD。
#  3. 429: JD 抓取由 china_run_wrapper.py 加 30/60/90s 重試階梯;
#     list 頁由 repo 內建的 fetch_list_page retry 處理。
#  4. 連敗 3 次的塊不寫 state → 下次 run 從頭重跑那一塊, 不會靜默少抓。

set -u

CITY="${1:-Shanghai}"
RANGE="${2:-7d}"
PLUGIN="${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$RUNS"
WRAPPER="$SCRIPT_DIR/china_run_wrapper.py"

LOWER=$(printf '%s' "$CITY" | tr '[:upper:]' '[:lower:]')
LOG="$RUNS/cn_${LOWER}_${RANGE}.log"
STATE="$RUNS/cn_${LOWER}_${RANGE}_chunk_state.txt"
TMPLOG="$RUNS/cn_${LOWER}_${RANGE}_chunk_attempt.log"
CHINA_GID=488353479
SHEET_ID="${SHEET_ID:?請設定 SHEET_ID 環境變數 (fail-closed: 沒有就不跑)}"
URL="https://docs.google.com/spreadsheets/d/${SHEET_ID}/edit?gid=${CHINA_GID}#gid=${CHINA_GID}"

cd "$PLUGIN" || exit 1

# 這台機: LinkedIn Guest API 直連回 451, Google Sheets API 直連會 timeout,
# 兩邊都要走本地 proxy (127.0.0.1:12000)。
# .env 裡本來就有這三個值, 但 launchctl 起的行程若哪天換了 env 就不會有 → 這裡顯式補上。
export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:12000}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:12000}"
unset CONTROL_PLANE_HTTP_PROXY

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG" 2>&1; }

mem_free_mb() { vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/[.]/,"",$3); print int($3*16384/1048576)}'; }
swap_used_mb() { sysctl -n vm.swapusage 2>/dev/null | sed 's/.*used = \([0-9]*\).*/\1/'; }

kill_reason() {
  case "$1" in
    137) echo "SIGKILL(9): 被系統殺掉 — 最可能是 jetsam/記憶體壓力";;
    143) echo "SIGTERM(15): 被要求終止";;
    139) echo "SIGSEGV(11): C 層 crash";;
    124) echo "timeout";;
    0)   echo "ok";;
    *)   echo "exit=$1";;
  esac
}

# 從引擎讀該 range 的預設 max pages, 再切成 3 個累計塊
# CN_MAX_PAGES 可覆寫頁數上限 — 用於「range 的預設上限比先前那輪還小」的情況:
#   30d 預設只有 25 頁, 但上海 14d 的池子就已經打滿 30 頁 → 30d 用預設會 0 新增,
#   所以要 CN_MAX_PAGES=70 才真的挖得到 30 天 (上海 30 天約 640 筆 ≈ 64 頁)。
_split_py='
import sys
def split(m):
    if m <= 3:
        return [m]
    step = -(-m // 3)
    return list(range(step, m, step)) + [m]
print(" ".join(map(str, split(int(sys.argv[1])))))
'
DEFAULT_MAXP=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.TIME_RANGES['$RANGE'][1])")
MAXP="${CN_MAX_PAGES:-$DEFAULT_MAXP}"
CHUNKS=$(.venv/bin/python -c "$_split_py" "$MAXP")
PREFIX=$(printf '%s' "$CITY" | tr '[:upper:]' '[:lower:]' | tr -d ' ')
OUT="${PREFIX}_product_jobs_${RANGE}_jd.json"

log ""
log "=== CHINA RUN city=$CITY range=$RANGE chunks=[$CHUNKS] max_pages=$MAXP (engine 預設 $DEFAULT_MAXP) target=China-Raw(gid=$CHINA_GID) ==="
log "記憶體基準: free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

FAILED=""
TOTAL_WRITTEN=0

for MP in $CHUNKS; do
    if [ -f "$STATE" ] && grep -qx "linkedin:$MP" "$STATE"; then
        log "--- chunk max-pages=$MP 已完成, 跳過 ---"
        continue
    fi

    attempt=0
    while true; do
        attempt=$((attempt + 1))
        log "--- CHUNK $CITY max-pages=$MP attempt=$attempt 開始 ---"

        .venv/bin/python -u "$WRAPPER" "$RANGE" --source linkedin \
            --location "$CITY" --with-jd --max-pages "$MP" \
            --to-sheet "$URL" --gid "$CHINA_GID" > "$TMPLOG" 2>&1
        rc=$?

        wrote=$(grep -c "結果: {" "$TMPLOG")
        nodata=$(grep -c "無資料，結束" "$TMPLOG")
        listfail=$(grep -c "FAIL: " "$TMPLOG")
        failed=$(grep -oE "failed=[0-9]+" "$TMPLOG" | tail -1)
        written=$(grep -oE "'written': [0-9]+" "$TMPLOG" | tail -1)
        endrow=$(grep -oE "'end_row': [0-9]+" "$TMPLOG" | tail -1)
        n_written=$(echo "$written" | grep -oE "[0-9]+" | tail -1)
        n_written=${n_written:-0}

        log "CHUNK $CITY $MP attempt=$attempt EXIT=$rc [$(kill_reason "$rc")] wrote=$wrote nodata=$nodata listFAIL=$listfail $failed $written $endrow mem_free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

        # list crawl 中途放棄 (某頁降級/失敗) → coverage 有缺口, 不能算這一塊完成,
        # 不寫 state → 下次重跑會從頭補那一塊。
        if [ "$listfail" -ge 1 ]; then
            log "--- chunk max-pages=$MP list crawl 有 FAIL (coverage 不完整), 不標記完成 ---"
            if [ "$attempt" -lt 3 ]; then
                sleep 60
                continue
            fi
            FAILED="$FAILED $MP"
            break
        fi

        if [ "$rc" -eq 0 ] && [ "$wrote" -ge 1 ] && [ "$nodata" -eq 0 ]; then
            # 跨塊 JD cache: 另存成符合 glob 且非當前輸出名的檔名
            if [ -f "$OUT" ]; then
                cp "$OUT" "${PREFIX}_product_jobs_${RANGE}chunk${MP}_jd.json"
                log "  JD cache 已另存: ${PREFIX}_product_jobs_${RANGE}chunk${MP}_jd.json"
            fi
            TOTAL_WRITTEN=$((TOTAL_WRITTEN + n_written))
            echo "linkedin:$MP" >> "$STATE"
            break
        fi

        if [ "$attempt" -ge 3 ]; then
            log "--- chunk max-pages=$MP 連敗 3 次 (EXIT=$rc [$(kill_reason "$rc")]), 標記未完成 (不寫 state) ---"
            FAILED="$FAILED $MP"
            break
        fi
        log "--- chunk max-pages=$MP 失敗, 20s 後重試 ---"
        sleep 20
    done
done

log "=== $CITY DONE: 本輪寫入 $TOTAL_WRITTEN 列; 未完成塊: ${FAILED:-無} ==="
if [ -n "$FAILED" ]; then
    exit 3
fi
exit 0
