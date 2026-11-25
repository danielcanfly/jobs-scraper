#!/bin/bash
# SG scraper — generic chunked supervisor (頁面區間式切塊, v1.8.0)
#
# 用法: run_sg_chunked.sh <range> [wait_for_job_label]
#   range: 1h | 24h | 3d | 7d | 14d | 21d | 30d
#   wait_for_job_label: 可選。若給了, 會先等那個 launchd job 消失再開始
#                       (避免兩個 run 同時搶 Sheet next_row / seen_jds.jsonl)
#
# 設計依據 (2026-10-27 / 10-30 實戰):
#  1. 這台機器會用 signal 殺掉長跑的 python (實測 ~31 分 / ~41 分) → 切塊,
#     每塊抓完立刻寫入 Sheet, 進度落地, 被殺也不會整段白跑。
#  2. JobStreet list fetch 沒有 retry (jobstreet.py:305-315): 任何例外都中止整個
#     keyword crawl, main() 印「無資料，結束」並 exit 0 → 假成功。
#     → supervisor 層嚴格驗收: 必須 exit 0 且 log 真的有「結果: {」。
#  3. launchctl submit 預設 keepalive → 結束時必須自我 launchctl remove。
#
# ── v1.8.0: 切塊從「累計頁數」改成「頁面區間」 ─────────────────────────────────
# 舊版第 N 塊爬第 1..N 頁 → 前面 N-1 頁每跑一塊就重爬一遍。
# 30d 的 LinkedIn 實測: 355 個 page fetch 換 100 頁的池子 = 3.55× 重複。
# 改成區間式後每頁只抓一次; 跨塊去重靠 seen_jds.jsonl + sheet pre-dedup。
# LinkedIn 的 list 是 sortBy=DD (依日期排序) → 順序穩定, 區間式安全。
#
# ── v1.8.0: per-source sleep ─────────────────────────────────────────────────
# LinkedIn 1.5-3.0s (Guest API 會 429, 30/60/90 backoff 仍在)
# JobStreet 0.5-1.0s (壓力測試 0.5s / 200 reqs = 0 fail)
# → list request 從 6.5s 降到 3.2s / 1.6s

set -uo pipefail

cd "${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}" || exit 1

# 這台機: LinkedIn Guest API 直連回 451, Google Sheets API 直連會 timeout,
# 兩邊都要走本地 proxy (127.0.0.1:12000)。launchctl submit 的 job 不一定繼承
# submitting shell 的 env → 這裡顯式補上, 不要靠 .env 剛好有。
export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:12000}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:12000}"
unset CONTROL_PLANE_HTTP_PROXY

RANGE="${1:-14d}"
WAIT_FOR="${2:-}"
# 第 3 個參數: LinkedIn 的 max-pages 覆寫。
# 引擎預設是照「上海池深」定的, 新加坡的池可能更深 (實測 2026-11-22 SG 7d = 550 筆 = 55 頁,
# 剛好卡在引擎預設 55 頁的邊界, 池子一長就又被截斷)。給大一點的餘裕。
LI_MAX_OVERRIDE="${3:-}"
# 第 4 個參數: JobStreet 的 max-pages 覆寫。
# 這個值是「每個 keyword」的頁數上限 (不是 5 個 keyword 合計), 2026-11-23 起尤其重要:
# v1.6.8 改成 per-keyword 軟停 → 5 個 keyword 每個都會爬到自己的池底, 請求量約為
# 舊版的 5 倍。引擎預設已依各 range 實測池深重設 (7d=73 / 14d=120 / 21d=168 / 30d=220),
# 這裡通常不需要再覆寫; 要覆寫時給的也是 per-keyword 頁數。
JS_MAX_OVERRIDE="${4:-}"

RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
mkdir -p "$RUNS"
# RANGE_TAG 去掉尾端的 d, 讓 14d→14 / 21d→21 / 30d→30 / 3d→3 / 7d→7 / 24h→24h
# → PREFIX=sg14, JOB=com.mavis.sg14
# 重要: JOB 必須跟 launchctl submit 時用的 -l label 完全一致, 否則跑完時
# `launchctl remove "$JOB"` 會失敗, 而 launchctl submit 的 job 預設 keepalive
# → 會無限重啟。所以檔名/label 都從同一個 RANGE 推導, 不要手動拼。
RANGE_TAG="${RANGE%d}"
PREFIX="sg${RANGE_TAG}"
LOG="$RUNS/$PREFIX.log"
STATE="$RUNS/${PREFIX}_chunk_state.txt"
TMPLOG="$RUNS/${PREFIX}_chunk_attempt.log"
JOB="com.mavis.${PREFIX}"

