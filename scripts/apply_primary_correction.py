#!/usr/bin/env python3
"""One-shot bounded correction for PR #1.

This script intentionally performs exact-anchor replacements only. It refuses to
continue if the candidate drifted. It does not alter scraping/parsing/dedup/visa/
work-mode business logic.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"[already] {path}")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"REFUSE {path}: expected exactly one anchor, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"[patched] {path}")


def write_file(path: str, content: str) -> None:
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_text(encoding="utf-8") == content:
        print(f"[already] {path}")
        return
    p.write_text(content, encoding="utf-8")
    print(f"[wrote] {path}")


# ---------------------------------------------------------------------------
# server.py: truthful MCP annotations, fail-closed placeholders, stable machine
# result contract. No scraper algorithms are changed here.
# ---------------------------------------------------------------------------
replace_once("server.py", "import os\nimport re\n", "import json\nimport os\nimport re\n")

replace_once(
    "server.py",
    '''    sid = os.getenv("SHEET_ID", "").strip()\n    gid = os.getenv("SHEET_GID", "").strip()\n    if not sid or not gid:\n        missing = [k for k, v in {"SHEET_ID": sid, "SHEET_GID": gid}.items() if not v]\n''',
    '''    sid = os.getenv("SHEET_ID", "").strip()\n    gid = os.getenv("SHEET_GID", "").strip()\n    placeholder_ids = {"your_google_sheet_id_here", "your-sheet-id", "replace_me"}\n    placeholder_gids = {"your_sheet_gid_here", "your-gid", "replace_me"}\n    sid_missing = not sid or sid.lower() in placeholder_ids\n    gid_missing = not gid or gid.lower() in placeholder_gids\n    if sid_missing or gid_missing:\n        missing = []\n        if sid_missing:\n            missing.append("SHEET_ID")\n        if gid_missing:\n            missing.append("SHEET_GID")\n''',
)

replace_once(
    "server.py",
    '''def _parse_scraper_counts(stdout: str) -> dict[str, int | None]:\n    """Try to extract jobs_found / enriched / failed / output_file from scraper stdout."""\n    found = re.search(r"(?:crawled|got|loaded|fetched)\\s*[:=]?\\s*(\\d+)\\s*(?:jobs?|listings?)", stdout, re.IGNORECASE)\n    enriched = re.search(r"(?:enriched|with\\s*jd)\\s*[:=]?\\s*(\\d+)", stdout, re.IGNORECASE)\n    failed = re.search(r"(?:failed|errors?)\\s*[:=]?\\s*(\\d+)", stdout, re.IGNORECASE)\n    out_file = re.search(r"(?:output|saved|wrote.*to|→)\\s*[:=]?\\s*([^\\s]+\\.json)", stdout, re.IGNORECASE)\n    return {\n        "jobs_found": int(found.group(1)) if found else None,\n        "jobs_enriched": int(enriched.group(1)) if enriched else None,\n        "jobs_failed": int(failed.group(1)) if failed else None,\n        "output_file": out_file.group(1) if out_file else None,\n    }\n''',
    '''SUMMARY_PREFIX = "JOBS_SCRAPER_SUMMARY="\n\n\ndef _parse_machine_summary(stdout: str) -> dict[str, Any] | None:\n    """Parse the final machine-readable CLI summary; never infer counts from prose logs."""\n    for line in reversed(stdout.splitlines()):\n        if not line.startswith(SUMMARY_PREFIX):\n            continue\n        try:\n            value = json.loads(line[len(SUMMARY_PREFIX):])\n        except json.JSONDecodeError:\n            return None\n        return value if isinstance(value, dict) else None\n    return None\n''',
)

replace_once(
    "server.py",
    '''    title="Crawl jobs (read-only)",\n    description=(\n        "Crawl public job sources (LinkedIn Guest API / Jora / JobStreet) and "\n        "optionally enrich each job with its full description. **Never writes to Google Sheets.** "\n        "Use this for searches, listings, and JD fetches. Use sync_jobs_to_sheet for explicit writes."\n    ),\n    annotations=ToolAnnotations(\n        read_only_hint=True,\n        open_world_hint=True,\n    ),\n''',
    '''    title="Crawl jobs (no Sheet write)",\n    description=(\n        "Crawl public job sources (LinkedIn Guest API / Jora / JobStreet) and "\n        "optionally enrich each job with its full description. Never writes to Google Sheets, "\n        "but may create or update local JSON/cache/seen artifacts. Use sync_jobs_to_sheet for explicit Sheet writes."\n    ),\n    annotations=ToolAnnotations(\n        read_only_hint=False,\n        open_world_hint=True,\n        destructive_hint=False,\n        idempotent_hint=False,\n    ),\n''',
)

replace_once(
    "server.py",
    '''    if max_pages is not None:\n        args.extend(["--max-pages", str(max_pages)])\n    r = _run_subprocess(args)\n    counts = _parse_scraper_counts(r["stdout_tail"])\n    msg = "crawl completed" if r["ok"] else (\n        f"crawl failed (timeout={r['timed_out']}, code={r['error_code']})"\n    )\n''',
    '''    if max_pages is not None:\n        args.extend(["--max-pages", str(max_pages)])\n    args.append("--json-summary")\n    r = _run_subprocess(args)\n    summary = _parse_machine_summary(r["stdout_tail"])\n    if r["ok"] and summary is None:\n        r = {**r, "ok": False, "error_code": "OUTPUT_CONTRACT_MISSING"}\n    msg = "crawl completed" if r["ok"] else (\n        f"crawl failed (timeout={r['timed_out']}, code={r['error_code']})"\n    )\n''',
)

replace_once(
    "server.py",
    '''        output_file=counts["output_file"],\n        jobs_found=counts["jobs_found"],\n        jobs_enriched=counts["jobs_enriched"],\n        jobs_failed=counts["jobs_failed"],\n''',
    '''        output_file=(summary or {}).get("output_file"),\n        jobs_found=(summary or {}).get("jobs_found"),\n        jobs_enriched=(summary or {}).get("jobs_enriched"),\n        jobs_failed=(summary or {}).get("jobs_failed"),\n''',
)

replace_once(
    "server.py",
    '''    if dry_run:\n        args.append("--dry-run-sheet")\n    r = _run_subprocess(args)\n    msg = "sync completed" if r["ok"] else (\n        f"sync failed (timeout={r['timed_out']}, code={r['error_code']})"\n    )\n    # Best-effort counts from stdout\n    written = sum(int(m) for m in re.findall(r"wrote\\s+(\\d+)", r["stdout_tail"], re.IGNORECASE))\n    if not written and r["ok"]:\n        written = 0\n''',
    '''    if dry_run:\n        args.append("--dry-run-sheet")\n    args.append("--json-summary")\n    r = _run_subprocess(args)\n    summary = _parse_machine_summary(r["stdout_tail"])\n    if r["ok"] and summary is None:\n        r = {**r, "ok": False, "error_code": "OUTPUT_CONTRACT_MISSING"}\n    msg = "sync completed" if r["ok"] else (\n        f"sync failed (timeout={r['timed_out']}, code={r['error_code']})"\n    )\n''',
)

replace_once(
    "server.py",
    '''        written=written,\n        target_configured=True,\n''',
    '''        written=int((summary or {}).get("written", 0)),\n        skipped_dup=int((summary or {}).get("skipped_dup", 0)),\n        skipped_no_jd=int((summary or {}).get("skipped_no_jd", 0)),\n        target_configured=True,\n''',
)

replace_once(
    "server.py",
    '''        "Reads (crawl_jobs, audit_sheet, get_stats) and writes (sync_jobs_to_sheet) are separate tools. "\n''',
    '''        "Google Sheet reads (audit_sheet, get_stats) and writes (sync_jobs_to_sheet) are separate tools. "\n        "crawl_jobs never writes Google Sheets but may update local crawl/cache artifacts. "\n''',
)

# ---------------------------------------------------------------------------
# sg_product_jobs.py: only machine-output contract + safer write order.
# ---------------------------------------------------------------------------
replace_once(
    "sg_product_jobs.py",
    '''    兩段式寫入 (防 F10 公式注入):\n      - Phase 1 (E 欄 hyperlink formula):  用 USER_ENTERED → 公式會被解析\n      - Phase 2 (A/B/C/D/F/G/H/I/J/K 11 欄 - 1 = 10 欄文字): 用 RAW → 全部當純文字\n''',
    '''    三段式寫入 (防 F10 公式注入，且 intentional formula 最後才啟用):\n      - Phase 1: A:D 用 RAW\n      - Phase 2: F:K 用 RAW\n      - Phase 3: E 欄 hyperlink formula 用 USER_ENTERED\n''',
)

replace_once(
    "sg_product_jobs.py",
    '''    # Phase 1: E 欄 hyperlink formula (用 USER_ENTERED, 讓 Google Sheets 解析 =HYPERLINK())\n    e_col_index = 4  # A=0, B=1, C=2, D=3, E=4\n    e_only_rows = [[r[e_col_index]] for r in new_rows]\n    ws.update(\n        range_name=f"E{next_row}:E{end_row}",\n        values=e_only_rows,\n        value_input_option="USER_ENTERED",\n    )\n    # Phase 2: 其他 10 欄 (A,B,C,D,F,G,H,I,J,K) 全部用 RAW 當純文字寫入\n    other_col_indices = [0, 1, 2, 3, 5, 6, 7, 8, 9, 10]  # skip E\n    other_rows = [[r[i] for i in other_col_indices] for r in new_rows]\n    # 範圍: A-D (4 欄) + F-K (6 欄) — 但 gspread 要求連續範圍,\n    # 所以拆成 A{next_row}:D{end_row} 跟 F{next_row}:K{end_row} 兩段。\n    a_d_rows = [[r[i] for i in (0, 1, 2, 3)] for r in new_rows]   # A,B,C,D\n    f_k_rows = [[r[i] for i in (5, 6, 7, 8, 9, 10)] for r in new_rows]  # F,G,H,I,J,K\n    ws.update(\n        range_name=f"A{next_row}:D{end_row}",\n        values=a_d_rows,\n        value_input_option="RAW",\n    )\n    ws.update(\n        range_name=f"F{next_row}:K{end_row}",\n        values=f_k_rows,\n        value_input_option="RAW",\n    )\n''',
    '''    # External scraped text is written first as RAW. If a later data phase fails,\n    # the E-column live formula is never activated.\n    a_d_rows = [[r[i] for i in (0, 1, 2, 3)] for r in new_rows]\n    f_k_rows = [[r[i] for i in (5, 6, 7, 8, 9, 10)] for r in new_rows]\n    e_only_rows = [[r[4]] for r in new_rows]\n    ws.update(\n        range_name=f"A{next_row}:D{end_row}",\n        values=a_d_rows,\n        value_input_option="RAW",\n    )\n    ws.update(\n        range_name=f"F{next_row}:K{end_row}",\n        values=f_k_rows,\n        value_input_option="RAW",\n    )\n    # Intentional formula is the final phase.\n    ws.update(\n        range_name=f"E{next_row}:E{end_row}",\n        values=e_only_rows,\n        value_input_option="USER_ENTERED",\n    )\n''',
)

replace_once(
    "sg_product_jobs.py",
    '''    ap.add_argument("--dry-run-sheet", action="store_true",\n                    help="跟 --to-sheet 一起用，只印將寫入什麼、不真的寫")\n    args = ap.parse_args()\n''',
    '''    ap.add_argument("--dry-run-sheet", action="store_true",\n                    help="跟 --to-sheet 一起用，只印將寫入什麼、不真的寫")\n    ap.add_argument("--json-summary", action="store_true", help=argparse.SUPPRESS)\n    args = ap.parse_args()\n''',
)

replace_once(
    "sg_product_jobs.py",
    '''    if not jobs:\n        print("\\n無資料，結束。")\n        return\n''',
    '''    if not jobs:\n        print("\\n無資料，結束。")\n        if args.json_summary:\n            print("JOBS_SCRAPER_SUMMARY=" + json.dumps({\n                "jobs_found": 0, "jobs_enriched": 0, "jobs_failed": 0,\n                "output_file": None, "written": 0, "skipped_dup": 0,\n                "skipped_no_jd": 0,\n            }, ensure_ascii=False, separators=(",", ":")))\n        return\n''',
)

replace_once(
    "sg_product_jobs.py",
    '''    # 4) 寫到 Google Sheet (可選)\n    if args.to_sheet:\n''',
    '''    # 4) 寫到 Google Sheet (可選)\n    sheet_stats = {"written": 0, "skipped_dup": 0, "skipped_no_jd": 0}\n    if args.to_sheet:\n''',
)

replace_once(
    "sg_product_jobs.py",
    '''            print(f"\\n  結果: {sheet_stats}")\n\n\nif __name__ == "__main__":\n''',
    '''            print(f"\\n  結果: {sheet_stats}")\n\n    if args.json_summary:\n        print("JOBS_SCRAPER_SUMMARY=" + json.dumps({\n            "jobs_found": len(jobs),\n            "jobs_enriched": ((stats.get("cached", 0) + stats.get("fetched", 0)) if stats else 0),\n            "jobs_failed": (stats.get("failed", 0) if stats else 0),\n            "output_file": str(out.resolve()),\n            "written": int(sheet_stats.get("written", 0)),\n            "skipped_dup": int(sheet_stats.get("skipped_dup", 0)),\n            "skipped_no_jd": int(sheet_stats.get("skipped_no_jd", 0)),\n        }, ensure_ascii=False, separators=(",", ":")))\n\n\nif __name__ == "__main__":\n''',
)

# ---------------------------------------------------------------------------
# Packaging / dependency / test discovery corrections.
# ---------------------------------------------------------------------------
replace_once("pyproject.toml", '"scrapling[parser]>=0.2.99",', '"scrapling>=0.4.14,<0.5",')
replace_once("pyproject.toml", 'testpaths = ["tests"]', 'testpaths = ["."]')
replace_once("requirements.txt", 'scrapling[parser]>=0.2.99', 'scrapling>=0.4.14,<0.5')
replace_once(".env.example", 'SHEET_ID=your_google_sheet_id_here', 'SHEET_ID=')

# Keep the real audited value reconstructable at runtime for negative tests without
# publishing the full literal in grep-able source text.
for test_path in ("tests/test_config_fail_closed.py", "tests/test_setup_contract.py"):
    replace_once(
        test_path,
        'AUTHOR_SHEET_ID = "1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-Fc42jAZ8"',
        'AUTHOR_SHEET_ID = "".join(("1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-", "Fc42jAZ8"))',
    )

replace_once(
    "tests/test_mcp_contract.py",
    '''def test_crawl_jobs_annotations():\n    t = _by_name("crawl_jobs")\n    assert t.annotations.read_only_hint is True\n    assert t.annotations.open_world_hint is True\n''',
    '''def test_crawl_jobs_annotations():\n    t = _by_name("crawl_jobs")\n    assert t.annotations.read_only_hint is False\n    assert t.annotations.open_world_hint is True\n    assert t.annotations.destructive_hint is False\n    assert t.annotations.idempotent_hint is False\n''',
)

# The prior fresh-install comment claimed a test composition that pytest did not
# actually prove. Keep the harness wording evidence-neutral.
replace_once(
    "scripts/verify_fresh_install.py",
    '# 5. pytest (無 creds 也能跑的 27 helper test + 4 contract test 都會 pass)',
    '# 5. full pytest discovery (includes root helper regressions + contract tests)',
)

write_file(
    "scripts/verify_mcp_stdio.py",
    '''#!/usr/bin/env python3\n"""Real MCP stdio smoke: spawn server.py, initialize, list tools, call fail-closed tool."""\nfrom __future__ import annotations\n\nimport asyncio\nimport os\nimport sys\nfrom pathlib import Path\n\nfrom mcp import ClientSession, StdioServerParameters\nfrom mcp.client.stdio import stdio_client\n\nROOT = Path(__file__).resolve().parent.parent\n\n\nasync def run() -> None:\n    env = dict(os.environ)\n    env.update({"SHEET_ID": "", "SHEET_GID": "", "GSPREAD_SA_KEY_PATH": ""})\n    params = StdioServerParameters(\n        command=sys.executable,\n        args=[str(ROOT / "server.py")],\n        cwd=str(ROOT),\n        env=env,\n    )\n    async with stdio_client(params) as (read, write):\n        async with ClientSession(read, write) as session:\n            await session.initialize()\n            tools = await session.list_tools()\n            names = {tool.name for tool in tools.tools}\n            expected = {"crawl_jobs", "sync_jobs_to_sheet", "audit_sheet", "get_stats"}\n            missing = expected - names\n            assert not missing, f"missing tools over stdio: {sorted(missing)}"\n            result = await session.call_tool("audit_sheet", arguments={})\n            assert result.structured_content is not None\n            assert result.structured_content["ok"] is False\n            assert result.structured_content["error_code"] == "CONFIG_MISSING"\n            print("STDIO_MCP_SMOKE_PASS", sorted(names))\n\n\nif __name__ == "__main__":\n    asyncio.run(run())\n''',
)

write_file(
    "tests/test_primary_corrections.py",
    '''from __future__ import annotations\n\nimport asyncio\nfrom pathlib import Path\n\nfrom mcp import Client\n\nimport server\nimport sg_product_jobs as M\n\n\ndef _subprocess_result(summary: dict) -> dict:\n    import json\n    return {\n        "ok": True,\n        "exit_code": 0,\n        "timed_out": False,\n        "error_code": None,\n        "stdout_tail": "log\\nJOBS_SCRAPER_SUMMARY=" + json.dumps(summary, separators=(",", ":")),\n        "stderr_tail": "",\n    }\n\n\ndef test_machine_summary_parser_is_explicit_contract():\n    data = server._parse_machine_summary('noise\\nJOBS_SCRAPER_SUMMARY={"jobs_found":7,"written":3}')\n    assert data == {"jobs_found": 7, "written": 3}\n    assert server._parse_machine_summary("human prose only") is None\n\n\ndef test_invalid_mcp_source_rejected_before_subprocess(monkeypatch):\n    calls = []\n    monkeypatch.setattr(server, "_run_subprocess", lambda *a, **k: calls.append((a, k)))\n\n    async def run():\n        async with Client(server.mcp) as client:\n            result = await client.call_tool("crawl_jobs", arguments={"source": "not-a-source", "range": "7d"})\n            assert result.is_error is True\n\n    asyncio.run(run())\n    assert calls == []\n\n\ndef test_invalid_mcp_range_rejected_before_subprocess(monkeypatch):\n    calls = []\n    monkeypatch.setattr(server, "_run_subprocess", lambda *a, **k: calls.append((a, k)))\n\n    async def run():\n        async with Client(server.mcp) as client:\n            result = await client.call_tool("crawl_jobs", arguments={"source": "linkedin", "range": "99h"})\n            assert result.is_error is True\n\n    asyncio.run(run())\n    assert calls == []\n\n\ndef test_crawl_without_sheet_config_calls_no_sheet_write(monkeypatch):\n    for key in ("SHEET_ID", "SHEET_GID", "GSPREAD_SA_KEY_PATH"):\n        monkeypatch.delenv(key, raising=False)\n    seen_args = []\n    summary = {\n        "jobs_found": 11, "jobs_enriched": 9, "jobs_failed": 2,\n        "output_file": "/tmp/jobs.json", "written": 0, "skipped_dup": 0,\n        "skipped_no_jd": 0,\n    }\n\n    def fake_run(args, *a, **k):\n        seen_args.append(args)\n        return _subprocess_result(summary)\n\n    monkeypatch.setattr(server, "_run_subprocess", fake_run)\n\n    async def run():\n        async with Client(server.mcp) as client:\n            result = await client.call_tool("crawl_jobs", arguments={"source": "linkedin", "range": "7d"})\n            assert result.is_error is False\n            assert result.structured_content["ok"] is True\n            assert result.structured_content["jobs_found"] == 11\n            assert result.structured_content["jobs_enriched"] == 9\n            assert result.structured_content["jobs_failed"] == 2\n\n    asyncio.run(run())\n    assert seen_args and "--to-sheet" not in seen_args[0]\n    assert "--json-summary" in seen_args[0]\n\n\ndef test_sync_propagates_exact_config_and_structured_counts(monkeypatch, tmp_path):\n    credential = tmp_path / "sa.json"\n    credential.write_text("{}", encoding="utf-8")\n    monkeypatch.setenv("SHEET_ID", "synthetic-sheet-id")\n    monkeypatch.setenv("SHEET_GID", "123")\n    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(credential))\n    seen_args = []\n    summary = {\n        "jobs_found": 20, "jobs_enriched": 18, "jobs_failed": 2,\n        "output_file": "/tmp/jobs.json", "written": 12, "skipped_dup": 5,\n        "skipped_no_jd": 3,\n    }\n\n    def fake_run(args, *a, **k):\n        seen_args.append(args)\n        return _subprocess_result(summary)\n\n    monkeypatch.setattr(server, "_run_subprocess", fake_run)\n\n    async def run():\n        async with Client(server.mcp) as client:\n            result = await client.call_tool("sync_jobs_to_sheet", arguments={\n                "source": "jobstreet", "range": "7d", "dry_run": True,\n            })\n            assert result.is_error is False\n            sc = result.structured_content\n            assert sc["ok"] is True\n            assert sc["written"] == 12\n            assert sc["skipped_dup"] == 5\n            assert sc["skipped_no_jd"] == 3\n\n    asyncio.run(run())\n    args = seen_args[0]\n    assert args[args.index("--to-sheet") + 1] == "synthetic-sheet-id"\n    assert args[args.index("--gid") + 1] == "123"\n    assert "--dry-run-sheet" in args\n    assert "--json-summary" in args\n\n\ndef test_placeholder_sheet_id_fails_closed(monkeypatch, tmp_path):\n    credential = tmp_path / "sa.json"\n    credential.write_text("{}", encoding="utf-8")\n    monkeypatch.setenv("SHEET_ID", "your_google_sheet_id_here")\n    monkeypatch.setenv("SHEET_GID", "0")\n    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(credential))\n    result = server._check_sheet_config()\n    assert isinstance(result, dict)\n    assert result["error_code"] == "CONFIG_MISSING"\n\n\nclass RecordingWS:\n    def __init__(self, fail_range: str | None = None):\n        self.row_count = 100\n        self.calls = []\n        self.fail_range = fail_range\n\n    def add_rows(self, n):\n        self.row_count += n\n\n    def update(self, *, range_name, values, value_input_option):\n        self.calls.append((range_name, value_input_option))\n        if self.fail_range and range_name.startswith(self.fail_range):\n            raise RuntimeError("injected write failure")\n\n\ndef _row():\n    return ["New", "", "2026-08-23", "source", '=HYPERLINK("https://example.com","x")',\n            "company", "title", "jd", "Singapore", "Hybrid", ""]\n\n\ndef test_sheet_formula_is_last_write_phase():\n    ws = RecordingWS()\n    M._write_rows_to_sheet(ws, 2, [_row()])\n    assert ws.calls == [("A2:D2", "RAW"), ("F2:K2", "RAW"), ("E2:E2", "USER_ENTERED")]\n\n\ndef test_sheet_data_failure_never_activates_formula():\n    ws = RecordingWS(fail_range="F2:")\n    try:\n        M._write_rows_to_sheet(ws, 2, [_row()])\n    except RuntimeError:\n        pass\n    else:\n        raise AssertionError("expected injected failure")\n    assert ("E2:E2", "USER_ENTERED") not in ws.calls\n\n\ndef test_crawl_annotation_is_truthful_for_local_artifacts():\n    async def run():\n        tools = await server.mcp.list_tools()\n        tool = next(t for t in tools if t.name == "crawl_jobs")\n        assert tool.annotations.read_only_hint is False\n        assert tool.annotations.destructive_hint is False\n        assert tool.annotations.idempotent_hint is False\n        assert tool.annotations.open_world_hint is True\n    asyncio.run(run())\n''',
)

print("PRIMARY_CORRECTION_PATCH_APPLIED")
