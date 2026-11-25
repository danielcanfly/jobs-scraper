#!/bin/bash
# SG / TW 抓取鏈 — 依序跑完 5 個任務, 每個跑完才進下一個
#
# 用法: run_chain.sh
#   (沒有參數; 順序寫死在下面的 PHASES)
#
# 順序 (2026-11-24 Daniel 指定):
#   0. 等 sg 14d (com.mavis.sg14 + com.mavis.sg14js) 跑完
#   1. sg 30d  — LinkedIn (run_sg_chunked.sh, 只跑 linkedin) + JobStreet (run_sg_jobstreet.sh)
#   2. tw 7d   — run_tw_chunked.sh
#   3. tw 14d  — run_tw_chunked.sh
#   4. tw 30d  — run_tw_chunked.sh
#
# 為什麼自己寫鏈而不是排 5 個 launchd job:
#   1. 五個任務都要寫同一張 Sheet (SG-Raw / TW-Raw) → 同時跑會搶 next_row
#      跟 seen_jds.jsonl → 必須序列化。
#   2. launchctl submit 預設 keepalive → 每個 job 結束時要自我 launchctl remove,
#      否則會無限重啟。鏈自己跑 → 只有最外層這一個 label 需要卸載。
#   3. 每個階段的 state 檔各自獨立 → 中途被殺, 下次重跑會從未完成的塊接續。
#
# 這支腳本自己是 launchd job com.mavis.sgchain → 結束時自我卸載。

set -uo pipefail

RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
mkdir -p "$RUNS"
LOG="$RUNS/chain.log"
JOB="com.mavis.sgchain"

export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-http://127.0.0.1:12000}"
export HTTP_PROXY="${HTTP_PROXY:-http://127.0.0.1:12000}"
unset CONTROL_PLANE_HTTP_PROXY

log() { echo "[$(date '+%m-%d %H:%M:%S')] $*" >> "$LOG" 2>&1; }

label_present() {
    # 回傳 0 = 這個 launchd label 還在 (還沒結束)
    launchctl list 2>/dev/null | awk '{print $3}' | grep -qx "$1"
}

wait_gone() {
    local label="$1"
    log "=== 等待 $label 結束 ==="
    local waited=0
    while label_present "$label"; do
        sleep 30
        waited=$((waited + 30))
        [ $((waited % 300)) -eq 0 ] && log "仍在等 $label (已等 ${waited}s)"
    done
    log "=== $label 已結束 (等 ${waited}s) ==="
}

# 跑一個階段; 回傳 0 = 完成, 3 = 有缺口 (該階段的 supervisor 自己判定)
run_phase() {
    local name="$1"; shift
    log ""
    log "########## PHASE START: $name ##########"
    local t0=$SECONDS
    "$@" >> "$LOG" 2>&1
    local rc=$?
    log "########## PHASE END: $name (exit=$rc, 耗時 $(( (SECONDS - t0) / 60 )) 分) ##########"
    return $rc
}

log ""
log "=== CHAIN START (pid $$) job=$JOB ==="
log "順序: 等 sg14 → sg 30d (linkedin+jobstreet) → tw 7d → tw 14d → tw 30d"

# ── 0. 等 sg 14d ─────────────────────────────────────────────────────────────
wait_gone "com.mavis.sg14"
wait_gone "com.mavis.sg14js"

# ── 1. sg 30d ────────────────────────────────────────────────────────────────
# LinkedIn: 只跑 linkedin (JobStreet 走 keyword 軸的 runner)。
# SG_LI_SPLIT=5 → 切成 20/40/60/80/100 頁 5 塊, 每塊的邊際新職缺少一點 → 比較不會被殺。
# (3 塊時第 3 塊要爬 100 頁, 邊際 ~500 筆新 JD ≈ 2 小時, 被殺就整塊丟)
run_phase "sg30-linkedin" env SG_SOURCES=linkedin SG_LI_SPLIT=6 \
    /bin/bash "$SCRIPT_DIR/run_sg_chunked.sh" 30d
LI_RC=$?
log "sg30-linkedin exit=$LI_RC"

run_phase "sg30-jobstreet" /bin/bash "$SCRIPT_DIR/run_sg_jobstreet.sh" 30d
JS_RC=$?
log "sg30-jobstreet exit=$JS_RC"

# ── 2-4. TW ──────────────────────────────────────────────────────────────────
run_phase "tw-7d" /bin/bash "$SCRIPT_DIR/run_tw_chunked.sh" 7d
TW7_RC=$?
log "tw-7d exit=$TW7_RC"

run_phase "tw-14d" /bin/bash "$SCRIPT_DIR/run_tw_chunked.sh" 14d
TW14_RC=$?
log "tw-14d exit=$TW14_RC"

run_phase "tw-30d" /bin/bash "$SCRIPT_DIR/run_tw_chunked.sh" 30d
TW30_RC=$?
log "tw-30d exit=$TW30_RC"

log ""
log "=== CHAIN DONE ==="
log "exit code: sg30-linkedin=$LI_RC sg30-jobstreet=$JS_RC tw7=$TW7_RC tw14=$TW14_RC tw30=$TW30_RC"
log "(3 = 有缺口: 那個範圍有塊沒完成, 需要補跑; 其餘 0 = 完整)"

launchctl remove "$JOB" 2>/dev/null
log "已卸載 launchd job"
exit 0