# 塊的切法直接從引擎讀該 range 的「預設 max pages」再切成 ~3 塊,
# 不要手動拼 → 換 range 時不會超抓 (例如 7d 預設只有 15 頁, 不是 30 頁)。
#
# 注意: 兩個清單必須用「各自獨立的呼叫」取得, 且 max pages 走 argv 傳入。
# 不要用 `read A B <<< "x y | z w"` —— read 只會把第一個字給 A、其餘(連 | 換過的
# 空白)全部給 B, 會變成 LI_CHUNKS="5" / JS_CHUNKS="10 15 5 10 15",
# 導致 LinkedIn 只爬到一半、JobStreet 順序錯亂 (2026-10-31 踩過)。
_split_py='
import sys
def ranges(m, n):
    """把 m 頁切成 n 段, 回傳 "start-end" (1-based, 含頭含尾)。"""
    if m <= n:
        return [f"1-{m}"]
    step = -(-m // n)
    out = []
    start = 1
    while start <= m:
        end = min(start + step - 1, m)
        out.append(f"{start}-{end}")
        start = end + 1
    return out
print(" ".join(ranges(int(sys.argv[1]), int(sys.argv[2]))))
'
LI_DEFAULT_MAX=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.TIME_RANGES['$RANGE'][1])")
JS_DEFAULT_MAX=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.JOBSTREET_MAX_PAGES['$RANGE'])")
# 2026-11-22: 引擎預設是照「上海池深」定的, 但新加坡的池可能更深
# (實測 SG 7d = 550 筆 = 55 頁, 剛好卡在引擎預設 55 頁的邊界)。
# SG_MAX_PAGES / SG_JS_MAX_PAGES 可以在不改 repo 的前提下把上限拉寬。
LI_MAX="${SG_MAX_PAGES:-${LI_MAX_OVERRIDE:-$LI_DEFAULT_MAX}}"
JS_MAX="${SG_JS_MAX_PAGES:-${JS_MAX_OVERRIDE:-$JS_DEFAULT_MAX}}"
# SG_LI_SPLIT: LinkedIn 切成幾塊 (預設 3)。
# 塊越大 → 每塊的邊際新職缺越多 → 塊越長, 被 jetsam 殺的風險越高;
# 塊越小 → 每塊都要重讀一次 Sheet (啟動成本) + 總頁數不變。
# 2026-11-24 實測: v1.8.0 之後一塊只要 ~4-8 分, 6 塊剛好。
LI_SPLIT="${SG_LI_SPLIT:-3}"
JS_SPLIT="${SG_JS_SPLIT:-3}"
LI_CHUNKS=$(.venv/bin/python -c "$_split_py" "$LI_MAX" "$LI_SPLIT")
JS_CHUNKS=$(.venv/bin/python -c "$_split_py" "$JS_MAX" "$JS_SPLIT")

URL=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.SG_RAW_URL)")

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG" 2>&1; }

# 2026-11-19: 連敗 3 次的塊會被記在這裡, 最後報出來 + exit 3。
# 不寫進 STATE → 下次 run 會重跑那些塊, 不會靜默少抓。
FAILED=""
POOLED=""

# ── 記憶體壓力觀察 (2026-11-19) ─────────────────────────────────────────────
# 這台機是 8GB RAM, swap 常年用到 10GB+/12GB, free page 常常只剩幾十 MB。
# macOS 的 jetsam 會在這種狀態下殺行程 (2026-11-19 12:45 實測:
# "Process knowledgeconstructiond killed by jetsam reason per-process-limit")。
# 所以每塊都要記下當下的記憶體壓力, 下次被殺時不用再去翻已經過期的 unified log。
mem_free_mb() { vm_stat 2>/dev/null | awk '/^Pages free/{gsub(/[.]/,"",$3); print int($3*16384/1048576)}'; }
swap_used_mb() { sysctl -n vm.swapusage 2>/dev/null | sed 's/.*used = \([0-9]*\).*/\1/'; }

# 退出碼 → 人看得懂的死因。137 = 128+9 (SIGKILL), 143 = 128+15 (SIGTERM)。
kill_reason() {
    case "$1" in
        137) echo "SIGKILL(9): 被外部殺掉 — 這台機最可能是 jetsam/記憶體壓力";;
        143) echo "SIGTERM(15): 被要求終止";;
        139) echo "SIGSEGV(11): C 層 crash";;
        124) echo "timeout: 被 timeout 砍掉";;
        0)   echo "ok";;
        *)   echo "exit=$1";;
    esac
}

log "塊設定: linkedin=[$LI_CHUNKS] (max=$LI_MAX, 引擎預設 $LI_DEFAULT_MAX) jobstreet=[$JS_CHUNKS] (max=$JS_MAX, 引擎預設 $JS_DEFAULT_MAX)"
log "記憶體基準: free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

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

all_done() {
    for mp in $LI_CHUNKS; do
        [ -f "$STATE" ] && grep -qx "linkedin:$mp" "$STATE" || return 1
    done
    for mp in $JS_CHUNKS; do
        [ -f "$STATE" ] && grep -qx "jobstreet:$mp" "$STATE" || return 1
    done
    return 0
}

if all_done; then
    log "所有 chunk 已完成 → 卸載 launchd job"
    launchctl remove "$JOB" 2>/dev/null
    exit 0
fi

log ""
log "=== SUPERVISOR START (pid $$) range=$RANGE job=$JOB ==="
log "TARGET: $URL"

