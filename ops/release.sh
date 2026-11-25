#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# jobs-scraper 一鍵發布 — 驗收 → push → tag → 同步三處 → 三處驗收
#
# 用法:
#   bash ops/release.sh --dry-run   # 只驗收與同步, 不 push、不 tag
#   bash ops/release.sh             # 完整發布
#
# 為什麼要有這支 (v1.8.5):
#   發布的每一段過去都是靠記憶的 —— 忘了推、忘了打 tag、忘了同步工作目錄。
#   v1.8.3 就是這樣才發現工作目錄少了整個 ops/。這支把整條鏈收成一條指令,
#   而且每一段都先驗後動: 任何一項不過, 就停在動手之前。
#
# 這支不會替你決定「這是不是一個 release」—— 版本號要你手動改,
# 這支只負責確認改對了, 然後把該做的事做完。
#
# tag 由這支打 (在所有守衛都跑過之後), GitHub Release 物件由 CI 在收到
# tag push 時建立 —— 這台機器沒有 gh CLI, CI 用內建的 GITHUB_TOKEN 建 Release
# 不需要任何額外憑證。
#
# 環境變數:
#   JOBS_SCRAPER_DIR             plugin runtime (預設 ~/.minimax/plugins/jobs-scraper)
#   JOBS_SCRAPER_WORKING_COPY    工作目錄 (預設 ~/.minimax-agent/projects/scrapling-test)
#   JOBS_SCRAPER_PROXY           這台機器的本機 proxy (預設 http://127.0.0.1:12000)
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# 這支腳本會把 ops/ 複製到工作目錄 → 覆蓋自己。bash 逐段讀腳本, 執行中的檔案
# 被改寫 → 下一段從錯的位置解析 → 語法錯誤。從暫存副本執行。
# 判斷「我是不是那份副本」用 BASH_SOURCE[0] 跟 _SELF 比對, 不要靠繼承的旗標。
# 旗標與路徑都會被 export 給子行程: 子行程繼承之後會跳過 re-exec 而直接跑原檔,
# 而它手上的 _ORIGIN 指向的是父行程的腳本 → 它會跑去父行程的目錄發布,
# 一層套一層 (v1.8.5 實際踩到: release 腳本在測試裡遞迴執行)。
if [ "${BASH_SOURCE[0]}" != "${_JOBS_SCRAPER_RELEASE_SELF:-}" ]; then
  _rel_origin="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
  _rel_self="$(mktemp -t jobs-scraper-release-self-XXXXXX)"
  cp -- "$_rel_origin" "$_rel_self"
  chmod +x "$_rel_self"
  export _JOBS_SCRAPER_RELEASE_SELF="${_rel_self}"
  export _JOBS_SCRAPER_RELEASE_ORIGIN="${_rel_origin}"
  exec bash "$_rel_self" "$@"
fi

# 到這裡我就是那份暫存副本 → 跑完只刪它, 而且只刪它。
trap 'rm -f -- "${_JOBS_SCRAPER_RELEASE_SELF}"' EXIT

REPO_DIR="$(cd -- "$(dirname -- "${_JOBS_SCRAPER_RELEASE_ORIGIN:-${BASH_SOURCE[0]}}")/.." &> /dev/null && pwd)"
cd "$REPO_DIR"

PLUGIN_DIR="${JOBS_SCRAPER_DIR:-$HOME/.minimax/plugins/jobs-scraper}"
WORKING_COPY="${JOBS_SCRAPER_WORKING_COPY:-$HOME/.minimax-agent/projects/scrapling-test}"

# 這台機器的 GitHub 走本機 proxy (跟 ops/ 的 runner 同一個慣例)。
export JOBS_SCRAPER_PROXY="${JOBS_SCRAPER_PROXY:-http://127.0.0.1:12000}"
export HTTPS_PROXY="${HTTPS_PROXY:-$JOBS_SCRAPER_PROXY}"
export HTTP_PROXY="${HTTP_PROXY:-$JOBS_SCRAPER_PROXY}"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

PY=".venv/bin/python"

echo "════════════════════════════════════════════"
echo " jobs-scraper 發布"
echo "════════════════════════════════════════════"
echo "  repo:     $REPO_DIR"
echo "  plugin:   $PLUGIN_DIR"
echo "  working:  $WORKING_COPY"
echo "  mode:     $([ "$DRY_RUN" -eq 1 ] && echo dry-run || echo release)"
echo ""

# ── 1. 前置 ────────────────────────────────────────────────────────────────
echo "──── 1. 前置檢查 ────"
# 這裡每一個檢查都要 fail-closed。`git status` 讀不到 (不是 git checkout、
# 權限問題) 的時候, 不能把它當成「工作樹乾淨」—— 那是 fail-open, 會讓
# 一次發布在它根本看不到的樹上開始。
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "發布中止: 這不是一個 git checkout: $REPO_DIR" >&2
  exit 1
fi
if ! git status --porcelain >/dev/null 2>&1; then
  echo "發布中止: 無法讀取 git 狀態, 不能確定工作樹是乾淨的" >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "發布中止: 工作樹不乾淨, 先把改動整理成一個 commit:" >&2
  git status --porcelain | head -20 >&2
  exit 1
fi
echo "  ✓ 在 git checkout 裡, 工作樹乾淨"

