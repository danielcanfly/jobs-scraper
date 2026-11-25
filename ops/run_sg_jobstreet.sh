#!/bin/bash
# SG JobStreet supervisor — 頁面區間式切塊 (v1.8.0)
#
# 用法: run_sg_jobstreet.sh [range] [wait_for_job_label]
#   range: 1h | 24h | 3d | 7d | 14d | 21d | 30d (default 7d)
#
# ── 為什麼改成區間式 (2026-11-24) ────────────────────────────────────────────
# 舊版是「累計式」: 第 N 塊爬第 1..N 頁 → 前面 N-1 頁每跑一塊就重爬一遍。
# 30d 實測: 爬了 2,179 頁, 但池子只需要 ~406 頁 = **5.4× 重複**
#   (product lead 一個 keyword: 1,260 頁 vs 池子 169 頁 = 7.5×)
#
# v1.8.0 改成「區間式」: 第 k 塊只爬第 START..END 頁 → 每頁只抓一次。
# 跨塊的去重本來就有 (seen_jds.jsonl + sheet pre-dedup) → 不會重抓 JD, 也不會漏。
# 引擎端新增 `--start-page` (sg_product_jobs.py) 支援這個模式。
#
# ── 另一個 v1.8.0 變更: sleep 與平行 ─────────────────────────────────────────
#   - JobStreet 的請求節奏降到 0.5-1.0s (舊的 3-10s → wall time 80% 是等待)
#   - 抓 JD 改成 3 個 thread 平行
# → 一塊從 ~13 分降到 ~4 分, 整輪 30d 從 ~8 小時降到 ~1.5 小時。
#
# ── 塊的大小 ──────────────────────────────────────────────────────────────────
# 每塊 ~14-30 個 list 頁。v1.8.0 之後一塊只要 ~3-6 分 (舊節奏要 15-25 分)。
# 寫入發生在塊的最後, 被殺 = 整塊的 JD 成果全丟 → 塊還是要切細
# (這台機 ~31-41 分就會被 jetsam 殺)。
# 塊數別太多: 每塊有 ~1.1 分的固定成本 (process 啟動 + 讀 6 千列 Sheet + 寫入),
# 塊數 × 固定成本 會吃掉省下來的網路時間 → 所以用大一點的區間。
#
# 每塊跑完立刻寫 Sheet → 進度落地, 被殺也不會整段白跑。
# 下一塊的 pre-dedup 會讀 SG-Raw 擋掉已寫入的職缺 → 不會重抓 JD。

set -uo pipefail

cd "${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}" || exit 1

# 這台機: LinkedIn Guest API 直連回 451, Google Sheets API 直連會 timeout,
# 兩邊都要走本地 proxy。launchctl submit 的 job 不一定繼承 submitting shell 的 env
# → 這裡顯式補上。
export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:12000}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:12000}"
unset CONTROL_PLANE_HTTP_PROXY

RANGE="${1:-7d}"
WAIT_FOR="${2:-}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
mkdir -p "$RUNS"
RANGE_TAG="${RANGE%d}"
PREFIX="sg${RANGE_TAG}js"
LOG="$RUNS/$PREFIX.log"
STATE="$RUNS/${PREFIX}_chunk_state.txt"
TMPLOG="$RUNS/${PREFIX}_chunk_attempt.log"
JOB="com.mavis.${PREFIX}"

