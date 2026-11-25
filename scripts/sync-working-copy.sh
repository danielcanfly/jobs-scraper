#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# jobs-scraper working-copy sync — 從 upstream checkout 拉最新到工作目錄
#
# 用法:
#   ./scripts/sync-working-copy.sh            # 拉取 + 套用 + 校驗 + 測試
#   ./scripts/sync-working-copy.sh --verify   # 只校驗工作目錄與 upstream 是否一致
#
# 為什麼需要這支 (v1.8.4):
#   三處不變式裡, upstream→GitHub 是 git push、GitHub→plugin 是
#   sync-from-repo.sh, 但 upstream→工作目錄一直只有一段手動 cp 迴圈。
#   漏掉那一段, 工作目錄就跟另外兩處分岔 —— v1.8.3 就是這樣才發現
#   工作目錄少了整個 ops/。
#
# 設計原則 (與 sync-from-repo.sh 對稱):
#   1. 檔案清單取自 upstream checkout 的 git 追蹤集 —— 不是任何一處自己的
#      git ls-files: 工作目錄有自己的 git repo, 追蹤的是本機殘留檔。
#   2. 只覆蓋 upstream 有的檔案, 絕不刪除本機獨有的檔案。
#   3. 私有狀態 (.env / .secrets / seen_jds.jsonl / JD 快取) 不進、不出。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# 這支腳本會把 upstream 的 scripts/ 複製到工作目錄 → 覆蓋自己。
# bash 逐段讀腳本: 執行中的檔案被改寫, 讀取位移沒跟著走 → 下一段從錯的
# 位置解析 → 語法錯誤。從暫存副本執行, 正在跑的那份永遠不會被改寫。
# 判斷「我是不是那份副本」用 BASH_SOURCE[0] 跟 _SELF 比對, 不要靠繼承的旗標。
# 旗標與路徑都會被 export 給子行程: 子行程繼承之後會跳過 re-exec 而直接跑原檔,
# 而它手上的 _ORIGIN 指向的是父行程的腳本 → 它會跑去父行程的目錄發布,
# 一層套一層 (v1.8.5 實際踩到: release 腳本在測試裡遞迴執行)。
if [ "${BASH_SOURCE[0]}" != "${_JOBS_SCRAPER_SYNC_WC_SELF:-}" ]; then
  _sync_origin="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
  _sync_self="$(mktemp -t jobs-scraper-wc-sync-self-XXXXXX)"
  cp -- "$_sync_origin" "$_sync_self"
  chmod +x "$_sync_self"
  export _JOBS_SCRAPER_SYNC_WC_SELF="${_sync_self}"
  export _JOBS_SCRAPER_SYNC_WC_ORIGIN="${_sync_origin}"
  exec bash "$_sync_self" "$@"
fi

# 到這裡我就是那份暫存副本 → 跑完只刪它, 而且只刪它。
trap 'rm -f -- "${_JOBS_SCRAPER_SYNC_WC_SELF}"' EXIT

REPO_DIR="$(cd -- "$(dirname -- "${_JOBS_SCRAPER_SYNC_WC_ORIGIN:-${BASH_SOURCE[0]}}")/.." &> /dev/null && pwd)"

# upstream 的位置: 預設是這個腳本所在的 checkout (前提是它就是 upstream),
# 否則用標準位置。判斷方式是 origin remote —— 工作目錄沒有 remote,
# 所以工作目錄裡的那份副本不會把工作目錄當成自己的來源。
remote="$(git -C "$REPO_DIR" config --get remote.origin.url 2>/dev/null || true)"
case "$remote" in
  *danielcanfly/jobs-scraper*) DEFAULT_UPSTREAM="$REPO_DIR" ;;
  *) DEFAULT_UPSTREAM="$HOME/.minimax-agent/projects/jobs-scraper-unified" ;;
esac

UPSTREAM_DIR="${UPSTREAM_DIR:-$DEFAULT_UPSTREAM}"
WORKING_COPY="${JOBS_SCRAPER_WORKING_COPY:-$HOME/.minimax-agent/projects/scrapling-test}"

# 不複製的本機狀態。upstream 不會追蹤它們, 這裡是保險。
SKIP_PATTERNS=(
  ".env"
  ".secrets/*"
  "seen_jds.jsonl"
  "local_tools/*"
  "_archive/*"
)

