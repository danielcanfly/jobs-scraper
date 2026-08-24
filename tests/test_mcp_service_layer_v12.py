from __future__ import annotations

import asyncio
import inspect

import server
import server_v1_1
from jobs_scraper.mcp_services import crawl, sheet_analysis, sheet_config, tracker


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_b5_service_modules_are_importable():
    assert crawl.build_crawl_args("7d", "linkedin", with_jd=False, max_pages=None, refetch=False)
    assert sheet_config.SCOPES_READONLY == server.SCOPES_READONLY
    assert callable(sheet_analysis.audit_rows)
    assert callable(tracker.sync_region_payload)


def test_v11_no_longer_imports_legacy_server():
    source = inspect.getsource(server_v1_1)
    legacy_import = "import server" + " as legacy"
    assert legacy_import not in source
    assert "legacy.crawl_jobs" not in source


def test_mcp_tool_sets_remain_exact():
    legacy_tools = {tool.name for tool in _run(server.mcp.list_tools())}
    v11_tools = {tool.name for tool in _run(server_v1_1.mcp.list_tools())}
    assert legacy_tools == {"crawl_jobs", "sync_jobs_to_sheet", "audit_sheet", "get_stats"}
    assert v11_tools == {
        "crawl_jobs",
        "initialize_job_tracker",
        "sync_jobs_to_sheet",
        "audit_sheet",
        "get_stats",
    }


def test_service_crawl_payload_preserves_legacy_subprocess_contract():
    seen_args: list[list[str]] = []

    def fake_runner(args):
        seen_args.append(list(args))
        return {
            "ok": True,
            "exit_code": 0,
            "timed_out": False,
            "error_code": None,
            "stdout_tail": 'JOBS_SCRAPER_SUMMARY={"jobs_found":2,"jobs_enriched":1,"jobs_failed":0,"output_file":"/tmp/jobs.json"}',
            "stderr_tail": "",
        }

    payload = crawl.crawl_payload(
        "jobstreet",
        "7d",
        with_jd=True,
        max_pages=3,
        refetch=True,
        runner=fake_runner,
    )
    assert seen_args == [["7d", "--source", "jobstreet", "--with-jd", "--refetch", "--max-pages", "3", "--json-summary"]]
    assert payload["ok"] is True
    assert payload["jobs_found"] == 2
    assert payload["output_file"] == "/tmp/jobs.json"


def test_sheet_analysis_shared_shape_matches_server_models():
    rows = [
        ["New", "", "2026-08-24", "LinkedIn / jobs-scraper", "https://www.linkedin.com/jobs/view/42", "Acme", "PM", "", "Singapore", "Hybrid", ""],
        ["New", "", "2026-08-24", "JobStreet / jobs-scraper", "https://sg.jobstreet.com/job/42", "Acme", "PM", "", "Singapore", "Remote", "⚠️ HARD: citizens only"],
    ]
    audit = sheet_analysis.audit_rows(rows)
    stats = sheet_analysis.stats_rows(rows)
    assert server.AuditResult(ok=True, **audit).rows_read == 2
    assert server.StatsResult(ok=True, **stats).total_rows == 2
    assert audit["work_mode_distribution"] == {"Hybrid": 1, "Remote": 1}
    assert stats["date_distribution_top10"] == {"2026-08-24": 2}
