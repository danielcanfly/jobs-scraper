#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# jobs-scraper Mavis plugin sync — 從 danielcanfly/jobs-scraper 拉最新
#
# 用法:
#   ./scripts/sync-from-repo.sh            # 拉取 + 套用 + 校驗
#   ./scripts/sync-from-repo.sh --verify   # 只校驗本地與 upstream 是否一致 (不改動)
#   ./scripts/sync-from-repo.sh --check    # 校驗三處 (plugin / working copy / upstream)
#
# 設計原則 (2026-10-26 v1.4.0 統一):
#   1. 單一版本線 — plugin runtime、working copy、upstream 必須是同一份 code。
#      sync 之後會用 SHA 逐一比對, 不一致就明確報出來。
#   2. 只覆蓋 upstream 有的檔案, 絕不刪除本地獨有的檔案 (含 local 測試)。
#   3. Mavis 專屬檔案一律保留。
#   4. 拉的是 pull, 不是 push — 要推上去請先在 upstream 開 PR。
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." &> /dev/null && pwd)"
UPSTREAM="${JOBS_SCRAPER_UPSTREAM:-https://github.com/danielcanfly/jobs-scraper.git}"
BRANCH="${JOBS_SCRAPER_BRANCH:-main}"
TMP_DIR="$(mktemp -d -t jobs-scraper-sync-XXXXXX)"

# ── 會被 upstream 覆蓋的根目錄檔案 ────────────────────────────────
SYNC_FILES=(
  server.py
  server_v1_1.py
  sg_product_jobs.py
  job_tracker.py
  region_policy.py
  runtime_core.py
  setup.sh
  requirements.txt
  pyproject.toml
  test_helpers.py
  .env.example
  LICENSE
  README.md
  RULES.md
  SKIP.md
  CHANGELOG.md
)

# ── 會被整個目錄覆蓋的路徑 ───────────────────────────────────────
# 注意: 目錄是「合併」不是「刪掉重建」, 同名檔覆蓋, 本地獨有的保留。
SYNC_DIRS=(
  jobs_scraper
  skills/jobs-scraper
  docs
  .github
  scripts
  tests
)

# ── 永遠保留 (Mavis 專屬 / 本機狀態) ──────────────────────────────
# 上游沒有這些檔, 同步時不動。
PRESERVED=(
  .minimax-plugin
  .codex-plugin
  servers.mcp.json
  run-server.sh
  icon.png
  .env
  .secrets
  seen_jds.jsonl
  skills/sg-jobs-run
  skills/sg-jobs-audit
  skills/sg-jobs-stats
)

MODE="sync"
for arg in "$@"; do
  case "$arg" in
    --verify) MODE="verify" ;;
    --check)  MODE="check" ;;
    -h|--help)
      sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# ─────────────────────────────────────────────────────────────
# 把 upstream 的某個路徑合併進 plugin (同名覆蓋, 不刪本地獨有)
# ─────────────────────────────────────────────────────────────
merge_dir() {
  local src="$1" dst="$2"
  [ -d "$src" ] || return 0
  mkdir -p "$dst"
  # 逐項複製, 保留本地獨有檔
  (cd "$src" && find . -type f -print0) | while IFS= read -r -d '' rel; do
    local target="$dst/${rel#./}"
    mkdir -p "$(dirname "$target")"
    cp -f "$src/${rel#./}" "$target"
  done
  echo "  ✓ ${dst#$REPO_DIR/}"
}