# 切塊計畫: "keyword|start-end,start-end,..." (區間式, 頁碼 1-based, 含頭含尾)
#
# 區間的頁數上限 = 該 keyword 的池深 / 20 (頁大小 20) + 1 (多那一頁是 pool 到底
# 時回 0 筆的 EOF 頁)。2026-11-23 實測池深 (API totalCount):
#   range | product manager | product director | director of product | head of product | product lead
#   7d    | 520              | 382                | 388                   | 184                | 1098
#   14d   | 929              | 691                | 707                   | 360                | 1900
#   30d   | 1645             | 1199               | 1187                  | 641                | 3369
# (池子每天會長, 所以每個 keyword 的最後一塊比「池深 / 20」多留 1 頁)
case "$RANGE" in
# 區間的最後一頁刻意留了 headroom (比實測池深多 ~15-25 頁):
# 池子每天會長, 舊的累計式切塊靠引擎的頁數上限留餘裕, 區間式沒有那個上限
# → 這裡自己留。跨過池底的頁回空資料 → 該塊記成「pool 到底」, 不算缺口。
7d)
    PLAN="product manager|1-14,15-40
product director|1-14,15-32
director of product|1-14,15-32
head of product|1-20
product lead|1-14,15-28,29-42,43-70"
    ;;
14d)
    PLAN="product manager|1-16,17-32,33-60
product director|1-18,19-45
director of product|1-18,19-45
head of product|1-25
product lead|1-16,17-32,33-48,49-64,65-80,81-110"
    ;;
30d)
    PLAN="product manager|1-28,29-56,57-100
product director|1-30,31-75
director of product|1-30,31-75
head of product|1-40
product lead|1-30,31-60,61-90,91-120,121-150,151-200"
    ;;
*)
    echo "PLAN 尚未定義 range=$RANGE (已知: 7d, 14d, 30d)" >&2
    exit 2
    ;;
esac

URL=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.SG_RAW_URL)")

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG" 2>&1; }

# 記憶體壓力觀察 (2026-11-19): 這台機 8GB RAM, swap 常年 10GB+, jetsam 會殺行程
mem_free_mb() { vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/[.]/,"",$3); print int($3*16384/1048576)}'; }
swap_used_mb() { sysctl -n vm.swapusage 2>/dev/null | sed 's/.*used = \([0-9]*\).*/\1/'; }

log "塊設定: range=$RANGE job=$JOB (區間式切塊)"
log "TARGET: $URL"
log "記憶體基準: free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

# ── 等另一個 supervisor 結束 (避免兩個 run 同時搶 Sheet next_row / seen_jds.jsonl) ──
if [ -n "$WAIT_FOR" ]; then
    log "=== 等待 $WAIT_FOR 結束 ==="
    waited=0
    while launchctl list 2>/dev/null | awk '{print $3}' | grep -qx "$WAIT_FOR"; do
        sleep 30
        waited=$((waited + 30))
        [ $((waited % 300)) -eq 0 ] && log "仍在等 $WAIT_FOR (已等 ${waited}s)"
    done
    log "=== $WAIT_FOR 已結束 (等 ${waited}s) ==="
fi

# ── 所有塊都完成了嗎 ────────────────────────────────────────────────────────
all_done() {
    while IFS='|' read -r kw ranges; do
        [ -z "$kw" ] && continue
        IFS=',' read -r -a rlist <<< "$ranges"
        for r in "${rlist[@]}"; do
            [ -f "$STATE" ] && grep -qx "jobstreet:$kw:$r" "$STATE" || return 1
        done
    done <<< "$PLAN"
}

if all_done; then
    log "所有 chunk 已完成 → 卸載 launchd job"
    launchctl remove "$JOB" 2>/dev/null
    exit 0
fi

log ""
log "=== SUPERVISOR START (pid $$) range=$RANGE job=$JOB ==="

FAILED=""
POOLED=""

