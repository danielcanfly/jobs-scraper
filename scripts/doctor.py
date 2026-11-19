#!/usr/bin/env python3
"""
jobs-scraper doctor — 安裝 / 配置 / 環境健全度檢查

跑法:
    .venv/bin/python scripts/doctor.py

永遠不印 credential JSON / private key / service-account 內容。
只印 PASS / WARN / FAIL 跟 user 應該做的事。

v1.1 Sheet contract:
- GSPREAD_SA_KEY_PATH + SHEET_ID are required for Sheet tools.
- SHEET_GID is legacy-only for server.py/direct CLI and is not required by server_v1_1.py.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _version() -> str:
    """The single version source: pyproject.toml. Never hard-code it here."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else "unknown"


VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"
ENV_FILE = REPO_ROOT / ".env"

REQUIRED_SHEET_KEYS_V11 = ("GSPREAD_SA_KEY_PATH", "SHEET_ID")
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
    for mod in ("mcp", "gspread", "google", "dotenv", "curl_cffi"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return f"缺: {', '.join(missing)}", "FAIL"
    return "OK", "PASS"


def check_files() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    required = [
        (REPO_ROOT / "sg_product_jobs.py", "sg_product_jobs.py"),
        (REPO_ROOT / "server.py", "server.py (legacy v1.0 entrypoint)"),
        (REPO_ROOT / "server_v1_1.py", "server_v1_1.py"),
        (REPO_ROOT / "job_tracker.py", "job_tracker.py"),
        (REPO_ROOT / "pyproject.toml", "pyproject.toml"),
        (REPO_ROOT / "LICENSE", "LICENSE"),
        (REPO_ROOT / ".gitignore", ".gitignore"),
        (REPO_ROOT / "skills" / "jobs-scraper" / "SKILL.md", "skills/jobs-scraper/SKILL.md"),
        (
            REPO_ROOT / "skills" / "jobs-scraper" / "references" / "JOB_TRACKER_SCHEMA.md",
            "skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md",
        ),
        (REPO_ROOT / ".codex-plugin" / "plugin.json", ".codex-plugin/plugin.json"),
    ]
    for path, name in required:
        tag = "PASS" if path.exists() else "FAIL"
        out.append((tag, f"{name}: {'exists' if path.exists() else 'MISSING'}"))
    return out


def _read_env_file() -> dict[str, str]:
    """極簡 .env 解析，不讀/印任何 credential 內容。"""
    env: dict[str, str] = {}
    if not ENV_FILE.exists():
        return env
    for raw in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _effective_env(keys: tuple[str, ...]) -> dict[str, str]:
    file_env = _read_env_file()
    out: dict[str, str] = {}
    for key in keys:
        # Process env wins only when explicitly non-empty. This keeps a populated
        # local .env usable when CI/hosts export an empty placeholder variable.
        process_value = os.getenv(key)
        if process_value is not None and process_value.strip():
            out[key] = process_value.strip()
        else:
            out[key] = file_env.get(key, "").strip()
    return out


def check_sheet_config() -> tuple[str, str]:
    """v1.1 fail-closed config: SA key path + SHEET_ID; GID is legacy-only."""
    proc_env = _effective_env(REQUIRED_SHEET_KEYS_V11)
    missing = [k for k in REQUIRED_SHEET_KEYS_V11 if not proc_env.get(k, "")]
    if missing:
        return (
            f"未設定: {', '.join(missing)} — crawl_jobs 仍可用；Sheet tools 會 fail closed。SHEET_GID 不需設定",
            "WARN",
        )

    sa = proc_env["GSPREAD_SA_KEY_PATH"]
    sa_path = Path(sa) if Path(sa).is_absolute() else (REPO_ROOT / sa)
    if not sa_path.exists():
        return (f"credential file 不存在: {sa_path}", "WARN")
    return "OK (v1.1 uses SHEET_ID; worksheet GID resolved by region)", "PASS"


def check_proxy() -> tuple[str, str]:
    """v1.6.3: 爬蟲走不走 proxy, 以及那個 proxy 還活著嗎。

    2026-11-19 實測: LinkedIn Guest API 對直連回 451, 走本地 proxy 就正常;
    Google Sheets API 在某些網路區段直連會 timeout, 同樣要靠 proxy。
    一個掛掉的 proxy 比直連更難診斷, 所以 doctor 直接探一次 port。
    """
    env = _effective_env(("JOBS_SCRAPER_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"))
    proxy = ""
    source_key = ""
    for key in ("JOBS_SCRAPER_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        if env.get(key):
            proxy = env[key]
            source_key = key
            break
    if not proxy:
        return "直連 (no proxy configured) — 若來源回 451/timeout, 設 JOBS_SCRAPER_PROXY 或 HTTPS_PROXY", "WARN"

    url = proxy if "://" in proxy else f"http://{proxy}"
    host, _, port = url.split("://", 1)[1].partition(":")
    host = host.split("/")[0]
    try:
        port_num = int(port) if port else (443 if url.startswith("https") else 80)
    except ValueError:
        port_num = 80
    try:
        with socket.create_connection((host, port_num), timeout=2):
            return f"{source_key}={proxy} (可連線)", "PASS"
    except OSError as e:
        return f"{source_key}={proxy} (連不上: {type(e).__name__}) — 來源會直接失敗, 不是直連能救", "FAIL"


def check_no_secrets_in_git() -> tuple[str, str]:
    """檢查 .env / service-account secret 沒被 git 追蹤。"""
    try:
        import subprocess

        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env", ".secrets/gsheet-sa.json"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return ("git ls-files 跑不動 (no-git or 不在 repo)", "WARN")
    if out.returncode == 0:
        return (".env 或 .secrets/gsheet-sa.json 被 git 追蹤，請修 .gitignore", "FAIL")
    return "OK (no secrets tracked)", "PASS"


def main() -> int:
    print(f"🩺 jobs-scraper v{_version()} doctor")
    print("=" * 60)
    order = {"PASS": 0, "WARN": 1, "FAIL": 2}
    worst = "PASS"

    py, tag = check_python()
    line(tag, f"Python: {py} (need >= 3.11)")
    worst = max(worst, tag, key=order.get)

    tag = "PASS" if VENV_PY.exists() else "WARN"
    line(tag, f"venv interpreter: {VENV_PY} ({'exists' if VENV_PY.exists() else 'missing — run setup.sh'})")
    worst = max(worst, tag, key=order.get)

    msg, tag = check_imports()
    line(tag, f"imports: {msg}")
    worst = max(worst, tag, key=order.get)

    for tag, msg in check_files():
        line(tag, f"file: {msg}")
        worst = max(worst, tag, key=order.get)

    msg, tag = check_sheet_config()
    line(tag, f"sheet config: {msg}")
    worst = max(worst, tag, key=order.get)

    msg, tag = check_no_secrets_in_git()
    line(tag, f"git hygiene: {msg}")
    worst = max(worst, tag, key=order.get)

    msg, tag = check_proxy()
    line(tag, f"proxy: {msg}")
    worst = max(worst, tag, key=order.get)

    print("=" * 60)
    if worst == "PASS":
        print("🎉 doctor: all green")
        return EXIT_OK
    if worst == "WARN":
        print("⚠️  doctor: warnings only (public-source crawl works; Sheet tools need user-owned Sheet config)")
        return EXIT_WARN
    print("❌ doctor: at least one FAIL")
    return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