# 版本號先從 pyproject.toml 用文字方式讀 (不需要 venv), 這樣「tag 必須指向 HEAD」
# 這個檢查可以在任何環境下先擋下來。權威的版本線檢查在下面的守衛裡跑。
VERSION="$(sed -n 's/^version = "\([^"]*\)".*/\1/p' pyproject.toml | head -1)"
if [ -z "$VERSION" ]; then
  echo "發布中止: 讀不到 pyproject.toml 的版本號" >&2
  exit 1
fi
echo "  ✓ 版本號: $VERSION"

# 已經存在的 tag 必須指向 HEAD。tag 是「這是個 release」的記錄, 指向別的 commit
# 就代表有人動過它 —— 發布不該默默移動一個已經發布出去的 tag。
if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
  TAGGED="$(git rev-list -n1 "v$VERSION")"
  HEAD_SHA="$(git rev-parse HEAD)"
  if [ "$TAGGED" != "$HEAD_SHA" ]; then
    echo "發布中止: tag v$VERSION 指向 ${TAGGED:0:8}, 但 HEAD 是 ${HEAD_SHA:0:8}" >&2
    echo "  已經發布出去的 tag 不會被這支腳本移動。要更新請明確地自己移動它。" >&2
    exit 1
  fi
  echo "  ✓ tag v$VERSION 已存在並指向 HEAD"
fi

# ── 2. 守衛 ────────────────────────────────────────────────────────────────
echo ""
echo "──── 2. 守衛 ────"
if [ ! -x "$PY" ]; then
  echo "發布中止: 找不到 $REPO_DIR/$PY (這個 checkout 沒有 venv)" >&2
  exit 1
fi
FORMAT_TARGETS="$(git ls-files '*.py' ':!tests/equivalence/*' ':!scripts/check_equivalence_freeze.py')"
"$PY" -m ruff format --check $FORMAT_TARGETS
"$PY" -m ruff check .
"$PY" -m mypy --config-file pyproject.toml
"$PY" -m pytest 2>&1 | tail -1
"$PY" scripts/check_equivalence_freeze.py
"$PY" scripts/check_repo_hygiene.py
"$PY" scripts/check_sync_manifest.py
"$PY" ops/check_version_line.py

# ── 3. 推送與 tag ─────────────────────────────────────────────────────────
echo ""
echo "──── 3. 推送與 tag ────"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "  (dry-run: 不 push、不 tag)"
else
  git push origin main
  if git rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null; then
    echo "  ✓ tag v$VERSION 已存在 (指向 $(git rev-list -n1 "v$VERSION" | cut -c1-8))"
  else
    git tag -a "v$VERSION" -m "$(git log -1 --format=%s)"
    git push origin "v$VERSION"
    echo "  ✓ tag v$VERSION 已建立並推送 → CI 會建 GitHub Release"
  fi
fi

# ── 4. 同步三處 ───────────────────────────────────────────────────────────
echo ""
echo "──── 4. 同步三處 ────"
# plugin 的 manifest 是 Mavis 專屬檔, sync 會保留它 → 版本號要自己跟上。
# 不跟上的話, plugin 會對外報一個舊版本, 而它的 code 是新版本。
"$PY" ops/update_plugin_manifest_version.py "$PLUGIN_DIR/.minimax-plugin/plugin.json" || true
if [ -f "$PLUGIN_DIR/scripts/sync-from-repo.sh" ]; then
  (cd "$PLUGIN_DIR" && bash scripts/sync-from-repo.sh 2>&1 | grep -E "一致|✗" | tail -3)
else
  echo "  (略過 plugin: 找不到 $PLUGIN_DIR/scripts/sync-from-repo.sh)"
fi
bash scripts/sync-working-copy.sh 2>&1 | grep -E "一致|✗|本機獨有" | tail -3

# ── 5. 三處驗收 ───────────────────────────────────────────────────────────
echo ""
echo "──── 5. 三處驗收 ────"
for D in "$REPO_DIR" "$PLUGIN_DIR" "$WORKING_COPY"; do
  [ -d "$D" ] || continue
  if [ ! -x "$D/.venv/bin/python" ]; then
    echo "  (略過 $D: 沒有 .venv)"
    continue
  fi
  echo "  ── $(basename "$D")"
  (cd "$D" && "$D/.venv/bin/python" -m pytest 2>&1 | tail -1 | sed 's/^/     /')
  (cd "$D" && "$D/.venv/bin/python" scripts/check_equivalence_freeze.py | sed 's/^/     /')
  (cd "$D" && "$D/.venv/bin/python" scripts/check_repo_hygiene.py | sed 's/^/     /')
  (cd "$D" && "$D/.venv/bin/python" ops/check_version_line.py | sed 's/^/     /')
done

# ── 6. 三處位元組一致 ─────────────────────────────────────────────────────
echo ""
echo "──── 6. 三處位元組一致 ────"
drift=0
checked=0
while IFS= read -r -d '' f; do
  a="$(shasum -a 256 "$REPO_DIR/$f" | awk '{print $1}')"
  for D in "$PLUGIN_DIR" "$WORKING_COPY"; do
    [ -d "$D" ] || continue
    if [ ! -f "$D/$f" ]; then
      echo "  ✗ $D/$f  (缺檔)"
      drift=$((drift+1))
      continue
    fi
    b="$(shasum -a 256 "$D/$f" | awk '{print $1}')"
    checked=$((checked+1))
    if [ "$a" != "$b" ]; then
      echo "  ✗ $D/$f  (內容不同)"
      drift=$((drift+1))
    fi
  done
done < <(git ls-files -z)
if [ "$drift" -eq 0 ]; then
  echo "  ✓ $checked 個檔案在 plugin 與工作目錄都與 repo 相同"
else
  echo "  ⚠️  $drift 處不一致"
fi

echo ""
if [ "$DRY_RUN" -eq 1 ]; then
  echo "🔍 dry-run 完成, 沒有 push 也沒有 tag。"
else
  echo "🎉 發布完成: v$VERSION"
fi
exit "$drift"
