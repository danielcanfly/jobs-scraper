"""The release flow has to be one command, and it has to refuse a dirty tree.

Every step of a release used to live in somebody's memory: push, tag, sync the
plugin runtime, sync the working copy, verify all three. v1.8.3 is how that
showed up — the working copy was missing the whole `ops/` directory, 35 tracked
files, until somebody ran the copy loop by hand. `ops/release.sh` collects the
steps, and it checks before it acts: a release that starts from a tree with
uncommitted changes is a release of something nobody reviewed.

These tests never run the release itself. They run the parts that end before
anything is pushed or tagged.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "ops" / "release.sh"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_release_script_is_in_the_tree() -> None:
    assert SCRIPT.is_file(), "the release script has to be in the tree, or it never travels"
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_help_prints_the_usage() -> None:
    result = _run("--help")
    assert result.returncode == 0
    assert "release.sh" in result.stdout
    assert "--dry-run" in result.stdout


def test_an_unknown_argument_is_rejected() -> None:
    result = _run("--publish-everything")
    assert result.returncode == 2


def test_a_dirty_tree_stops_the_release_before_anything_is_pushed() -> None:
    """The first thing the release does is check the tree, and it stops there.

    The marker file makes the tree dirty on purpose, so the script cannot get
    past its first gate — it never reaches the push, the tag or the sync.
    """
    marker = REPO_ROOT / ".release-script-dirty-marker"
    assert not marker.exists(), "the marker file should not be left behind"
    marker.write_text("dirty\n", encoding="utf-8")
    try:
        result = _run("--dry-run")
    finally:
        marker.unlink()

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "發布中止" in output
    assert "推送與 tag" not in output, "the release must not reach the push stage"
    assert not marker.exists()


def test_a_checkout_that_is_not_a_git_repository_is_refused() -> None:
    """A check that cannot read the tree must not be read as "clean".

    The fresh-install harness copies the repository without its `.git`, so the
    release script can be run from a directory that is not a checkout at all.
    `git status` fails there — and a failure is not the same answer as "the
    working tree is clean".
    """
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="jobs-scraper-not-a-repo-"))
    try:
        ops = tmp / "ops"
        ops.mkdir()
        shutil.copy2(SCRIPT, ops / "release.sh")
        result = subprocess.run(
            ["bash", str(ops / "release.sh"), "--dry-run"],
            cwd=tmp,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    assert result.returncode == 1
    output = result.stdout + result.stderr
    assert "發布中止" in output
    assert "推送與 tag" not in output, "the release must not reach the push stage"


def test_a_tag_that_does_not_point_at_head_stops_the_release(tmp_path: Path) -> None:
    """A published tag is a record; the release does not move it silently."""
    repo = tmp_path / "repo"
    (repo / "ops").mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "ops" / "release.sh")
    (repo / "pyproject.toml").write_text('[project]\nname = "jobs-scraper"\nversion = "9.9.9"\n', encoding="utf-8")

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    git("add", "-A")
    git("commit", "-qm", "one")
    git("tag", "-a", "v9.9.9", "-m", "one")
    (repo / "second.txt").write_text("two\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "two")

    result = subprocess.run(
        ["bash", str(repo / "ops" / "release.sh"), "--dry-run"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "發布中止" in output
    assert "v9.9.9" in output
    assert "推送與 tag" not in output, "the release must not reach the push stage"


def test_the_release_script_never_pushes_before_the_checks_pass() -> None:
    """The order is the point: checks, then push. Read it, don't run it."""
    text = SCRIPT.read_text(encoding="utf-8")
    checks = text.index("──── 2. 守衛 ────")
    push = text.index("──── 3. 推送與 tag ────")
    assert checks < push, "the guards have to run before anything is pushed"
    assert "git push origin main" in text
    assert "check_version_line.py" in text, "a release has to agree on its own version"
