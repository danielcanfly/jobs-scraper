"""The working copy has to reach the upstream by a command, not by memory.

Three placements carry the same build: the upstream repository, the plugin
runtime and a working copy. upstream→GitHub is a `git push`, and
GitHub→plugin is `scripts/sync-from-repo.sh`, but upstream→working copy was a
hand-typed `cp` loop that nothing checked and that nothing remembered. v1.8.3
is how that gap showed up: the working copy was missing the whole `ops/`
directory — 35 tracked files — until the loop was run by hand.

These tests run the real script against a throwaway upstream and a throwaway
working copy, so they exercise the copy, the drift check and the private-state
rules rather than a description of them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "sync-working-copy.sh"

# Files the upstream carries that must never reach a working copy.
PRIVATE_FILES = (".env", "seen_jds.jsonl")


def _make_upstream(tmp_path: Path) -> Path:
    upstream = tmp_path / "upstream"
    (upstream / "pkg").mkdir(parents=True)
    (upstream / "engine.py").write_text("VERSION = '1'\n", encoding="utf-8")
    (upstream / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (upstream / "README.md").write_text("# upstream\n", encoding="utf-8")
    (upstream / ".env.example").write_text("SHEET_ID=\n", encoding="utf-8")
    # Private state, tracked on purpose: the script has to refuse it.
    (upstream / ".env").write_text("SHEET_ID=secret\n", encoding="utf-8")
    (upstream / "seen_jds.jsonl").write_text('{"id": 1}\n', encoding="utf-8")

    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    subprocess.run(["git", "add", "-A", "-f"], cwd=upstream, check=True)
    return upstream


def _run(upstream: Path, working_copy: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(upstream.parent),
        "UPSTREAM_DIR": str(upstream),
        "JOBS_SCRAPER_WORKING_COPY": str(working_copy),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_the_script_lives_in_the_tracked_tree() -> None:
    assert SCRIPT.is_file(), "the working-copy sync has to be in the tree, or it never travels"
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_the_sync_copies_the_tracked_files(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()

    result = _run(upstream, working_copy)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (working_copy / "engine.py").read_text(encoding="utf-8") == "VERSION = '1'\n"
    assert (working_copy / "pkg" / "mod.py").is_file()
    assert (working_copy / "README.md").is_file()
    assert (working_copy / ".env.example").is_file()


def test_private_state_does_not_travel(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()

    result = _run(upstream, working_copy)

    assert result.returncode == 0, result.stdout + result.stderr
    for private in PRIVATE_FILES:
        assert not (working_copy / private).exists(), f"private state travelled: {private}"


def test_the_sync_does_not_delete_files_the_working_copy_owns(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()
    (working_copy / "my_notes.md").write_text("mine\n", encoding="utf-8")

    result = _run(upstream, working_copy)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (working_copy / "my_notes.md").read_text(encoding="utf-8") == "mine\n"


def test_verify_reports_drift_without_touching_anything(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()
    _run(upstream, working_copy)
    (working_copy / "engine.py").write_text("TAMPERED\n", encoding="utf-8")

    result = _run(upstream, working_copy, "--verify")

    assert result.returncode == 1
    assert "engine.py" in result.stdout
    assert (working_copy / "engine.py").read_text(encoding="utf-8") == "TAMPERED\n"


def test_the_sync_repairs_drift(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()
    _run(upstream, working_copy)
    (working_copy / "engine.py").write_text("TAMPERED\n", encoding="utf-8")

    result = _run(upstream, working_copy)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (working_copy / "engine.py").read_text(encoding="utf-8") == "VERSION = '1'\n"


def test_a_missing_file_is_drift(tmp_path: Path) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()
    _run(upstream, working_copy)
    (working_copy / "engine.py").unlink()

    result = _run(upstream, working_copy, "--verify")

    assert result.returncode == 1
    assert "engine.py" in result.stdout


@pytest.mark.parametrize("arg", ["--bogus"])
def test_an_unknown_argument_is_rejected(tmp_path: Path, arg: str) -> None:
    upstream = _make_upstream(tmp_path)
    working_copy = tmp_path / "work"
    working_copy.mkdir()

    result = _run(upstream, working_copy, arg)

    assert result.returncode == 2
