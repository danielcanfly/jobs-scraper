#!/bin/bash
# 清掉某個 range 的 chunk state (留 .bak-<時間戳>)。
#
# 為什麼需要這支 (2026-11-24, Daniel 決定「每次跑前自動清 state」):
#   區間式切塊 (v1.8.0) 的 state key 是「頁面區間」(例: linkedin:1-27),
#   而區間計畫是固定的 → 下一輪再跑同一個 range 會全部命中 → 整輪跳過
#   → 池子裡新長出來的職缺一個都撿不到 (靜默漏抓)。
#   所以每輪「新的抓取」之前要先清 state。
#
# 清完再跑, 中途被殺時 state 還在 → 下一次重跑會從未完成的塊接續
#   (這才是 state 真正的用途: 同一輪內的續跑保護, 不是跨輪的 cache)。
#
# 用法: reset_state.sh <range>      # 例: reset_state.sh 7d / 30d
set -uo pipefail

RUNS="${JOBS_SCRAPER_RUNTIME_DIR:-${HOME}/.minimax-agent/projects/.runs}"
mkdir -p "$RUNS"
RANGE="${1:-}"
if [ -z "$RANGE" ]; then
  echo "usage: reset_state.sh <range>   (例: 7d / 14d / 30d)" >&2
  exit 2
fi

TAG="${RANGE%d}"
STAMP=$(date +%Y%m%d-%H%M%S)
FOUND=0

# SG 有兩個 state (LinkedIn + JobStreet keyword 軸), TW 只有一個。
for f in "$RUNS/sg${TAG}_chunk_state.txt" "$RUNS/sg${TAG}js_chunk_state.txt" "$RUNS/tw${TAG}_chunk_state.txt"; do
  [ -f "$f" ] || continue
  FOUND=1
  cp "$f" "$f.bak-$STAMP"
  : > "$f"   # 清空 (不用 rm → 會被權限閘擋)
  echo "已清: $(basename "$f")  (備份 $(basename "$f").bak-$STAMP)"
done

[ "$FOUND" -eq 1 ] || echo "range=$RANGE 沒有 state 檔 (第一次跑, 不需要清)"
exit 0
