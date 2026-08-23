#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# jobs-scraper 一鍵安裝 (fail-fast, idempotent, 不覆蓋 .env/.secrets)
# 用法: ./setup.sh
# 結果: 建 .venv, 裝依賴, 跑 unit test, 印可用的 interpreter 路徑
# ─────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"

echo "🚀 jobs-scraper setup"
echo "=================================="
echo "  repo:  $REPO_ROOT"
echo "  venv:  $VENV_DIR"
echo "=================================="

# 1. 確認 Python 3.11+
if ! command -v python3 > /dev/null 2>&1; then
    echo "❌ 沒找到 python3, 請先安裝 Python 3.11+ (建議: brew install python@3.11)"
    exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "❌ 需要 Python 3.11+, 你裝的是 $PY_VERSION"
    echo "   建議: brew install python@3.11"
    exit 1
fi
echo "✅ Python $PY_VERSION"

# 2. 建 .venv (idempotent: 已存在就跳過, 不要 activate 來做後續動作)
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 建 .venv..."
    python3 -m venv "$VENV_DIR"
fi
# 不用 source activate — 後續一律用絕對 "$VENV_PY" 避免 activate 失效
if [ ! -x "$VENV_PY" ]; then
    echo "❌ venv python 不可執行: $VENV_PY"
    exit 1
fi
echo "✅ venv ready: $VENV_PY"

# 3. 裝依賴 (用 .venv python, 不依賴 activate)
echo "📦 升 pip + 裝依賴 (pyproject.toml)..."
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -e ".[dev]"
echo "✅ 依賴裝好"

# 4. 建 .secrets/ (idempotent: 不覆蓋現有)
mkdir -p "$REPO_ROOT/.secrets"
echo "✅ .secrets/ 存在 (放你的 service account JSON)"

# 5. 建 .env (idempotent: 不覆蓋現有)
if [ ! -f "$REPO_ROOT/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo "✅ 建 .env (從 .env.example, 記得編輯填 SHEET_ID / SHEET_GID / GSPREAD_SA_KEY_PATH)"
else
    echo "⏭️  .env 已存在, 跳過 (不會覆蓋你的 secrets/config)"
fi

# 6. 跑 unit test 確認安裝正確 (用 .venv python 跑, 測試失敗要 fail-fast)
echo ""
echo "🧪 跑 unit test..."
if ! "$VENV_PY" -m pytest -q; then
    echo ""
    echo "❌ test 失敗, 請把上面錯誤訊息回報給開發者"
    exit 1
fi
echo "✅ pytest 全綠"

# 7. 跑 doctor
echo ""
echo "🩺 跑 doctor..."
if ! "$VENV_PY" "$REPO_ROOT/scripts/doctor.py"; then
    echo "❌ doctor 報錯 (看上面訊息, 通常是缺 credentials, 不是 setup 失敗)"
else
    echo "✅ doctor 通過"
fi

# 8. 印使用者要在 MCP host 用的 interpreter 路徑
echo ""
echo "=================================="
echo "🎉 Setup 完成!"
echo ""
echo "📝 下一步:"
echo "  1. 把你的 service account JSON 放到 .secrets/gsheet-sa.json"
echo "  2. 編輯 .env 設 SHEET_ID / SHEET_GID (沒設 → Sheet tools 會 fail-closed 報 CONFIG_MISSING)"
echo "  3. MCP host 設定請用這條絕對路徑:"
echo ""
echo "       $VENV_PY"
echo ""
echo "  4. 第一次跑 (純 list, 不用 Google config 也行):"
echo "       $VENV_PY sg_product_jobs.py 7d --source linkedin"
echo ""
echo "📖 完整文檔: README.md + RULES.md + skills/jobs-scraper/SKILL.md"