skip_file() {
  local path="$1" pat
  for pat in "${SKIP_PATTERNS[@]}"; do
    case "$path" in
      $pat) return 0 ;;
    esac
  done
  return 1
}

MODE="sync"
for arg in "$@"; do
  case "$arg" in
    --verify) MODE="verify" ;;
    -h|--help)
      awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

echo "🔄 jobs-scraper working-copy sync"
echo "=================================="
echo "  upstream:      $UPSTREAM_DIR"
echo "  working copy:  $WORKING_COPY"
echo "  mode:          $MODE"
echo ""

if [ ! -d "$UPSTREAM_DIR" ]; then
  echo "upstream 不存在: $UPSTREAM_DIR" >&2
  exit 1
fi
if [ ! -d "$WORKING_COPY" ]; then
  echo "工作目錄不存在: $WORKING_COPY" >&2
  exit 1
fi

# ── 1. 檔案清單: upstream checkout 的 git 追蹤集 ─────────────────────────────
tracked=()
while IFS= read -r -d '' f; do
  tracked+=("$f")
done < <(git -C "$UPSTREAM_DIR" ls-files -z)

# ── 2. 套用 ────────────────────────────────────────────────────────────────
copied=0
skipped=0
if [ "$MODE" = "sync" ]; then
  for f in "${tracked[@]}"; do
    if skip_file "$f"; then
      skipped=$((skipped+1))
      continue
    fi
    src="$UPSTREAM_DIR/$f"
    if [ ! -f "$src" ]; then
      echo "  ! upstream 缺檔案: $f" >&2
      continue
    fi
    dst="$WORKING_COPY/$f"
    mkdir -p "$(dirname -- "$dst")"
    cp -- "$src" "$dst"
    copied=$((copied+1))
  done
  echo "  ✓ 複製 $copied 個檔案 (跳過本機狀態 $skipped 個)"
fi

# ── 3. 校驗: 每一個被追蹤的檔案, 位元組都要一樣 ────────────────────────────
echo ""
echo "🔍 一致性校驗 (working copy vs upstream)"
drift=0
checked=0
for f in "${tracked[@]}"; do
  if skip_file "$f"; then
    continue
  fi
  src="$UPSTREAM_DIR/$f"
  dst="$WORKING_COPY/$f"
  if [ ! -f "$dst" ]; then
    echo "  ✗ $f  (工作目錄缺檔)"
    drift=$((drift+1))
    continue
  fi
  checked=$((checked+1))
  if ! cmp -s "$src" "$dst"; then
    echo "  ✗ $f  (內容不同)"
    drift=$((drift+1))
  fi
done

echo ""
if [ "$drift" -eq 0 ]; then
  echo "  ✓ 全部 $checked 個檔案一致"
else
  echo "  ⚠️  $drift 處不一致 — 工作目錄與 upstream 已經分岔"
fi

# ── 4. 本機獨有檔案: 數量, 不動它們 ───────────────────────────────────────
tracked_list="$(mktemp -t jobs-scraper-wc-tracked-XXXXXX)"
for f in "${tracked[@]}"; do
  printf '%s\n' "$f" >> "$tracked_list"
done
local_only=0
while IFS= read -r -d '' f; do
  rel="${f#"$WORKING_COPY"/}"
  case "$rel" in
    .git/*|.venv/*|__pycache__/*|*.pyc|.pytest_cache/*|.ruff_cache/*|.mypy_cache/*|*.egg-info/*)
      continue
      ;;
  esac
  if skip_file "$rel"; then
    continue
  fi
  if grep -Fxq -- "$rel" "$tracked_list"; then
    continue
  fi
  local_only=$((local_only+1))
done < <(find "$WORKING_COPY" -type f -print0 2>/dev/null || true)
rm -f -- "$tracked_list"
echo "  ℹ️  工作目錄另有 $local_only 個本機獨有檔案 (未觸碰)"

# ── 5. 測試 ───────────────────────────────────────────────────────────────
echo ""
echo "🧪 跑測試..."
if [ -x "$WORKING_COPY/.venv/bin/python" ]; then
  (cd "$WORKING_COPY" && .venv/bin/python -m pytest 2>&1 | tail -3)
else
  echo "  (跳過: 沒有 .venv)"
fi

echo ""
if [ "$MODE" = "verify" ]; then
  echo "🔍 只校驗, 未更動任何檔案."
else
  echo "🎉 working copy 已與 upstream 同步."
fi
exit "$drift"
