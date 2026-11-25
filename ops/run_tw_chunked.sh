#!/bin/bash
# TW (104.com.tw) scraper — keyword 軸 chunked supervisor
#
# 用法: run_tw_chunked.sh <range> [wait_for_job_label]
#   range: 1h | 24h | 3d | 7d | 14d | 21d | 30d
#   wait_for_job_label: 可選。給了就先等那個 launchd job 消失再開始
#                       (避免兩個 run 同時搶 Sheet next_row / seen_jds.jsonl)
#
# 為什麼需要專用 runner (2026-11-24):
#   1. 之前只有 SG 的 supervisor, TW 沒有 → 104 source 從沒被 chunked 跑過。
#   2. 104 的 list 是「多個 keyword × max_pages」(pagesize=20, engine 預設
#      7d=15 / 14d=30 / 30d=50 頁), 一個 chunk 若包所有 keyword, 邊際 JD
#      工作量 = 全部 keyword × 頁數 → 一塊可以長到好幾小時, 被殺就全毀
#      (寫入發生在塊的最後)。
#      → 走 keyword 軸 (ONEZEROFOUR_KEYWORDS env 覆寫, 跟 JobStreet 同設計):
#        每個 process 只爬一個 keyword 的前 N 頁, 每塊的邊際量 = N 頁 × 20 筆。
#   3. TW-Raw 只有 137 列 → pre-dedup 幾乎擋不掉東西 → 每塊的 JD 量 ≈ 頁數 × 20。
#      v1.8.0 之後 (104 節奏 1.0-2.0s + 抓 JD 3 threads 平行 + 區間式切塊):
#      7d 一塊 5-10 頁 ≈ 100-200 筆 ≈ 3 分; 14d ≈ 4 分; 30d ≈ 6 分
#      → 都遠低於本機 ~31-41 分的被殺門檻。
#
# 每塊跑完立刻寫 Sheet → 進度落地, 被殺也不會整段白跑。
# 下一塊的 pre-dedup 會讀 TW-Raw 擋掉已寫入的職缺 → 不會重抓 JD。

set -uo pipefail

cd "${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}" || exit 1

# 這台機: Google Sheets API 直連會 timeout → 一律走本地 proxy。
# launchctl submit 的 job 不一定繼承 submitting shell 的 env → 這裡顯式補上。
export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:12000}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:12000}"
unset CONTROL_PLANE_HTTP_PROXY

RANGE="${1:-7d}"
WAIT_FOR="${2:-}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
mkdir -p "$RUNS"
RANGE_TAG="${RANGE%d}"
PREFIX="tw${RANGE_TAG}"
LOG="$RUNS/$PREFIX.log"
STATE="$RUNS/${PREFIX}_chunk_state.txt"
TMPLOG="$RUNS/${PREFIX}_chunk_attempt.log"
JOB="com.mavis.${PREFIX}"

# 每個 keyword 的切塊頁區間 (v1.8.0: 區間式, 不是累計式)。
#
# 舊版是「累計式」: 第 N 塊爬第 1..N 頁 → 前面每頁每跑一塊就重爬一遍
# (7d 三塊 = 5+10+15 = 30 次 page fetch 換 15 頁的池子 = 2× 重複)。
# 改成區間式後每頁只抓一次; 跨塊去重靠 seen_jds.jsonl + sheet pre-dedup。
#
# 最後一段刻意留 headroom (比引擎預設的頁數上限多): 池子會長。
# 104 的 list API 沒有軟停 → 跨過池底的頁回空資料, 該塊記成「pool 到底」。
#
# ── 2026-11-24 重新量測池深, 舊 STEPS 嚴重不足 ─────────────────────────────────
# 實測 (直接打 104 list API 的 metadata.pagination):
#   - total 三個 range 都是 1001 → 那是 104 的「顯示上限」, 不是真實筆數
#   - lastPage: English keyword 150 / 中文「產品經理」7d 只有 110
#   - 實測 page 200 還有資料, page 150 對「產品經理」是空 (池底)
#   → 104 的搜尋 (mode=s, 模糊匹配) 沒有天然池底, 深度是「預算」不是「池深」
#   - 標題預篩通過率: page 1 = 95%, page 25 = 50%, page 200 = 40% (深頁多低相關性)
# 舊的 7d STEPS 只到 20 頁 → 只覆蓋 ~13% 的池子, 是靜默截斷不是「跑完了」。
# Daniel 2026-11-24 決定: 7d 抓 50 頁/keyword (450 頁, ~50-70 分鐘),
# 先量真實的時間/通過率/列數, 再決定 14d/30d 要多深。
# 之後要加深只要追加區間 (state 會接著跑)。
case "$RANGE" in
7d)  STEPS="1-25,26-50";;
14d) STEPS="1-25,26-50";;
30d) STEPS="1-25,26-50";;
*)
    echo "STEPS 尚未定義 range=$RANGE (已知: 7d, 14d, 30d)" >&2
    exit 2
    ;;
esac

