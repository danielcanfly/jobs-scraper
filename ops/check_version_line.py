#!/usr/bin/env python3
"""Fail closed when the version line disagrees with itself.

One build, one version. The number appears in the package metadata, the locked
dependency set, the engine, the two MCP server identities, the plugin
manifests and the Agent Skill. Any two of them drifting apart means the thing
you are running is not the thing you think you are running: the MCP server
would report one version and the package another, and a release tag could
land on a commit whose metadata says something else.

RULES.md §15 lists the carriers. This reads the ones that are present: the
Mavis plugin manifest lives in the plugin runtime rather than in the
repository, so it is optional here and checked when it is there.

Usage:
    python ops/check_version_line.py [ROOT]

The optional root argument points the check at another tree, which is how the
tests exercise it.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The carriers, in the order RULES.md lists them.
CARRIERS = (
    "pyproject.toml",
    "uv.lock",
    "sg_product_jobs.py",
    "server.py",
    "server_v1_1.py",
    ".codex-plugin/plugin.json",
    "skills/jobs-scraper/SKILL.md",
    # Lives in the plugin runtime, not in the repository.
    ".minimax-plugin/plugin.json",
)
OPTIONAL = (".minimax-plugin/plugin.json",)


def read_version(path: Path) -> str | None:
    """Read the version a carrier states, or None if it states none."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".toml":
        return tomllib.loads(text)["project"]["version"]
    if path.suffix == ".json":
        return json.loads(text)["version"]
    if path.suffix == ".lock":
        match = re.search(r'name = "jobs-scraper"\nversion = "([^"]+)"', text)
        return match.group(1) if match else None
    if path.suffix == ".py":
        match = re.search(r'__version__ = "([^"]+)"', text)
        if match:
            return match.group(1)
        match = re.search(r'version="([^"]+)"', text)
        return match.group(1) if match else None
    if path.suffix == ".md":
        match = re.search(r'^\s*version: "([^"]+)"', text, re.M)
        return match.group(1) if match else None
    return None


def main() -> int:
    root = ROOT
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()

    versions: dict[str, str] = {}
    unreadable: list[str] = []
    for rel in CARRIERS:
        found = read_version(root / rel)
        if found is None:
            if rel not in OPTIONAL:
                unreadable.append(rel)
        else:
            versions[rel] = found

    failures: list[str] = []
    if unreadable:
        failures.append(f"could not read a version from: {', '.join(unreadable)}")
    distinct = set(versions.values())
    if len(distinct) > 1:
        failures.append(f"the version line disagrees — {len(distinct)} values:")
        for rel, value in sorted(versions.items()):
            failures.append(f"  {rel}: {value}")
    if failures:
        print("VERSION_LINE_FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"VERSION_LINE_PASS ({len(versions)} carriers → {distinct.pop()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