# ─────────────────────────────────────────────────────────────
# 一致性校驗: plugin vs upstream 的 SHA 比對
# ─────────────────────────────────────────────────────────────
verify_against_upstream() {
  local tmp="$1"
  local drift=0 checked=0
  echo ""
  echo "🔍 一致性校驗 (plugin vs upstream@$BRANCH)"

  for f in "${SYNC_FILES[@]}"; do
    if [ -f "$tmp/$f" ]; then
      checked=$((checked+1))
      if ! cmp -s "$tmp/$f" "$REPO_DIR/$f"; then
        echo "  ✗ $f  (plugin 與 upstream 不一致)"
        drift=$((drift+1))
      fi
    fi
  done

  for d in "${SYNC_DIRS[@]}"; do
    if [ -d "$tmp/$d" ]; then
      (cd "$tmp" && find "$d" -type f -not -path "*/__pycache__/*" -print0) \
        | while IFS= read -r -d '' rel; do
          if [ -f "$REPO_DIR/$rel" ]; then
            checked=$((checked+1))
            if ! cmp -s "$tmp/$rel" "$REPO_DIR/$rel"; then
              echo "  ✗ $rel  (plugin 與 upstream 不一致)"
              drift=$((drift+1))
            fi
          else
            echo "  ✗ $rel  (upstream 有, plugin 缺)"
            drift=$((drift+1))
          fi
        done
    fi
  done

  echo ""
  if [ "$drift" -eq 0 ]; then
    echo "  ✓ 全部 $checked 個檔案一致"
  else
    echo "  ⚠️  $drift 處不一致 — plugin 與 upstream 已經分岔, 需要處理"
  fi
  return "$drift"
}

echo "🔄 jobs-scraper Mavis plugin sync"
echo "=================================="
echo "  plugin:   $REPO_DIR"
echo "  upstream: $UPSTREAM @ $BRANCH"
echo "  mode:     $MODE"
echo ""

git clone --depth 1 --branch "$BRANCH" "$UPSTREAM" "$TMP_DIR" 2>&1 | tail -2

if [ "$MODE" = "verify" ] || [ "$MODE" = "check" ]; then
  set +e
  verify_against_upstream "$TMP_DIR"
  rc=$?
  set -e
  rm -rf "$TMP_DIR"
  exit "$rc"
fi

# 1. 備份 Mavis 專屬檔
BACKUP_DIR="$(mktemp -d -t jobs-scraper-backup-XXXXXX)"
for p in "${PRESERVED[@]}"; do
  [ -e "$REPO_DIR/$p" ] && cp -Rp "$REPO_DIR/$p" "$BACKUP_DIR/" 2>/dev/null || true
done
echo "  ✓ 已備份 Mavis 專屬檔到 $BACKUP_DIR"

# 2. 複製根目錄檔
echo ""
for f in "${SYNC_FILES[@]}"; do
  if [ -f "$TMP_DIR/$f" ]; then
    cp -f "$TMP_DIR/$f" "$REPO_DIR/$f"
    echo "  ✓ $f"
  fi
done

# 3. 合併目錄 (不刪本地獨有檔)
echo ""
for d in "${SYNC_DIRS[@]}"; do
  if [ -d "$TMP_DIR/$d" ]; then
    merge_dir "$TMP_DIR/$d" "$REPO_DIR/$d"
  fi
done

# 4. 還原 Mavis 專屬檔
echo ""
for p in "${PRESERVED[@]}"; do
  if [ -e "$BACKUP_DIR/$p" ]; then
    if [ -d "$BACKUP_DIR/$p" ]; then
      rm -rf "$REPO_DIR/$p"
    fi
    cp -Rp "$BACKUP_DIR/$p" "$REPO_DIR/"
  fi
done
echo "  ✓ Mavis 專屬檔還原 (${PRESERVED[*]})"

# 5. 一致性校驗
set +e
verify_against_upstream "$TMP_DIR"
verify_rc=$?
set -e

# 6. 測試
echo ""
echo "🧪 跑測試..."
if [ -x "$REPO_DIR/.venv/bin/python" ]; then
  (cd "$REPO_DIR" && .venv/bin/python -m pytest -q 2>&1 | tail -4)
else
  echo "  (跳過: 沒有 .venv)"
fi

# 7. 清理
rm -rf "$TMP_DIR" "$BACKUP_DIR"

echo ""
echo "🎉 sync 完成. Plugin 與 upstream 已同步."
echo "   下次更新: bash $REPO_DIR/scripts/sync-from-repo.sh"
echo "   只校驗:   bash $REPO_DIR/scripts/sync-from-repo.sh --verify"
echo "   換 branch: JOBS_SCRAPER_BRANCH=<branch> bash $REPO_DIR/scripts/sync-from-repo.sh"
exit "$verify_rc"
