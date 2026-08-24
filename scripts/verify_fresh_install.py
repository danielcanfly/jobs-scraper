#!/usr/bin/env python3
"""
Fresh-install qualification harness.

跑法:
    .venv/bin/python scripts/verify_fresh_install.py [target_dir]

預設行為: 把當前 repo 複製到 temp dir, 建全新 venv, 從 pyproject.toml 裝依賴,
跑 compile + unit test + import server + 列 MCP tools (不需 Google creds)。

任何失敗 → exit 1, 不動 production 環境。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, timeout=timeout,
    )


def _find_python_311() -> str | None:
    """Find a Python 3.11+ interpreter.

    Order:
      1. Same dir as current interpreter (so a venv that already has 3.11+ can re-use itself)
      2. Common absolute paths (pyenv / homebrew / system)
      3. shutil.which for python3.12/3.11/3.10/python3
    """
    here = Path(sys.executable).parent
    candidates: list[str] = []
    # 1. Same dir as the current interpreter (the venv this script is running in)
    for name in ("python3.12", "python3.11", "python3.10", "python3", "python"):
        candidates.append(str(here / name))
    # 2. Common absolute paths
    for prefix in ("/usr/local/bin", "/opt/homebrew/bin"):
        for name in ("python3.12", "python3.11", "python3.10", "python3"):
            candidates.append(f"{prefix}/{name}")
    # 3. pyenv shims — look for any 3.11+ version installed
    pyenv_root = os.environ.get("PYENV_ROOT", str(Path.home() / ".pyenv"))
    versions_dir = Path(pyenv_root) / "versions"
    if versions_dir.is_dir():
        for ver in sorted(versions_dir.iterdir(), reverse=True):
            if not ver.is_dir():
                continue
            bin_py = ver / "bin" / "python3"
            if bin_py.exists():
                candidates.append(str(bin_py))
    # 4. shutil.which as last resort
    for name in ("python3.12", "python3.13", "python3.11", "python3.10", "python3"):
        p = shutil.which(name)
        if p:
            candidates.append(p)
    seen: set[str] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if not Path(c).exists():
            continue
        r = _run([c, "-c", "import sys; print(sys.version_info.major, sys.version_info.minor)"], timeout=5)
        if r.returncode == 0:
            parts = r.stdout.strip().split()
            if len(parts) == 2:
                try:
                    major, minor = int(parts[0]), int(parts[1])
                except ValueError:
                    continue
                if (major, minor) >= (3, 11):
                    return c
    return None


def main(target_dir: str | None = None) -> int:
    src = REPO_ROOT
    if target_dir:
        dst = Path(target_dir).resolve()
        dst.mkdir(parents=True, exist_ok=True)
    else:
        dst = Path(tempfile.mkdtemp(prefix="jobs-scraper-fresh-")).resolve()
    print(f"[fresh-install] src={src}  dst={dst}")

    # 1. 複製 repo (排除 .venv / .secrets / __pycache__ / .git)
    for child in src.iterdir():
        if child.name in {".venv", ".secrets", "__pycache__", ".git", "node_modules"}:
            continue
        s = child
        d = dst / child.name
        if s.is_dir():
            shutil.copytree(s, d, dirs_exist_ok=True, ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".venv", ".secrets"
            ))
        else:
            shutil.copy2(s, d)
    print("[fresh-install] copied")

    # 2. 建全新 venv (用 Python 3.11+)
    venv = dst / ".venv"
    py = _find_python_311()
    if not py:
        print("FAIL: no Python 3.11+ interpreter on PATH (tried python3.12/3.11/3.10/python3)")
        return 1
    r = _run([py, "-m", "venv", str(venv)], timeout=60)
    if r.returncode != 0:
        print(f"FAIL: venv create: {r.stderr}")
        return 1
    vpy = venv / "bin" / "python"
    print(f"[fresh-install] venv: {vpy} (using {py})")

    # 3. 裝依賴
    r = _run([str(vpy), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], timeout=120)
    if r.returncode != 0:
        print(f"FAIL: pip upgrade: {r.stderr}")
        return 1
    r = _run([str(vpy), "-m", "pip", "install", "--quiet", "-e", f"{dst}[dev]"], timeout=600)
    if r.returncode != 0:
        print(f"FAIL: pip install -e .[dev]: {r.stderr}")
        print(r.stdout)
        return 1
    print("[fresh-install] deps installed (incl. pytest from [dev])")

    # 4. compileall
    r = _run([str(vpy), "-m", "compileall", "-q", str(dst)], timeout=60)
    if r.returncode != 0:
        print(f"FAIL: compileall: {r.stderr}")
        return 1
    print("[fresh-install] compile OK")

    # 5. full pytest discovery (includes root helper regressions + contract tests)
    r = _run([str(vpy), "-m", "pytest", "-q", str(dst)], timeout=120)
    if r.returncode != 0:
        print(f"FAIL: pytest: {r.stdout}\n{r.stderr}")
        return 1
    print("[fresh-install] pytest OK")

    # 6. import server (確認 MCP v2 走得通)
    r = _run(
        [str(vpy), "-c", "import server; import inspect; m=inspect.getsource(server); assert 'MCPServer' in m, 'no MCPServer in server.py'; print('server import OK')"],
        cwd=str(dst), timeout=30,
    )
    if r.returncode != 0:
        print(f"FAIL: import server: {r.stdout}\n{r.stderr}")
        return 1
    print("[fresh-install] server import OK")

    # 7. 列 MCP tools (不需 Google creds, async list_tools in MCP v2)
    # Use a temp file because multi-line -c needs careful escaping
    list_tools_script = dst / "_list_tools.py"
    list_tools_script.write_text(
        "import asyncio, server\n"
        "async def go():\n"
        "    tools = await server.mcp.list_tools()\n"
        "    names = sorted(t.name for t in tools)\n"
        "    print('tools:', names)\n"
        "    need = ['crawl_jobs', 'sync_jobs_to_sheet', 'audit_sheet', 'get_stats']\n"
        "    missing = [n for n in need if n not in names]\n"
        "    assert not missing, f'missing: {missing}'\n"
        "asyncio.run(go())\n",
        encoding="utf-8",
    )
    r = _run([str(vpy), str(list_tools_script)], cwd=str(dst), timeout=30)
    if r.returncode != 0:
        print(f"FAIL: list tools: {r.stdout}\n{r.stderr}")
        return 1
    print(f"[fresh-install] MCP tools listed: {r.stdout.strip()}")
    list_tools_script.unlink()

    # 8. validate SKILL.md frontmatter 結構 (deterministic, 沒裝 skills-ref 也能跑)
    skill = dst / "skills" / "jobs-scraper" / "SKILL.md"
    if not skill.exists():
        print("FAIL: skills/jobs-scraper/SKILL.md missing")
        return 1
    text = skill.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        print("FAIL: SKILL.md missing YAML frontmatter start")
        return 1
    end = text.find("\n---\n", 4)
    if end < 0:
        print("FAIL: SKILL.md frontmatter not closed")
        return 1
    fm = text[4:end]
    for key in ("name:", "description:"):
        if key not in fm:
            print(f"FAIL: SKILL.md frontmatter missing {key}")
            return 1
    if "name: jobs-scraper" not in fm:
        print("FAIL: SKILL.md name != jobs-scraper")
        return 1
    print("[fresh-install] SKILL.md frontmatter OK")

    print(f"\n🎉 fresh install qualified at {dst}")
    return 0


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else None
    raise SystemExit(main(tgt))
