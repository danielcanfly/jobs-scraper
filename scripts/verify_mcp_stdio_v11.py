#!/usr/bin/env python3
"""Real MCP stdio smoke for v1.1.0: spawn server_v1_1.py and verify the five-tool contract."""
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
        args=[str(ROOT / "server_v1_1.py")],
        cwd=str(ROOT),
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            expected = {
                "crawl_jobs",
                "initialize_job_tracker",
                "sync_jobs_to_sheet",
                "audit_sheet",
                "get_stats",
            }
            assert names == expected, f"unexpected v1.1 tool set: {sorted(names)}"

            sync = next(t for t in tools.tools if t.name == "sync_jobs_to_sheet")
            props = (sync.inputSchema or {}).get("properties") or {}
            assert "region" in props
            assert "gid" not in props
            assert "sheet_id" not in props

            result = await session.call_tool("audit_sheet", arguments={"region": "SG"})
            assert result.structured_content is not None
            assert result.structured_content["ok"] is False
            assert result.structured_content["error_code"] == "CONFIG_MISSING"
            print("STDIO_MCP_V11_SMOKE_PASS", sorted(names))


if __name__ == "__main__":
    asyncio.run(run())