while IFS='|' read -r kw ranges; do
    [ -z "$kw" ] && continue
    IFS=',' read -r -a rlist <<< "$ranges"
    for R in "${rlist[@]}"; do
        START="${R%%-*}"
        END="${R##*-}"
        KEY="jobstreet:$kw:$R"
        if [ -f "$STATE" ] && grep -qx "$KEY" "$STATE"; then
            log "--- $KEY 已完成, 跳過 ---"
            continue
        fi

        attempt=0
        while true; do
            attempt=$((attempt + 1))
            log "--- CHUNK $KEY (pages $START..$END) attempt=$attempt 開始 ---"

            # background 跑 + 採樣峰值 RSS: 被殺時才知道是記憶體被 jetsam 挑走還是真的 hang
            JOBSTREET_KEYWORDS="$kw" .venv/bin/python -u sg_product_jobs.py "$RANGE" \
                --source jobstreet --with-jd \
                --start-page "$START" --max-pages "$END" --to-sheet "$URL" > "$TMPLOG" 2>&1 &
            CHILD=$!
            PEAK_KB=0
            while kill -0 "$CHILD" 2>/dev/null; do
                R2=$(ps -o rss= -p "$CHILD" 2>/dev/null | tr -d ' ')
                if [ -n "$R2" ] && [ "$R2" -gt "$PEAK_KB" ]; then PEAK_KB=$R2; fi
                sleep 5
            done
            wait "$CHILD"; rc=$?
            PEAK_MB=$((PEAK_KB / 1024))

            wrote=$(grep -c "結果: {" "$TMPLOG")
            nodata=$(grep -c "無資料，結束" "$TMPLOG")
            listfail=$(grep -cE "\[jobstreet .*\] FAIL" "$TMPLOG")
            fetched=$(grep -oE "fetch [0-9]+" "$TMPLOG" | tail -1)
            written=$(grep -oE "'written': [0-9]+" "$TMPLOG" | tail -1)
            rows=$(grep -oE "'end_row': [0-9]+" "$TMPLOG" | tail -1)

            log "CHUNK $KEY attempt=$attempt EXIT=$rc wrote=$wrote nodata=$nodata listFAIL=$listfail $fetched $written $rows peak_rss=${PEAK_MB}MB mem_free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

            # 「無資料」= 這個區間的頁已經在池子之外 (pool 到底) → 算完成, 不是缺口。
            # 區間式切塊一定會有這種塊: 最後一塊常常跨過池底。
            if [ "$nodata" -ge 1 ] && [ "$rc" -eq 0 ]; then
                log "--- $KEY pool 到底 (無資料) → 標記完成 ---"
                echo "$KEY" >> "$STATE"
                POOLED="$POOLED $KEY"
                break
            fi

            if [ "$rc" -eq 0 ] && [ "$wrote" -ge 1 ]; then
                if [ "$listfail" -ge 1 ] && [ "$attempt" -lt 3 ]; then
                    log "--- $KEY list 有 FAIL (coverage 可能不完整), 重試 ---"
                    sleep 20
                    continue
                fi
                echo "$KEY" >> "$STATE"
                break
            fi

            if [ "$attempt" -ge 3 ]; then
                log "--- $KEY 連敗 3 次 (EXIT=$rc), 標記為未完成 (不寫 state) ---"
                FAILED="$FAILED $KEY"
                break
            fi
            log "--- $KEY 失敗 (EXIT=$rc), 20s 後重試 ---"
            sleep 20
        done
    done
done <<< "$PLAN"

log "=== SUPERVISOR DONE (range=$RANGE) ==="
log "SEEN: $(wc -l < seen_jds.jsonl) 筆 (after)"
log "記憶體結束狀態: free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

if [ -n "$FAILED" ]; then
    log "⚠️⚠️ 有未完成的塊:$FAILED"
    log "⚠️⚠️ 這些塊沒有寫進 state → 下次 run 會從頭重跑, 不要把這輪當成完整 coverage"
else
    log "所有塊都完成 (state 已記錄)"
fi
[ -n "$POOLED" ] && log "以下塊是 pool 到底 (不是缺口):$POOLED"

launchctl remove "$JOB" 2>/dev/null
log "已卸載 launchd job"

# 有未完成塊 → exit 3, 讓呼叫端分辨「跑完了但有缺口」跟「完整跑完」
[ -n "$FAILED" ] && exit 3
exit 0
