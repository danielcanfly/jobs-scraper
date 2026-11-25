"""The plugin sync must be able to carry the frozen supervisors to the runtime.

v1.8.2 put the crawl supervisors under `ops/` and left `ops/` off the merge
manifest of `scripts/sync-from-repo.sh`, so 35 tracked files existed in the
repository and would never reach the plugin runtime that executes them. The
supervisors are frozen baseline behaviour (contract item 42b), so a runtime
copy that drifts from the repository's copy runs behaviour the baseline does
not describe.

These tests read the manifest and the tree beside it. They never touch the
network and never read git, because the same tree exists in three places with
three different git histories — the upstream checkout, the plugin runtime and
a working copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "scripts" / "sync-from-repo.sh"

# Directories that legitimately exist on only one side of the three placements,
# or that are build output rather than source. They are not expected on the
# merge manifest.
LOCAL_ONLY = {
    ".git",
    ".venv",
    ".idea",
    ".vscode",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".secrets",
    ".minimax-plugin",
    "__pycache__",
    "_archive",
    "build",
    "dist",
    "jobs_scraper.egg-info",
    "local_tools",
    "node_modules",
}

# Private state: it stays where it is and never travels through a sync.
PRIVATE_PATHS = (
    ".env",
    ".secrets",
    "seen_jds.jsonl",
    "local_tools",
    ".minimax-plugin",
    "servers.mcp.json",
)

# The supervisors the contract freezes (item 42b). The runtime has to be able
# to receive exactly these.
FROZEN_SUPERVISORS = (
    "ops/run_chain.sh",
    "ops/run_sg_chunked.sh",
    "ops/run_sg_jobstreet.sh",
    "ops/run_tw_chunked.sh",
)


def parse_list(text: str, name: str) -> list[str]:
    match = re.search(rf"^{name}=\(\n(.*?)^\)", text, re.S | re.M)
    if not match:
        raise SystemExit(f"could not find {name}=() in {MANIFEST}")
    return re.findall(r"^\s*([^\s#]+)\s*$", match.group(1), re.M)


@pytest.fixture(scope="module")
def manifest() -> str:
    return MANIFEST.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sync_files(manifest: str) -> list[str]:
    return parse_list(manifest, "SYNC_FILES")


@pytest.fixture(scope="module")
def sync_dirs(manifest: str) -> list[str]:
    return parse_list(manifest, "SYNC_DIRS")


@pytest.fixture(scope="module")
def preserved(manifest: str) -> list[str]:
    return parse_list(manifest, "PRESERVED")


def test_ops_is_on_the_merge_manifest(sync_dirs: list[str]) -> None:
    assert "ops" in sync_dirs, (
        "ops/ holds the crawl supervisors, and they are frozen baseline behaviour; "
        "without it on the merge manifest the runtime keeps a private copy that "
        "drifts from the repository's one"
    )


def test_every_frozen_supervisor_travels_with_ops(sync_dirs: list[str]) -> None:
    assert "ops" in sync_dirs
    for supervisor in FROZEN_SUPERVISORS:
        assert (REPO_ROOT / supervisor).is_file(), f"missing frozen supervisor: {supervisor}"
        assert supervisor.startswith("ops/"), supervisor


def test_every_merged_directory_exists_and_is_not_empty(sync_dirs: list[str]) -> None:
    for name in sync_dirs:
        target = REPO_ROOT / name
        assert target.is_dir(), f"manifest names a directory that does not exist: {name}"
        assert any(p.is_file() for p in target.rglob("*")), f"merged directory is empty: {name}"


def test_every_named_root_file_exists(sync_files: list[str]) -> None:
    for name in sync_files:
        assert (REPO_ROOT / name).is_file(), f"manifest names a root file that does not exist: {name}"


def test_every_top_level_directory_is_covered_by_the_manifest(sync_files: list[str], sync_dirs: list[str]) -> None:
    """A new top-level directory has to be added to the manifest, or it never travels.

    This is the check that would have caught v1.8.2: `ops/` was a new top-level
    directory and it was not on the merge manifest.
    """
    carried = sync_files + sync_dirs
    for entry in sorted(REPO_ROOT.iterdir()):
        if not entry.is_dir() or entry.name in LOCAL_ONLY:
            continue
        covered = any(item == entry.name or item.startswith(f"{entry.name}/") for item in carried)
        assert covered, (
            f"top-level directory {entry.name}/ is not covered by the sync manifest; "
            f"add it to SYNC_DIRS or it never reaches the runtime"
        )


def test_private_state_is_never_carried_by_a_sync(sync_files: list[str], sync_dirs: list[str]) -> None:
    carried = set(sync_files) | set(sync_dirs)
    for private in PRIVATE_PATHS:
        assert private not in carried, f"private path is on the sync manifest: {private}"


def test_private_state_is_on_the_preserve_list(preserved: list[str]) -> None:
    for private in PRIVATE_PATHS:
        assert private in preserved, f"private path is not on the preserve list: {private}"


def _load_guard():
    """Load the CI guard by path: scripts/ is not a package."""
    import importlib.util

    path = REPO_ROOT / "scripts" / "check_sync_manifest.py"
    spec = importlib.util.spec_from_file_location("check_sync_manifest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("git@github.com:danielcanfly/jobs-scraper.git", "danielcanfly/jobs-scraper"),
        ("https://github.com/danielcanfly/jobs-scraper.git", "danielcanfly/jobs-scraper"),
        ("https://github.com/danielcanfly/jobs-scraper", "danielcanfly/jobs-scraper"),
        ("https://github.com/danielcanfly/jobs-scraper/", "danielcanfly/jobs-scraper"),
        ("ssh://git@github.com/danielcanfly/jobs-scraper.git", "danielcanfly/jobs-scraper"),
    ],
)
def test_remote_urls_normalise_to_one_repository(url: str, expected: str) -> None:
    assert _load_guard().repo_slug(url) == expected


def test_the_guard_skips_a_checkout_without_an_origin(monkeypatch, capsys) -> None:
    """The plugin runtime and a working copy have their own tracked sets.

    Their tracked files are their own — the runtime tracks the Mavis-specific
    files, a working copy tracks whatever is left on that machine — so the
    guard has to recognise that it is not in the upstream checkout instead of
    failing on a file set it was never meant to judge.
    """
    guard = _load_guard()
    monkeypatch.setattr(guard, "origin_remote", lambda: None)
    assert guard.main() == 0
    assert "SKIPPED" in capsys.readouterr().out


def test_the_guard_skips_a_different_origin(monkeypatch, capsys) -> None:
    guard = _load_guard()
    monkeypatch.setattr(guard, "origin_remote", lambda: "https://github.com/someone/else.git")
    assert guard.main() == 0
    assert "SKIPPED" in capsys.readouterr().out
