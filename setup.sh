#!/usr/bin/env bash
# jobs-scraper one-shot local setup (fail-fast, idempotent, preserves .env/.secrets)
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"

# 1. Python 3.11+
# 不要假設 `python3` 就是夠新的版本 — 很多機器上 python3 是系統預設的 3.9,
# 而 3.11+ 另外裝在 /opt/homebrew/bin、/usr/local/bin 或 pyenv 之類的地方,
# 而且那些目錄不一定在 PATH 上。所以名稱跟常見路徑都找一遍。
PY_CANDIDATES="python3.13 python3.12 python3.11 python3 python"
for extra in \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3; do
    [ -x "$extra" ] && PY_CANDIDATES="$PY_CANDIDATES $extra"
done
for pyenv_py in "$HOME"/.pyenv/versions/*/bin/python; do
    [ -x "$pyenv_py" ] && PY_CANDIDATES="$PY_CANDIDATES $pyenv_py"
done

PY_BIN=""
PY_VERSION=""
for cand in $PY_CANDIDATES; do
    case "$cand" in
        */*) [ -x "$cand" ] || continue ;;
        *) command -v "$cand" > /dev/null 2>&1 || continue ;;
    esac
    cand_version="$("$cand" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2> /dev/null)" || continue
    cand_major="${cand_version%%.*}"
    cand_minor="${cand_version##*.}"
    if [ "$cand_major" -gt 3 ] || { [ "$cand_major" -eq 3 ] && [ "$cand_minor" -ge 11 ]; }; then
        PY_BIN="$cand"
        PY_VERSION="$cand_version"
        break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "❌ Python 3.11+ required; none of the candidates is 3.11+:"
    echo "   $PY_CANDIDATES"
    exit 1
fi
echo "✅ Python $PY_VERSION ($PY_BIN)"

# 單一版本來源: 版本號只認 pyproject.toml, 不在這裡硬寫一份。
JOBS_SCRAPER_VERSION="$("$PY_BIN" - <<'PY'
import re, sys
try:
    import tomllib
except ModuleNotFoundError:
    text = open("pyproject.toml", encoding="utf-8").read()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    print(match.group(1) if match else "unknown")
else:
    print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])
PY
)"

echo "🚀 jobs-scraper v$JOBS_SCRAPER_VERSION setup"
echo "=================================="
echo "  repo:  $REPO_ROOT"
echo "  venv:  $VENV_DIR"
echo "=================================="

# 2. Create/reuse venv
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 creating .venv..."
    "$PY_BIN" -m venv "$VENV_DIR"
fi
if [ ! -x "$VENV_PY" ]; then
    echo "❌ venv python not executable: $VENV_PY"
    exit 1
fi
echo "✅ venv ready: $VENV_PY"

# 3. Install package + dev tests
"$VENV_PY" -m pip install --quiet --upgrade pip
"$VENV_PY" -m pip install --quiet -e ".[dev]"
echo "✅ dependencies installed"

# 4. Secrets dir
mkdir -p "$REPO_ROOT/.secrets"
echo "✅ .secrets/ ready"

# 5. Create .env without overwriting user config
if [ ! -f "$REPO_ROOT/.env" ]; then
    cp "$REPO_ROOT/.env.example" "$REPO_ROOT/.env"
    echo "✅ created .env; fill SHEET_ID and GSPREAD_SA_KEY_PATH for Sheet tools"
else
    echo "⏭️  .env already exists; preserved"
fi

# 6. Tests
printf '\n🧪 running tests...\n'
if ! "$VENV_PY" -m pytest -q; then
    echo "❌ tests failed"
    exit 1
fi
echo "✅ pytest green"

# 7. Doctor (may report missing optional Google config)
printf '\n🩺 running doctor...\n'
if ! "$VENV_PY" "$REPO_ROOT/scripts/doctor.py"; then
    echo "⚠️ doctor reported an environment/config issue; setup itself completed"
else
    echo "✅ doctor passed"
fi

# 8. Final host instructions
printf '\n==================================\n'
echo "🎉 Setup complete"
echo ""
echo "MCP v$JOBS_SCRAPER_VERSION STDIO command:"
echo "  $VENV_PY $REPO_ROOT/server_v1_1.py"
echo ""
echo "First crawl (no Google config required):"
echo "  $VENV_PY $REPO_ROOT/sg_product_jobs.py 7d --source linkedin"
echo ""
echo "For Google Sheet onboarding:"
echo "  1. Put your service-account JSON at .secrets/gsheet-sa.json (or configure GSPREAD_SA_KEY_PATH)."
echo "  2. Share your blank/existing spreadsheet with that service-account email."
echo "  3. Set SHEET_ID in .env. SHEET_GID is NOT required by server_v1_1.py."
echo "  4. In the MCP host, call initialize_job_tracker with dry_run=true first."
echo "  5. After reviewing the plan, explicitly initialize with dry_run=false."
echo ""
echo "Default tracker pairs: SG-Raw/SG-Selected, TW-Raw/TW-Selected, China-Raw/China-Selected"
echo "📖 Docs: README.md + skills/jobs-scraper/SKILL.md + skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md"
