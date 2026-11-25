#!/usr/bin/env python3
"""Fail closed when the plugin sync manifest does not cover every tracked file.

The plugin runtime and the working copies receive the upstream code through
`scripts/sync-from-repo.sh`. That script copies the root files named in
`SYNC_FILES` and merges the directories named in `SYNC_DIRS`. A tracked file
that neither list covers never reaches the runtime: it exists in the repository
and nowhere else, and the three placements silently stop being the same build.

That is not hypothetical. v1.8.2 added `ops/` — 35 tracked files, including
every crawl supervisor — and left `ops/` off the merge manifest, so the runtime
would have kept running its own copy while the repository's copy sat unchanged.
The supervisors are frozen baseline behaviour (contract item 42b), so a runtime
copy that drifts from the repository's copy runs behaviour the baseline does not
describe.

This guard runs where the tracked set is authoritative: the upstream checkout.

The plugin runtime and a working copy have their own git histories, and their
tracked sets are their own — the runtime tracks the Mavis-specific files, a
working copy tracks whatever is left on that machine. Comparing those against
the manifest would report files that are deliberately not carried, so the guard
recognises the upstream checkout (by its origin remote) and reports that it does
not apply anywhere else rather than failing on the wrong file set.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "scripts" / "sync-from-repo.sh"
DEFAULT_UPSTREAM = "https://github.com/danielcanfly/jobs-scraper.git"

# Paths that must never travel through a sync: they are private state, and the
# repository's own hygiene guard rejects the same identities in tracked text.
PRIVATE_PATHS = (
    ".env",
    ".secrets",
    "seen_jds.jsonl",
    "local_tools",
    ".minimax-plugin",
    "servers.mcp.json",
)


def repo_slug(url: str) -> str:
    """Normalise a git remote to an owner/repo pair."""
    text = url.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    if text.startswith("git@"):
        text = text[4:].replace(":", "/", 1)
    else:
        for prefix in ("https://", "http://", "ssh://", "git://"):
            if text.startswith(prefix):
                text = text[len(prefix) :]
                if "@" in text.split("/")[0]:
                    text = text.split("@", 1)[1]
                break
    parts = [part for part in text.split("/") if part]
    return "/".join(parts[-2:]) if len(parts) >= 2 else text


def origin_remote() -> str | None:
    proc = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    remote = proc.stdout.strip()
    return remote or None


def parse_list(text: str, name: str) -> list[str]:
    match = re.search(rf"^{name}=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise SystemExit(f"could not find {name}=() in {MANIFEST}")
    return re.findall(r"^\s*([^\s#]+)\s*$", match.group(1), re.M)


def tracked_files() -> list[str]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT)
    return [p.decode("utf-8") for p in raw.split(b"\0") if p]


def main() -> int:
    upstream = os.environ.get("JOBS_SCRAPER_UPSTREAM", DEFAULT_UPSTREAM)
    remote = origin_remote()
    if remote is None:
        print("SYNC_MANIFEST_SKIPPED (not a checkout with an origin remote)")
        return 0
    if repo_slug(remote) != repo_slug(upstream):
        print(f"SYNC_MANIFEST_SKIPPED (origin {remote} is not {upstream})")
        return 0

    text = MANIFEST.read_text(encoding="utf-8")
    files = parse_list(text, "SYNC_FILES")
    dirs = parse_list(text, "SYNC_DIRS")
    preserved = parse_list(text, "PRESERVED")

    failures: list[str] = []

    # 1. Every tracked file must be covered by the manifest.
    file_set = set(files)
    prefixes = tuple(d.rstrip("/") + "/" for d in dirs)
    uncovered = [
        path
        for path in tracked_files()
        if path not in file_set and not any(path.startswith(prefix) for prefix in prefixes)
    ]
    for path in uncovered:
        failures.append(f"tracked file not covered by the sync manifest: {path}")

    # 2. Every manifest entry must exist, and a merged directory must not be empty.
    for name in files:
        if not (REPO_ROOT / name).is_file():
            failures.append(f"manifest names a root file that does not exist: {name}")
    for name in dirs:
        target = REPO_ROOT / name
        if not target.is_dir():
            failures.append(f"manifest names a directory that does not exist: {name}")
        elif not any(p.is_file() for p in target.rglob("*")):
            failures.append(f"manifest names an empty directory: {name}")

    # 3. Private state must not travel, and must be preserved where it is.
    carried = set(files) | set(dirs)
    for private in PRIVATE_PATHS:
        if private in carried:
            failures.append(f"private path is on the sync manifest: {private}")
        if private not in preserved:
            failures.append(f"private path is not on the preserve list: {private}")

    if failures:
        print("SYNC_MANIFEST_FAIL")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"SYNC_MANIFEST_PASS ({len(files)} files, {len(dirs)} directories)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
