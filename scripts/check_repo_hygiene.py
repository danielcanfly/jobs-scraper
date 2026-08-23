#!/usr/bin/env python3
"""Fail closed when tracked repository text leaks private/production metadata.

This guard intentionally scans the entire tracked tree, not a hand-picked list of
"distributable" files. Known historical values are assembled at runtime so the
guard itself does not re-commit the forbidden literal it is meant to detect.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Known values that must never reappear in the current tracked tree.
# Keep fragments split so this source file does not contain the literal itself.
FORBIDDEN_EXACT = {
    "author_production_sheet_id": "1e-" + "YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-Fc42jAZ8",
    "author_production_tab_gid": "111" + "9491672",
    "author_service_account": "job-scrape@" + "dark-park-493403-n2.iam.gserviceaccount.com",
    "author_legacy_secret_path": "projects/scrapling-test/" + ".secrets/gsheet-sa.json",
    "pem_private_key_header": "-----BEGIN " + "PRIVATE KEY-----",
}

# Generic patterns catch future leaks that do not reuse the historical values.
PATTERNS: dict[str, re.Pattern[str]] = {
    "concrete_google_sheet_url": re.compile(
        r"https://docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{20,}(?:/|\b)"
    ),
    "service_account_identity": re.compile(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com\b"
    ),
    "google_private_key_json": re.compile(r'"private_key"\s*:\s*"-----BEGIN'),
}


def tracked_files() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT)
    return [REPO_ROOT / p.decode("utf-8") for p in raw.split(b"\0") if p]


def read_text_if_text_file(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan() -> list[str]:
    findings: list[str] = []
    for path in tracked_files():
        text = read_text_if_text_file(path)
        if text is None:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for label, value in FORBIDDEN_EXACT.items():
            if value in text:
                findings.append(f"{rel}: forbidden exact value: {label}")
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{rel}: forbidden pattern: {label}")
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("REPO_HYGIENE_FAIL")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("REPO_HYGIENE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
