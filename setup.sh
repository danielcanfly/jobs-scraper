#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# jobs-scraper 一鍵安裝
# 用法: ./setup.sh
# 結果: 裝依賴, 建 .secrets/ 資料夾, 複製 .env.example 成 .env, 跑 unit test
# ─────────────────────────────────────────────────────────────

set -e

echo "🚀 jobs-scraper setup"
echo "=================================="

# 1. 確認 Python 3.11+
PYTHON=$(python3 --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PYTHON" | cut -d. -f1)
PY_MINOR=$(echo "$PYTHON" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]); then
    echo "❌ 需要 Python 3.11+, 你裝的是 $PYTHON"
    echo "   建議: brew install python@3.11"
    exit 1
fi
echo "✅ Python $PYTHON"

# 2. 建 venv (避免污染系統 Python)
if [ ! -d ".venv" ]; then
    echo "📦 建 venv..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "✅ venv activated: $(which python)"

# 3. 裝依賴
echo "📦 裝依賴 (pip install -r requirements.txt)..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✅ 依賴裝好"

# 4. 建 .secrets/ 資料夾
mkdir -p .secrets
echo "✅ .secrets/ 存在 (把 service account JSON 放這)"

# 5. 複製 .env.example → .env (如果 .env 不存在)
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ 建 .env (從 .env.example 複製, 記得編輯填 SHEET_ID)"
else
    echo "⏭️  .env 已存在, 跳過"
fi

# 6. 跑 unit test 確認安裝正確
echo ""
echo "🧪 跑 unit test..."
if python test_helpers.py 2>&1 | tail -3; then
    echo "✅ 27/27 test 通過, 安裝成功"
else
    echo "❌ test 失敗, 請貼錯誤訊息給開發者"
    exit 1
fi

echo ""
echo "=================================="
echo "🎉 Setup 完成!"
echo ""
echo "📝 下一步:"
echo "  1. 把你的 service account JSON 放到 .secrets/gsheet-sa.json"
echo "     (從 Google Cloud Console 下載, 細節見 README.md)"
echo ""
echo "  2. 編輯 .env 填入:"
echo "     - SHEET_ID (你的 Google Sheet ID)"
echo "     - SHEET_GID (sheet tab 編號, 通常 0)"
echo ""
echo "  3. 第一次跑:"
echo "     python sg_product_jobs.py 7d --source linkedin --with-jd --to-sheet <URL>"
echo ""
echo "  4. 跑 unit test 確認沒壞:"
echo "     python test_helpers.py"
echo ""
echo "📖 完整文檔: README.md + RULES.md"
