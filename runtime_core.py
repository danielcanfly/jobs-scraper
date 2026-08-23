"""Shared runtime/execution contract for jobs-scraper MCP entrypoints.

This module owns subprocess execution, timeout/error normalization, repository
paths, source/range public types, and the machine-readable CLI summary parser.
It is deliberately independent of MCP registration and Google Sheet logic.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).parent.resolve()
PYTHON_EXE = sys.executable
SUBPROCESS_TIMEOUT = int(os.getenv("JOBS_SCRAPER_SUBPROCESS_TIMEOUT", "7200"))
OUTPUT_TAIL_STDOUT = 5_000
OUTPUT_TAIL_STDERR = 2_000
SUMMARY_PREFIX = "JOBS_SCRAPER_SUMMARY="

Source = Literal["linkedin", "jora", "jobstreet"]
Range = Literal["1h", "24h", "3d", "7d", "14d", "21d", "30d"]


def run_scraper_subprocess(
    args: list[str],
    timeout: int = SUBPROCESS_TIMEOUT,
    *,
    raw: bool = False,
) -> dict[str, Any]:
    """Run the scraper (or a verbatim test command) and normalize its result.

    Default mode prepends the current interpreter and `sg_product_jobs.py` and
    always executes from the repository root. `raw=True` runs `args` verbatim.
    """
    cmd = args if raw else [PYTHON_EXE, str(REPO_ROOT / "sg_product_jobs.py")] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(REPO_ROOT),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "exit_code": -1,
            "timed_out": True,
            "error_code": "SUBPROCESS_TIMEOUT",
            "stdout_tail": (
                exc.stdout.decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or "")
            )[-OUTPUT_TAIL_STDOUT:],
            "stderr_tail": (
                exc.stderr.decode("utf-8", "replace")
                if isinstance(exc.stderr, bytes)
                else (exc.stderr or "")
            )[-OUTPUT_TAIL_STDERR:],
        }

    stdout_tail = (result.stdout or "")[-OUTPUT_TAIL_STDOUT:]
    stderr_tail = (result.stderr or "")[-OUTPUT_TAIL_STDERR:]
    error_code: str | None = None
    if result.returncode != 0:
        if re.search(r"\b(429|403|rate\s*limit|too many requests)\b", stderr_tail, re.IGNORECASE):
            error_code = "UPSTREAM_RATE_LIMIT"
        else:
            error_code = "SCRAPER_EXIT_NONZERO"

    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "timed_out": False,
        "error_code": error_code,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


def parse_machine_summary(stdout: str) -> dict[str, Any] | None:
    """Parse the final JSON CLI summary without inferring counts from prose."""
    for line in reversed(stdout.splitlines()):
        if not line.startswith(SUMMARY_PREFIX):
            continue
        try:
            value = json.loads(line[len(SUMMARY_PREFIX):])
        except json.JSONDecodeError:
            return None
        return value if isinstance(value, dict) else None
    return None
