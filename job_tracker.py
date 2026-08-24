"""Compatibility surface for portable Google Sheet Job Tracker v1.1.0."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

import region_policy as RP
from jobs_scraper.tracker import audit as _audit
from jobs_scraper.tracker import client as _client
from jobs_scraper.tracker import initializer as _initializer
from jobs_scraper.tracker.schema import (
    COLUMN_WIDTHS,
    DEFAULT_REGIONS,
    DEFAULT_ROWS,
    DEFAULT_SHEET_TITLES,
    HEADER_HEIGHT_PX,
    HEADER_NOTES,
    HEADER_RGB,
    HEADERS,
    PRIORITY_COLORS,
    REGION_ALIASES,
    SCHEMA_COLUMNS,
    SCHEMA_VERSION,
    STATUS_COLORS,
    VALIDATIONS,
    WHITE_RGB,
    TrackerError,
    canonical_region,
    canonical_regions,
    expected_tabs,
    raw_tab,
    selected_tab,
)

SCOPES_READONLY = _client.SCOPES_READONLY
SCOPES_WRITE = _client.SCOPES_WRITE

_resolve_sa_key_path = _client._resolve_sa_key_path
_open_spreadsheet = _client._open_spreadsheet
_header_values = _audit._header_values
worksheet_is_blank = _audit.worksheet_is_blank
validate_worksheet_schema = _audit.validate_worksheet_schema

_grid_range = _initializer._grid_range
_schema_requests = _initializer._schema_requests
_grid_resize_request = _initializer._grid_resize_request
_allocate_sheet_ids = _initializer._allocate_sheet_ids
_build_initialization_requests = _initializer._build_initialization_requests


def _sync_compat_hooks() -> None:
    _client._resolve_sa_key_path = _resolve_sa_key_path
    _client._open_spreadsheet = _open_spreadsheet
    _client.validate_worksheet_schema = validate_worksheet_schema
    _initializer.worksheet_is_blank = worksheet_is_blank
    _initializer.validate_worksheet_schema = validate_worksheet_schema
    _initializer._schema_requests = _schema_requests
    _initializer._grid_resize_request = _grid_resize_request


def check_tracker_config(repo_root: Path | None = None) -> tuple[str, str] | dict[str, Any]:
    _sync_compat_hooks()
    return _client.check_tracker_config(repo_root)


def resolve_region_worksheet(sh, region: str, *, selected: bool = False):
    _sync_compat_hooks()
    return _client.resolve_region_worksheet(sh, region, selected=selected)


def _apply_schema(sh, ws) -> None:
    _sync_compat_hooks()
    return _initializer._apply_schema(sh, ws)


def _find_blank_default_sheets(sh, protected_titles: set[str]) -> list[Any]:
    _sync_compat_hooks()
    return _initializer._find_blank_default_sheets(sh, protected_titles)


def plan_initialize(sh, regions: Iterable[str] | None = None) -> dict[str, Any]:
    _sync_compat_hooks()
    return _initializer.plan_initialize(sh, regions)


def initialize_job_tracker(
    sheet_id: str,
    sa_key_path: str,
    regions: Iterable[str] | None = None,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    _sync_compat_hooks()
    return _initializer.initialize_job_tracker(sheet_id, sa_key_path, regions, dry_run=dry_run)


def open_region_raw(sheet_id: str, sa_key_path: str, region: str, *, write: bool = False):
    _sync_compat_hooks()
    return _client.open_region_raw(sheet_id, sa_key_path, region, write=write)


def read_region_rows(sheet_id: str, sa_key_path: str, region: str) -> list[list[str]]:
    _sync_compat_hooks()
    return _client.read_region_rows(sheet_id, sa_key_path, region)


__all__ = [
    "Any",
    "COLUMN_WIDTHS",
    "DEFAULT_REGIONS",
    "DEFAULT_ROWS",
    "DEFAULT_SHEET_TITLES",
    "HEADERS",
    "HEADER_HEIGHT_PX",
    "HEADER_NOTES",
    "HEADER_RGB",
    "Iterable",
    "PRIORITY_COLORS",
    "Path",
    "REGION_ALIASES",
    "RP",
    "SCHEMA_COLUMNS",
    "SCHEMA_VERSION",
    "SCOPES_READONLY",
    "SCOPES_WRITE",
    "STATUS_COLORS",
    "TrackerError",
    "VALIDATIONS",
    "WHITE_RGB",
    "canonical_region",
    "canonical_regions",
    "check_tracker_config",
    "expected_tabs",
    "initialize_job_tracker",
    "open_region_raw",
    "os",
    "plan_initialize",
    "raw_tab",
    "re",
    "read_region_rows",
    "resolve_region_worksheet",
    "selected_tab",
    "validate_worksheet_schema",
    "worksheet_is_blank",
]
