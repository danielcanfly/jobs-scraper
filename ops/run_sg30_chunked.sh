#!/bin/bash
# SG 30d — LinkedIn + JobStreet chunked supervisor (v3)
#
# 排在 SG 21d 之後跑: 先等 com.mavis.sg21 這個 launchd job 消失,
# 避免兩個 run 同時搶 Sheet 的 next_row / seen_jds.jsonl, 也避免同時打同一個 IP
# 提高 429 風險。
#
# 沿用 SG 30d / 21d 實戰結論:
#  1. 這台機器會用 signal 殺掉長跑的 python (實測 ~31 分 / ~41 分) → 切塊,
#     每塊抓完立刻寫入 Sheet。
#  2. JobStreet list fetch 沒有 retry (jobstreet.py:305-315) → 假成功風險,
#     supervisor 層嚴格驗收 (必須 exit 0 且 log 有「結果: {」)。
#  3. launchctl submit 預設 keepalive → 結束時自我 launchctl remove。
#
# 30d 的預設 max pages 是 25 (21d/14d 是 30)。LinkedIn 塊 10/20/25,
# JobStreet 塊 6/12/18/25。

cd "${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}" || exit 1

RANGE="${1:-30d}"
RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
mkdir -p "$RUNS"
LOG=$RUNS/sg30.log
STATE=$RUNS/sg30_chunk_state.txt
TMPLOG=$RUNS/sg30_chunk_attempt.log
JOB=com.mavis.sg30
WAIT_FOR_JOB=com.mavis.sg21

URL=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.SG_RAW_URL)")
LI_CHUNKS="10 20 25"
JS_CHUNKS="6 12 18 25"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG" 2>&1; }

log ""
log "=== 等待 SG21 結束 (job=$WAIT_FOR_JOB) ==="
waited=0
while launchctl list 2>/dev/null | grep -q "$WAIT_FOR_JOB"; do
    sleep 30
    waited=$((waited + 30))
    if [ $((waited % 300)) -eq 0 ]; then
        log "仍在等 SG21 結束 (已等 ${waited}s)"
    fi
done
log "=== SG21 已結束 (等 ${waited}s), 開始 SG$RANGE ==="

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

log "TARGET: $URL"

run_source() {
    local src="$1"; shift
    local chunks="$*"

    for MP in $chunks; do
        if [ -f "$STATE" ] && grep -qx "$src:$MP" "$STATE"; then
            log "--- $src max-pages=$MP 已完成, 跳過 ---"
            continue
        fi

        attempt=0
        while true; do
            attempt=$((attempt + 1))
            log "--- CHUNK $src max-pages=$MP attempt=$attempt 開始 ---"

            .venv/bin/python -u sg_product_jobs.py "$RANGE" --source "$src" \
                --with-jd --max-pages "$MP" --to-sheet "$URL" > "$TMPLOG" 2>&1
            rc=$?

            wrote=$(grep -c "結果: {" "$TMPLOG")
            nodata=$(grep -c "無資料，結束" "$TMPLOG")
            listfail=$(grep -cE "\[jobstreet .*\] FAIL" "$TMPLOG")
            fetched=$(grep -oE "fetch [0-9]+" "$TMPLOG" | tail -1)
            written=$(grep -oE "'written': [0-9]+" "$TMPLOG" | tail -1)
            rows=$(grep -oE "'end_row': [0-9]+" "$TMPLOG" | tail -1)

            log "CHUNK $src $MP attempt=$attempt EXIT=$rc wrote=$wrote nodata=$nodata listFAIL=$listfail $fetched $written $rows"

            if [ "$rc" -eq 0 ] && [ "$wrote" -ge 1 ] && [ "$nodata" -eq 0 ]; then
                if [ "$listfail" -ge 1 ] && [ "$attempt" -lt 3 ]; then
                    log "--- $src $MP list 有 FAIL (coverage 可能不完整), 重試 ---"
                    sleep 20
                    continue
                fi
                echo "$src:$MP" >> "$STATE"
                break
            fi

            if [ "$attempt" -ge 3 ]; then
                log "--- $src $MP 連敗 3 次 (EXIT=$rc nodata=$nodata), 標記並前進 ---"
                echo "$src:$MP" >> "$STATE"
                break
            fi
            log "--- $src $MP 失敗, 20s 後重試 ---"
            sleep 20
        done
    done
}

run_source linkedin $LI_CHUNKS
run_source jobstreet $JS_CHUNKS

log "=== SUPERVISOR v3 DONE (range=$RANGE) ==="
log "SEEN: $(wc -l < seen_jds.jsonl) 筆 (after)"

launchctl remove "$JOB" 2>/dev/null
log "已卸載 launchd job"
