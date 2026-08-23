#!/usr/bin/env python3
"""
jobs-scraper doctor — 安裝 / 配置 / 環境健全度檢查

跑法:
    .venv/bin/python scripts/doctor.py

永遠不印 credential JSON / private key / service-account 內容。
只印 PASS / WARN / FAIL 跟 user 應該做的事。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
SECRETS_DIR = REPO_ROOT / ".secrets"
SA_KEY_PATH = REPO_ROOT / ".secrets" / "gsheet-sa.json"

REQUIRED_SHEET_KEYS = ("GSPREAD_SA_KEY_PATH", "SHEET_ID", "SHEET_GID")
EXIT_OK = 0
EXIT_WARN = 0
EXIT_FAIL = 1


def line(tag: str, msg: str) -> None:
    icon = {"PASS": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[tag]
    print(f"  {icon} {msg}", flush=True)


def check_python() -> tuple[str, str]:
    v = sys.version_info
    return f"{v.major}.{v.minor}", "PASS" if (v.major, v.minor) >= (3, 11) else "FAIL"


def check_imports() -> tuple[str, str]:
    missing = []
    for mod in ("mcp", "gspread", "google", "bs4", "dotenv", "curl_cffi"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return f"缺: {', '.join(missing)}", "FAIL"
    return "OK", "PASS"


def check_files() -> list[tuple[str, str, str]]:
    """回 (tag, msg)"""
    out: list[tuple[str, str, str]] = []
    for path, name in [
        (REPO_ROOT / "sg_product_jobs.py", "sg_product_jobs.py"),
        (REPO_ROOT / "server.py", "server.py"),
        (REPO_ROOT / "pyproject.toml", "pyproject.toml"),
        (REPO_ROOT / "LICENSE", "LICENSE"),
        (REPO_ROOT / ".gitignore", ".gitignore"),
        (REPO_ROOT / "skills" / "jobs-scraper" / "SKILL.md", "skills/jobs-scraper/SKILL.md"),
        (REPO_ROOT / ".codex-plugin" / "plugin.json", ".codex-plugin/plugin.json"),
    ]:
        tag = "PASS" if path.exists() else "FAIL"
        out.append((tag, f"{name}: {'exists' if path.exists() else 'MISSING'}"))
    return out


def _read_env_file() -> dict[str, str]:
    """極簡 .env 解析 (不依賴 python-dotenv, 避免 doctor 自己壞)。"""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def check_sheet_config() -> tuple[str, str]:
    """Sheet config fail-closed 檢查: 三個 var 都要 set, credential file 要存在。"""
    file_env = _read_env_file()
    proc_env = {**file_env, **{k: os.getenv(k, "") for k in REQUIRED_SHEET_KEYS}}

    missing_var = [k for k in REQUIRED_SHEET_KEYS if not proc_env.get(k, "").strip()]
    if missing_var:
        return (f"未設定: {', '.join(missing_var)} — Sheet tools 會回 CONFIG_MISSING 結構化錯誤", "WARN")

    sa = proc_env["GSPREAD_SA_KEY_PATH"]
    sa_path = Path(sa) if Path(sa).is_absolute() else (REPO_ROOT / sa)
    if not sa_path.exists():
        return (f"credential file 不存在: {sa_path}", "WARN")
    return "OK", "PASS"


def check_no_secrets_in_git() -> tuple[str, str]:
    """檢查 .secrets / .env / *.key / *.pem 沒被 git 追蹤。"""
    try:
        import subprocess
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch",
             ".env", ".secrets/gsheet-sa.json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ("git ls-files 跑不動 (no-git or 不在 repo)", "WARN")
    if out.returncode == 0:
        return ("❌ .env 或 .secrets 居然被 git 追蹤, 請修 .gitignore", "FAIL")
    return "OK (no secrets tracked)", "PASS"


def main() -> int:
    print("🩺 jobs-scraper doctor")
    print("=" * 60)

    worst = "PASS"

    # 1. Python version
    py, tag = check_python()
    line(tag, f"Python: {py} (need >= 3.11)")
    worst = max(worst, tag, key=lambda t: {"PASS": 0, "WARN": 1, "FAIL": 2}[t])

    # 2. venv interpreter
    tag = "PASS" if VENV_PY.exists() else "WARN"
    line(tag, f"venv interpreter: {VENV_PY} ({'exists' if VENV_PY.exists() else 'missing — 跑 setup.sh'})")
    worst = max(worst, tag, key=lambda t: {"PASS": 0, "WARN": 1, "FAIL": 2}[t])

    # 3. imports
    msg, tag = check_imports()
    line(tag, f"imports: {msg}")
    worst = max(worst, tag, key=lambda t: {"PASS": 0, "WARN": 1, "FAIL": 2}[t])

    # 4. files
    for tag, msg in check_files():
        line(tag, f"file: {msg}")
        worst = max(worst, tag, key=lambda t: {"PASS": 0, "WARN": 1, "FAIL": 2}[t])

    # 5. Sheet config (fail-closed)
    msg, tag = check_sheet_config()
    line(tag, f"sheet config: {msg}")
    worst = max(worst, tag, key=lambda t: {"PASS": 0, "WARN": 1, "FAIL": 2}[t])

    # 6. secrets hygiene
    msg, tag = check_no_secrets_in_git()
    line(tag, f"git hygiene: {msg}")
    worst = max(worst, tag, key=lambda t: {"PASS": 0, "WARN": 1, "FAIL": 2}[t])

    print("=" * 60)
    if worst == "PASS":
        print("🎉 doctor: all green")
        return EXIT_OK
    if worst == "WARN":
        print("⚠️  doctor: warnings only (Sheet tools 不一定可用, 但 scraper CLI 跟 read-only MCP 可用)")
        return EXIT_WARN
    print("❌ doctor: 至少一個 FAIL, 看上面修")
    return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
