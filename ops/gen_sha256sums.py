"""Regenerate SHA256SUMS.txt: every tracked file except itself, path-sorted."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("UPSTREAM_DIR", str(Path.home() / ".minimax-agent" / "projects" / "jobs-scraper-unified")))
OUT = ROOT / "SHA256SUMS.txt"

tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split("\n")
paths = sorted(p for p in tracked if p and p != "SHA256SUMS.txt")

lines = []
for path in paths:
    digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    lines.append(f"{digest}  {path}")

OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"{len(lines)} entries written")
