#!/usr/bin/env python3
"""Fail closed if the frozen v1.1.1 behaviour-equivalence oracle drifts."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FREEZE = REPO_ROOT / "tests" / "equivalence" / "HARNESS_FREEZE.json"


def git_blob(path: str) -> str:
    proc = subprocess.run(
        ["git", "hash-object", "--", path],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git hash-object failed for {path}")
    return proc.stdout.strip()


def main() -> int:
    data = json.loads(FREEZE.read_text(encoding="utf-8"))
    failures: list[str] = []
    for path, expected in data["frozen_blobs"].items():
        target = REPO_ROOT / path
        if not target.exists():
            failures.append(f"missing: {path}")
            continue
        observed = git_blob(path)
        if observed != expected:
            failures.append(f"drift: {path}: expected {expected}, observed {observed}")

    if failures:
        print("EQUIVALENCE_HARNESS_DRIFT")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("EQUIVALENCE_HARNESS_FREEZE_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
