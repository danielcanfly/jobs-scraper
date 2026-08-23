#!/usr/bin/env python3
"""Real MCP stdio smoke: spawn server.py, initialize, list tools, call fail-closed tool."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent


async def run() -> None:
    env = dict(os.environ)
    env.update({"SHEET_ID": "", "SHEET_GID": "", "GSPREAD_SA_KEY_PATH": ""})
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        cwd=str(ROOT),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {"crawl_jobs", "sync_jobs_to_sheet", "audit_sheet", "get_stats"}
            missing = expected - names
            assert not missing, f"missing tools over stdio: {sorted(missing)}"
            result = await session.call_tool("audit_sheet", arguments={})
            assert result.structured_content is not None
            assert result.structured_content["ok"] is False
            assert result.structured_content["error_code"] == "CONFIG_MISSING"
            print("STDIO_MCP_SMOKE_PASS", sorted(names))


if __name__ == "__main__":
    asyncio.run(run())