# keyword 清單從引擎讀 (single source of truth), 不要在這裡另外硬寫一份。
KW_LIST=$(.venv/bin/python -c "import sg_product_jobs as M; print('\n'.join(M.ONEZEROFOUR_KEYWORDS))")

# 切塊計畫: "keyword|pages" 以空白分隔
PLAN=""
while IFS= read -r kw; do
    [ -z "$kw" ] && continue
    PLAN="$PLAN$kw|$STEPS
"
done <<< "$KW_LIST"

# TW-Raw 的 sheet 目標 (同一張試算表, 不同 tab)
URL=$(.venv/bin/python -c "import sg_product_jobs as M; print(f'https://docs.google.com/spreadsheets/d/{M.SG_RAW_SHEET_ID}/edit?gid={M.ONEZEROFOUR_TW_RAW_GID}')")

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG" 2>&1; }

# ── TW 暫停開關 (2026-11-24) ────────────────────────────────────────────────
# 內容含 "paused" → 這個 range 直接跳過 (exit 2 = 暫停, 不是缺口)。
# 內容改成 "run" 或清空 → 恢復正常執行。
# 用法: echo paused > tw_paused.flag / echo run > tw_paused.flag
# 為什麼用「內容」而不是「檔案存在」: rm 會被權限閘擋, 改內容比較安全。
PAUSE_FLAG="$RUNS/tw_paused.flag"
if [ -f "$PAUSE_FLAG" ] && grep -q "paused" "$PAUSE_FLAG" 2>/dev/null; then
    log "=== TW 階段暫停 ($PAUSE_FLAG 含 'paused') → exit 2 ==="
    log "=== 2026-11-24 Daniel 指示: 先讓 sg 30d 跑完 + 修缺陷 (sleep/切塊), TW 暫不跑 ==="
    exit 2
fi

# 記憶體壓力觀察: 這台機 8GB RAM, swap 常年 10GB+, jetsam 會殺行程
mem_free_mb() { vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/[.]/,"",$3); print int($3*16384/1048576)}'; }
swap_used_mb() { sysctl -n vm.swapusage 2>/dev/null | sed 's/.*used = \([0-9]*\).*/\1/'; }

log "塊設定: range=$RANGE job=$JOB steps=$STEPS"
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
    while IFS='|' read -r kw pages; do
        [ -z "$kw" ] && continue
        IFS=',' read -r -a plist <<< "$pages"
        for mp in "${plist[@]}"; do
            [ -f "$STATE" ] && grep -qx "104:$kw:$mp" "$STATE" || return 1
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

while IFS='|' read -r kw pages; do
    [ -z "$kw" ] && continue
    IFS=',' read -r -a plist <<< "$pages"
    for MP in "${plist[@]}"; do
        START="${MP%%-*}"
        END="${MP##*-}"
        KEY="104:$kw:$MP"
        if [ -f "$STATE" ] && grep -qx "$KEY" "$STATE"; then
            log "--- $KEY 已完成, 跳過 ---"
            continue
        fi

        attempt=0
        while true; do
            attempt=$((attempt + 1))
            log "--- CHUNK $KEY (pages $START..$END) attempt=$attempt 開始 ---"

            # background 跑 + 採樣峰值 RSS: 被殺時才知道是記憶體被 jetsam 挑走還是真的 hang
            ONEZEROFOUR_KEYWORDS="$kw" .venv/bin/python -u sg_product_jobs.py "$RANGE" \
                --source onezerofour --with-jd \
                --start-page "$START" --max-pages "$END" --to-sheet "$URL" > "$TMPLOG" 2>&1 &
            CHILD=$!
            PEAK_KB=0
            while kill -0 "$CHILD" 2>/dev/null; do
                R=$(ps -o rss= -p "$CHILD" 2>/dev/null | tr -d ' ')
                if [ -n "$R" ] && [ "$R" -gt "$PEAK_KB" ]; then PEAK_KB=$R; fi
                sleep 5
            done
            wait "$CHILD"; rc=$?
            PEAK_MB=$((PEAK_KB / 1024))

            wrote=$(grep -c "結果: {" "$TMPLOG")
            nodata=$(grep -c "無資料，結束" "$TMPLOG")
            listfail=$(grep -cE "\[104 .*\] FAIL" "$TMPLOG")
            fetched=$(grep -oE "fetch [0-9]+" "$TMPLOG" | tail -1)
            written=$(grep -oE "'written': [0-9]+" "$TMPLOG" | tail -1)
            rows=$(grep -oE "'end_row': [0-9]+" "$TMPLOG" | tail -1)

            log "CHUNK $KEY attempt=$attempt EXIT=$rc wrote=$wrote nodata=$nodata listFAIL=$listfail $fetched $written $rows peak_rss=${PEAK_MB}MB mem_free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

            # 「無資料」= 這個 keyword 在這個深度真的沒職缺了 (pool 挖到底)。
            # 跟「失敗」不同: 失敗會讓引擎 raise → exit != 0。
            # 所以 nodata 算完成, 不能算缺口。
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