run_source() {
    local src="$1"; shift
    local chunks="$*"

    for R in $chunks; do
        local START="${R%%-*}"
        local END="${R##*-}"
        local KEY="$src:$R"
        if [ -f "$STATE" ] && grep -qx "$KEY" "$STATE"; then
            log "--- $KEY 已完成, 跳過 ---"
            continue
        fi

        attempt=0
        while true; do
            attempt=$((attempt + 1))
            log "--- CHUNK $KEY (pages $START..$END) attempt=$attempt 開始 ---"

            # background 跑 + 採樣峰值 RSS: 被殺時才知道是記憶體被 jetsam 挑走還是真的 hang。
            .venv/bin/python -u sg_product_jobs.py "$RANGE" --source "$src" \
                --with-jd --start-page "$START" --max-pages "$END" --to-sheet "$URL" > "$TMPLOG" 2>&1 &
            CHILD=$!
            PEAK_KB=0
            while kill -0 "$CHILD" 2>/dev/null; do
                RSS=$(ps -o rss= -p "$CHILD" 2>/dev/null | tr -d ' ')
                if [ -n "$RSS" ] && [ "$RSS" -gt "$PEAK_KB" ]; then PEAK_KB=$RSS; fi
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

            log "CHUNK $KEY attempt=$attempt EXIT=$rc [$(kill_reason "$rc")] wrote=$wrote nodata=$nodata listFAIL=$listfail $fetched $written $rows peak_rss=${PEAK_MB}MB mem_free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

            # 「無資料」= 這個區間的頁已經在池子之外 (pool 到底) → 算完成, 不是缺口。
            # 區間式切塊一定會有這種塊: 最後一塊常常跨過池底。
            if [ "$nodata" -ge 1 ] && [ "$rc" -eq 0 ]; then
                log "--- $KEY pool 到底 (無資料) → 標記完成 ---"
                echo "$KEY" >> "$STATE"
                POOLED="$POOLED $KEY"
                break
            fi

            if [ "$rc" -eq 0 ] && [ "$wrote" -ge 1 ] && [ "$nodata" -eq 0 ]; then
                if [ "$listfail" -ge 1 ] && [ "$attempt" -lt 3 ]; then
                    log "--- $src $R list 有 FAIL (coverage 可能不完整), 重試 ---"
                    sleep 20
                    continue
                fi
                echo "$KEY" >> "$STATE"
                break
            fi

            if [ "$attempt" -ge 3 ]; then
                # 2026-11-19 fix: 原本這裡會把這一塊寫進 STATE 當成「已完成」,
                # 於是被殺掉的塊會被靜默跳過, run 看起來成功但 coverage 其實有缺口。
                # 現在不寫 STATE → 下次 run 會從頭重跑這一塊。
                log "--- $src $R 連敗 3 次 (EXIT=$rc [$(kill_reason "$rc")]), 標記為未完成 (不寫 state) ---"
                FAILED="$FAILED $KEY"
                break
            fi
            log "--- $src $R 失敗 (EXIT=$rc [$(kill_reason "$rc")]), 20s 後重試 ---"
            sleep 20
        done
    done
}

# SG_SOURCES: 要跑哪些 source (空白分隔, 預設兩個都跑)。
# 2026-11-23 起 JobStreet 改用 keyword 軸的 run_sg_jobstreet.sh (per-keyword 軟停);
# 這支 runner 的 JobStreet 切塊是「全 keyword 累計切塊」→ list 請求量多約 5 倍。
# 所以只跑 LinkedIn 時用 SG_SOURCES=linkedin 把它關掉, 別讓兩邊重疊爬。
SG_SOURCES="${SG_SOURCES:-linkedin jobstreet}"

case " $SG_SOURCES " in
  *" linkedin "*) run_source linkedin $LI_CHUNKS ;;
  *) log "SG_SOURCES 不含 linkedin → 跳過 LinkedIn 塊" ;;
esac
case " $SG_SOURCES " in
  *" jobstreet "*) run_source jobstreet $JS_CHUNKS ;;
  *) log "SG_SOURCES 不含 jobstreet → 跳過 JobStreet 塊 (改用 run_sg_jobstreet.sh)" ;;
esac

log "=== SUPERVISOR DONE (range=$RANGE) ==="
log "SEEN: $(wc -l < seen_jds.jsonl) 筆 (after)"
log "記憶體結束狀態: free=$(mem_free_mb)MB swap_used=$(swap_used_mb)MB"

if [ -n "$FAILED" ]; then
    log "⚠️⚠️ 有未完成的塊 (被殺或連敗 3 次):$FAILED"
    log "⚠️⚠️ 這些塊沒有寫進 state → 下次 run 會從頭重跑, 不要把這輪當成完整 coverage"
else
    log "所有塊都完成 (state 已記錄)"
fi
[ -n "$POOLED" ] && log "以下塊是 pool 到底 (不是缺口):$POOLED"

launchctl remove "$JOB" 2>/dev/null
log "已卸載 launchd job"

# 有未完成塊 → exit 3, 讓呼叫端可以分辨「跑完了但有缺口」跟「完整跑完」。
[ -n "$FAILED" ] && exit 3
exit 0
