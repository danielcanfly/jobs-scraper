from __future__ import annotations

import asyncio

from mcp import Client

import server
import sg_product_jobs as M


def _subprocess_result(summary: dict) -> dict:
    import json

    return {
        "ok": True,
        "exit_code": 0,
        "timed_out": False,
        "error_code": None,
        "stdout_tail": "log\nJOBS_SCRAPER_SUMMARY=" + json.dumps(summary, separators=(",", ":")),
        "stderr_tail": "",
    }


def test_machine_summary_parser_is_explicit_contract():
    data = server._parse_machine_summary('noise\nJOBS_SCRAPER_SUMMARY={"jobs_found":7,"written":3}')
    assert data == {"jobs_found": 7, "written": 3}
    assert server._parse_machine_summary("human prose only") is None


def test_invalid_mcp_source_rejected_before_subprocess(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_run_subprocess", lambda *a, **k: calls.append((a, k)))

    async def run():
        async with Client(server.mcp) as client:
            result = await client.call_tool("crawl_jobs", arguments={"source": "not-a-source", "range": "7d"})
            assert result.is_error is True

    asyncio.run(run())
    assert calls == []


def test_invalid_mcp_range_rejected_before_subprocess(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "_run_subprocess", lambda *a, **k: calls.append((a, k)))

    async def run():
        async with Client(server.mcp) as client:
            result = await client.call_tool("crawl_jobs", arguments={"source": "linkedin", "range": "99h"})
            assert result.is_error is True

    asyncio.run(run())
    assert calls == []


def test_crawl_without_sheet_config_calls_no_sheet_write(monkeypatch):
    for key in ("SHEET_ID", "SHEET_GID", "GSPREAD_SA_KEY_PATH"):
        monkeypatch.delenv(key, raising=False)
    seen_args = []
    summary = {
        "jobs_found": 11,
        "jobs_enriched": 9,
        "jobs_failed": 2,
        "output_file": "/tmp/jobs.json",
        "written": 0,
        "skipped_dup": 0,
        "skipped_no_jd": 0,
    }

    def fake_run(args, *a, **k):
        seen_args.append(args)
        return _subprocess_result(summary)

    monkeypatch.setattr(server, "_run_subprocess", fake_run)

    async def run():
        async with Client(server.mcp) as client:
            result = await client.call_tool("crawl_jobs", arguments={"source": "linkedin", "range": "7d"})
            assert result.is_error is False
            assert result.structured_content["ok"] is True
            assert result.structured_content["jobs_found"] == 11
            assert result.structured_content["jobs_enriched"] == 9
            assert result.structured_content["jobs_failed"] == 2

    asyncio.run(run())
    assert seen_args and "--to-sheet" not in seen_args[0]
    assert "--json-summary" in seen_args[0]


def test_sync_propagates_exact_config_and_structured_counts(monkeypatch, tmp_path):
    credential = tmp_path / "sa.json"
    credential.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHEET_ID", "synthetic-sheet-id")
    monkeypatch.setenv("SHEET_GID", "123")
    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(credential))
    seen_args = []
    summary = {
        "jobs_found": 20,
        "jobs_enriched": 18,
        "jobs_failed": 2,
        "output_file": "/tmp/jobs.json",
        "written": 12,
        "skipped_dup": 5,
        "skipped_no_jd": 3,
    }

    def fake_run(args, *a, **k):
        seen_args.append(args)
        return _subprocess_result(summary)

    monkeypatch.setattr(server, "_run_subprocess", fake_run)

    async def run():
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "sync_jobs_to_sheet",
                arguments={
                    "source": "jobstreet",
                    "range": "7d",
                    "dry_run": True,
                },
            )
            assert result.is_error is False
            sc = result.structured_content
            assert sc["ok"] is True
            assert sc["written"] == 12
            assert sc["skipped_dup"] == 5
            assert sc["skipped_no_jd"] == 3

    asyncio.run(run())
    args = seen_args[0]
    assert args[args.index("--to-sheet") + 1] == "synthetic-sheet-id"
    assert args[args.index("--gid") + 1] == "123"
    assert "--dry-run-sheet" in args
    assert "--json-summary" in args


def test_placeholder_sheet_id_fails_closed(monkeypatch, tmp_path):
    credential = tmp_path / "sa.json"
    credential.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHEET_ID", "your_google_sheet_id_here")
    monkeypatch.setenv("SHEET_GID", "0")
    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(credential))
    result = server._check_sheet_config()
    assert isinstance(result, dict)
    assert result["error_code"] == "CONFIG_MISSING"


class RecordingWS:
    def __init__(self, fail_range: str | None = None):
        self.row_count = 100
        self.calls = []
        self.fail_range = fail_range

    def add_rows(self, n):
        self.row_count += n

    def update(self, *, range_name, values, value_input_option):
        self.calls.append((range_name, value_input_option))
        if self.fail_range and range_name.startswith(self.fail_range):
            raise RuntimeError("injected write failure")


def _row():
    return [
        "New",
        "",
        "2026-08-23",
        "source",
        '=HYPERLINK("https://example.com","x")',
        "company",
        "title",
        "jd",
        "Singapore",
        "Hybrid",
        "",
    ]


def test_sheet_formula_is_last_write_phase():
    ws = RecordingWS()
    M._write_rows_to_sheet(ws, 2, [_row()])
    assert ws.calls == [("A2:D2", "RAW"), ("F2:K2", "RAW"), ("E2:E2", "USER_ENTERED")]


def test_sheet_data_failure_never_activates_formula():
    ws = RecordingWS(fail_range="F2:")
    try:
        M._write_rows_to_sheet(ws, 2, [_row()])
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected injected failure")
    assert ("E2:E2", "USER_ENTERED") not in ws.calls


def test_crawl_annotation_is_truthful_for_local_artifacts():
    async def run():
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "crawl_jobs")
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is False
        assert tool.annotations.open_world_hint is True

    asyncio.run(run())
