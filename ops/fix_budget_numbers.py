"""Align the v1.6.8 budget numbers in the docs with the adapter (20 / 20 / 40)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("UPSTREAM_DIR", str(Path.home() / ".minimax-agent" / "projects" / "jobs-scraper-unified")))

REPLACEMENTS = {
    "README.md": [
        ("`1h` 12 pages, `24h` 12, `3d` 30, `7d` 73", "`1h` 20 pages, `24h` 20, `3d` 40, `7d` 73"),
    ],
    "README.zh-TW.md": [
        ("`1h` 12 頁、`24h` 12、`3d` 30、`7d` 73", "`1h` 20 頁、`24h` 20、`3d` 40、`7d` 73"),
    ],
    "README.zh-CN.md": [
        ("`1h` 12 页、`24h` 12、`3d` 30、`7d` 73", "`1h` 20 页、`24h` 20、`3d` 40、`7d` 73"),
    ],
    "CHANGELOG.md": [
        ("`1h` 12 pages, `24h` 12, `3d` 30, `7d` 73", "`1h` 20 pages, `24h` 20, `3d` 40, `7d` 73"),
    ],
    "tests/equivalence/BEHAVIOUR_EQUIVALENCE_CONTRACT.md": [
        (
            "1h 12 pages, 24h 12, 3d 30, 7d 73",
            "1h 20 pages, 24h 20, 3d 40, 7d 73",
        ),
    ],
}

for rel, pairs in REPLACEMENTS.items():
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    for old, new in pairs:
        if old not in text:
            raise SystemExit(f"{rel}: anchor not found: {old}")
        text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")
    print(f"updated {rel}")
