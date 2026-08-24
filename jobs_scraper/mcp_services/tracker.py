"""Region-aware MCP service helpers for Job Tracker v1.1."""
from __future__ import annotations

from typing import Any, Callable

import job_tracker as JT
import region_policy as RP
import runtime_core as RT

from . import crawl as crawl_service

ConfigReader = Callable[[], tuple[str, str] | dict[str, Any]]


def cfg_or_error() -> tuple[str, str] | dict[str, Any]:
    return JT.check_tracker_config(RT.REPO_ROOT)


def source_region_supported(source: str, region: str) -> tuple[bool, str | None]:
    return RP.source_region_supported(source, region)


def initialize_tracker_payload(
    regions: list[str],
    *,
    dry_run: bool,
    cfg_reader: ConfigReader = cfg_or_error,
) -> dict[str, Any]:
    cfg = cfg_reader()
    if isinstance(cfg, dict):
        return {
            "ok": False,
            "dry_run": dry_run,
            "regions": list(regions),
            "error_code": cfg["error_code"],
            "message": cfg["message"],
        }
    sa_key_path, sheet_id = cfg
    try:
        result = JT.initialize_job_tracker(sheet_id, sa_key_path, regions, dry_run=dry_run)
    except JT.TrackerError as exc:
        return {
            "ok": False,
            "dry_run": dry_run,
            "regions": list(regions),
            "error_code": exc.error_code,
            "message": exc.message,
        }
    except Exception as exc:
        return {
            "ok": False,
            "dry_run": dry_run,
            "regions": list(regions),
            "error_code": "SHEET_INIT_FAILED",
            "message": f"could not initialize tracker: {type(exc).__name__}: {exc}",
        }
    payload = dict(result)
    payload.setdefault("created", [])
    payload.setdefault("configured", [])
    payload.setdefault("already_compatible", [])
    payload.setdefault("remove_blank_defaults", [])
    payload.setdefault("removed_blank_defaults", [])
    payload.setdefault("incompatible", [])
    return payload


def sync_region_payload(
    region: RP.PublicRegion,
    source: RT.Source,
    range: RT.Range,
    *,
    with_jd: bool,
    max_pages: int | None,
    refetch: bool,
    dry_run: bool,
    cfg_reader: ConfigReader = cfg_or_error,
    runner: crawl_service.Runner = RT.run_scraper_subprocess,
) -> dict[str, Any]:
    target_sheet = JT.raw_tab(region)
    supported, reason = source_region_supported(source, region)
    if not supported:
        return {
            "ok": False,
            "source": source,
            "region": region,
            "range": range,
            "target_sheet": target_sheet,
            "exit_code": -1,
            "dry_run": dry_run,
            "target_configured": False,
            "error_code": "SOURCE_REGION_UNSUPPORTED",
            "message": reason or "unsupported source/region",
        }

    cfg = cfg_reader()
    if isinstance(cfg, dict):
        return {
            "ok": False,
            "source": source,
            "region": region,
            "range": range,
            "target_sheet": target_sheet,
            "exit_code": -1,
            "dry_run": dry_run,
            "target_configured": False,
            "error_code": cfg["error_code"],
            "message": cfg["message"],
        }
    sa_key_path, sheet_id = cfg

    try:
        _sh, ws = JT.open_region_raw(sheet_id, sa_key_path, region, write=not dry_run)
    except JT.TrackerError as exc:
        return {
            "ok": False,
            "source": source,
            "region": region,
            "range": range,
            "target_sheet": target_sheet,
            "exit_code": -1,
            "dry_run": dry_run,
            "target_configured": False,
            "error_code": exc.error_code,
            "message": exc.message,
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": source,
            "region": region,
            "range": range,
            "target_sheet": target_sheet,
            "exit_code": -1,
            "dry_run": dry_run,
            "target_configured": False,
            "error_code": "SHEET_NOT_FOUND",
            "message": f"could not resolve target sheet: {type(exc).__name__}: {exc}",
        }

    payload = crawl_service.sheet_sync_payload(
        source,
        range,
        sheet_id=sheet_id,
        gid=ws.id,
        with_jd=with_jd,
        max_pages=max_pages,
        refetch=refetch,
        dry_run=dry_run,
        runner=runner,
        sheet_source=RP.SOURCE_LABELS[source],
        location=RP.REGION_LOCATIONS[region],
    )
    payload.update({"region": region, "target_sheet": target_sheet, "target_gid": int(ws.id)})
    return payload


def read_region_rows(
    region: RP.PublicRegion,
    *,
    cfg_reader: ConfigReader = cfg_or_error,
) -> tuple[list[list[str]] | None, dict[str, str] | None]:
    cfg = cfg_reader()
    if isinstance(cfg, dict):
        return None, {"error_code": cfg["error_code"], "message": cfg["message"]}
    sa_key_path, sheet_id = cfg
    try:
        return JT.read_region_rows(sheet_id, sa_key_path, region), None
    except JT.TrackerError as exc:
        return None, {"error_code": exc.error_code, "message": exc.message}
    except Exception as exc:
        return None, {"error_code": "SHEET_NOT_FOUND", "message": f"could not read region sheet: {type(exc).__name__}: {exc}"}
