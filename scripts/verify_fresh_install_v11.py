#!/usr/bin/env python3
"""Extend the qualified fresh-install harness with v1.1.x MCP checks in the same clean copy."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from verify_fresh_install import main as verify_legacy_fresh_install


def _run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)


def main() -> int:
    dst = Path(tempfile.mkdtemp(prefix="jobs-scraper-v11-fresh-")).resolve()
    legacy_rc = verify_legacy_fresh_install(str(dst))
    if legacy_rc != 0:
        print("FAIL: legacy fresh-install gate failed before v1.1 checks")
        return legacy_rc

    vpy = dst / ".venv" / "bin" / "python"
    script = dst / "_list_v11_tools.py"
    script.write_text(
        "import asyncio, server_v1_1\n"
        "from importlib.metadata import version as package_version\n"
        "async def go():\n"
        "    tools = await server_v1_1.mcp.list_tools()\n"
        "    names = sorted(t.name for t in tools)\n"
        "    print('v1.1 tools:', names)\n"
        "    need = ['audit_sheet','crawl_jobs','get_stats','initialize_job_tracker','sync_jobs_to_sheet']\n"
        "    assert names == need, (names, need)\n"
        "    expected_version = package_version('jobs-scraper')\n"
        "    assert server_v1_1.mcp.version == expected_version, (server_v1_1.mcp.version, expected_version)\n"
        "asyncio.run(go())\n",
        encoding="utf-8",
    )
    r = _run([str(vpy), str(script)], dst, timeout=30)
    if r.returncode != 0:
        print(f"FAIL: v1.1 import/tool list: {r.stdout}\n{r.stderr}")
        return 1
    script.unlink()
    print(f"[fresh-install-v1.1] {r.stdout.strip()}")

    r = _run([str(vpy), "scripts/verify_mcp_stdio_v11.py"], dst, timeout=60)
    if r.returncode != 0:
        print(f"FAIL: v1.1 STDIO smoke: {r.stdout}\n{r.stderr}")
        return 1
    print(f"[fresh-install-v1.1] {r.stdout.strip()}")
    print("FRESH_INSTALL_V11_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
