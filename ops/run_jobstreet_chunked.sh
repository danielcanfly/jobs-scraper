#!/bin/bash
# JobStreet 30d SG — chunked supervisor (v2)
#
# 兩個必須處理的問題:
#  1. 這台機器會用 signal 殺掉長跑的 python (實測 ~31 分 / ~41 分), 整段跑必然重頭來。
#     → 切小塊, 每塊抓完立刻寫入 Sheet, 進度落地。
#  2. jobs_scraper/sources/jobstreet.py 的 list fetch 沒有 retry:
#     任何例外都 `return all_jobs` 直接中止整個 keyword crawl (line ~305-315),
#     然後 main() 印「無資料，結束」並 exit 0 → 假成功。
#     → 這裡在 supervisor 層嚴格驗收, 假成功不算成功, 直接重試。
#
# 分塊: --max-pages 遞增 (cumulative)。每塊的 list 結果會被 pre_dedup 對 Sheet 去重,
# 所以第 N 塊只會抓「前面沒寫過的」那些職缺 → JD fetch 數是遞減的 delta。
# 用小步長 (4 頁 ≈ 80 職缺 ≈ 8 分) 讓每個 process 的壽命遠小於被殺的門檻。
#
# state file: 每行一個已完成塊的 max-pages。最後一個 chunk 完成後自我卸載
# (launchctl submit 預設 keepalive, 不卸載會無限重啟)。

cd "${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}" || exit 1

RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
mkdir -p "$RUNS"
LOG=$RUNS/sg30_jobstreet.log
STATE=$RUNS/sg30_chunk_state.txt
TMPLOG=$RUNS/sg30_chunk_attempt.log

URL=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.SG_RAW_URL)")
CHUNKS="6 10 14 18 22 25"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG" 2>&1; }

# 全部塊都做完了 → 卸載自己, 否則 launchd keepalive 會無限重啟
all_done() {
    for mp in $CHUNKS; do
        [ -f "$STATE" ] && grep -qx "$mp" "$STATE" || return 1
    done
    return 0
}

if all_done; then
    log "所有 chunk 已完成 → 卸載 launchd job"
    launchctl remove com.mavis.sg30 2>/dev/null
    exit 0
fi

log ""
log "=== SUPERVISOR v2 START (pid $$) chunks=[$CHUNKS] ==="

for MP in $CHUNKS; do
    if [ -f "$STATE" ] && grep -qx "$MP" "$STATE"; then
        log "--- chunk max-pages=$MP 已完成, 跳過 ---"
        continue
    fi

    attempt=0
    while true; do
        attempt=$((attempt + 1))
        log "--- CHUNK max-pages=$MP attempt=$attempt 開始 ---"

        .venv/bin/python -u sg_product_jobs.py 30d --source jobstreet \
            --with-jd --max-pages "$MP" --to-sheet "$URL" > "$TMPLOG" 2>&1
        rc=$?

        wrote=$(grep -c "結果: {" "$TMPLOG")
        nodata=$(grep -c "無資料，結束" "$TMPLOG")
        listfail=$(grep -cE "\[jobstreet .*\] FAIL" "$TMPLOG")
        fetched=$(grep -oE "fetch [0-9]+" "$TMPLOG" | tail -1)
        written=$(grep -oE "'written': [0-9]+" "$TMPLOG" | tail -1)

        log "CHUNK $MP attempt=$attempt EXIT=$rc wrote=$wrote nodata=$nodata listFAIL=$listfail $fetched $written"

        # 成功條件: exit 0 且真的走到 sheet 寫入, 且不是「無資料」假成功
        if [ "$rc" -eq 0 ] && [ "$wrote" -ge 1 ] && [ "$nodata" -eq 0 ]; then
            if [ "$listfail" -ge 1 ]; then
                # list 被中途截斷 → coverage 不完整, 重試一次讓它跑更遠
                if [ "$attempt" -lt 3 ]; then
                    log "--- chunk $MP list 有 FAIL (coverage 可能不完整), 重試 ---"
                    sleep 20
                    continue
                fi
                log "--- chunk $MP 重試 3 次仍有 list FAIL, 接受並前進 ---"
            fi
            echo "$MP" >> "$STATE"
            break
        fi

        if [ "$attempt" -ge 3 ]; then
            log "--- chunk $MP 連敗 3 次 (EXIT=$rc nodata=$nodata), 標記並前進 ---"
            echo "$MP" >> "$STATE"
            break
        fi
        log "--- chunk $MP 失敗, 20s 後重試 ---"
        sleep 20
    done
done

log "=== SUPERVISOR v2 DONE ==="
log "SEEN: $(wc -l < seen_jds.jsonl) 筆 (after)"

# 自我卸載 (keepalive 會無限重啟)
launchctl remove com.mavis.sg30 2>/dev/null
log "已卸載 launchd job"
