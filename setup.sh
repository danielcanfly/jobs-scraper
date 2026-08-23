#!/usr/bin/env bash
# jobs-scraper v1.1.0 one-shot local setup (fail-fast, idempotent, preserves .env/.secrets)
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
VENV_DIR="$REPO_ROOT/.venv"
VENV_PY="$VENV_DIR/bin/python"

echo "🚀 jobs-scraper v1.1.0 setup"
echo "=================================="
echo "  repo:  $REPO_ROOT"
echo "  venv:  $VENV_DIR"
echo "=================================="

# 1. Python 3.11+
if ! command -v python3 > /dev/null 2>&1; then
    echo "❌ python3 not found; install Python 3.11+"
    exit 1
fi
PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "❌ Python 3.11+ required; found $PY_VERSION"
    exit 1
fi
echo "✅ Python $PY_VERSION"

# 2. Create/reuse venv
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 creating .venv..."
    python3 -m venv "$VENV_DIR"
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
echo "MCP v1.1.0 STDIO command:"
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
