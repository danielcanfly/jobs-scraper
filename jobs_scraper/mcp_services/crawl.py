"""Shared crawl/sync subprocess orchestration for MCP entrypoints."""

from __future__ import annotations

from typing import Any, Callable

import runtime_core as RT

Runner = Callable[[list[str]], dict[str, Any]]


def build_crawl_args(
    range: RT.Range,
    source: RT.Source,
    *,
    with_jd: bool,
    max_pages: int | None,
    refetch: bool,
) -> list[str]:
    args = [range, "--source", source]
    if with_jd:
        args.append("--with-jd")
    if refetch:
        args.append("--refetch")
    if max_pages is not None:
        args.extend(["--max-pages", str(max_pages)])
    args.append("--json-summary")
    return args


def build_sheet_sync_args(
    range: RT.Range,
    source: RT.Source,
    *,
    sheet_id: str,
    gid: str | int,
    with_jd: bool,
    max_pages: int | None,
    refetch: bool,
    dry_run: bool,
    sheet_source: str | None = None,
    location: str | None = None,
) -> list[str]:
    args = [range, "--source", source, "--to-sheet", sheet_id, "--gid", str(gid)]
    if sheet_source is not None:
        args.extend(["--sheet-source", sheet_source])
    if location is not None:
        args.extend(["--location", location])
    if with_jd:
        args.append("--with-jd")
    if refetch:
        args.append("--refetch")
    if max_pages is not None:
        args.extend(["--max-pages", str(max_pages)])
    if dry_run:
        args.append("--dry-run-sheet")
    args.append("--json-summary")
    return args


def run_and_parse(
    args: list[str], runner: Runner = RT.run_scraper_subprocess
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    result = runner(args)
    summary = RT.parse_machine_summary(result["stdout_tail"])
    if result["ok"] and summary is None:
        result = {**result, "ok": False, "error_code": "OUTPUT_CONTRACT_MISSING"}
    return result, summary


def crawl_payload(
    source: RT.Source,
    range: RT.Range,
    *,
    with_jd: bool,
    max_pages: int | None,
    refetch: bool,
    runner: Runner = RT.run_scraper_subprocess,
) -> dict[str, Any]:
    result, summary = run_and_parse(
        build_crawl_args(range, source, with_jd=with_jd, max_pages=max_pages, refetch=refetch),
        runner,
    )
    message = (
        "crawl completed"
        if result["ok"]
        else (f"crawl failed (timeout={result['timed_out']}, code={result['error_code']})")
    )
    return {
        "ok": result["ok"],
        "source": source,
        "range": range,
        "with_jd": with_jd,
        "exit_code": result["exit_code"],
        "output_file": (summary or {}).get("output_file"),
        "jobs_found": (summary or {}).get("jobs_found"),
        "jobs_enriched": (summary or {}).get("jobs_enriched"),
        "jobs_failed": (summary or {}).get("jobs_failed"),
        "timed_out": result["timed_out"],
        "error_code": result["error_code"],
        "message": message,
        "stdout_tail": result["stdout_tail"],
        "stderr_tail": result["stderr_tail"],
    }


def sheet_sync_payload(
    source: RT.Source,
    range: RT.Range,
    *,
    sheet_id: str,
    gid: str | int,
    with_jd: bool,
    max_pages: int | None,
    refetch: bool,
    dry_run: bool,
    target_configured: bool = True,
    runner: Runner = RT.run_scraper_subprocess,
    sheet_source: str | None = None,
    location: str | None = None,
) -> dict[str, Any]:
    result, summary = run_and_parse(
        build_sheet_sync_args(
            range,
            source,
            sheet_id=sheet_id,
            gid=gid,
            with_jd=with_jd,
            max_pages=max_pages,
            refetch=refetch,
            dry_run=dry_run,
            sheet_source=sheet_source,
            location=location,
        ),
        runner,
    )
    message = (
        "sync completed"
        if result["ok"]
        else (f"sync failed (timeout={result['timed_out']}, code={result['error_code']})")
    )
    return {
        "ok": result["ok"],
        "source": source,
        "range": range,
        "exit_code": result["exit_code"],
        "dry_run": dry_run,
        "written": int((summary or {}).get("written", 0)),
        "skipped_dup": int((summary or {}).get("skipped_dup", 0)),
        "skipped_no_jd": int((summary or {}).get("skipped_no_jd", 0)),
        "target_configured": target_configured,
        "timed_out": result["timed_out"],
        "error_code": result["error_code"],
        "message": message,
        "stdout_tail": result["stdout_tail"],
        "stderr_tail": result["stderr_tail"],
    }
