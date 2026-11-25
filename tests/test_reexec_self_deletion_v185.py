"""A re-exec script must never delete the original, and must never re-enter the parent's work.

Three scripts copy themselves into a temporary file and run that copy: bash
reads a running script incrementally, and each of them overwrites the
directory it lives in, so the file being executed would be rewritten
underneath it.

Two things follow, and both were got wrong at first.

**The copy's cleanup must name the copy, not the running script.** The state
that says "you are already the copy" is exported, so a child process inherits
it — and a child that inherits it would skip the re-exec and run the original
in place. If the cleanup named `BASH_SOURCE[0]`, that child would delete the
original. The release script's own pytest run did exactly that:
`ops/release.sh` was gone from the repository when the run finished.

**The re-exec must happen even when the state is inherited.** The same
exported state carries the path the script should treat as its own origin. A
child that inherits it and skips the re-exec therefore resolves the parent's
repository — and the release script ran its own release, in a loop, each layer
starting a pytest that started the next layer. The re-exec is keyed on
comparing the running script's own path with the temporary copy's path, so a
child that inherits the state re-execs on its own terms and works on its own
directory.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# (relative path, the state prefix, the temporary-copy name pattern)
SCRIPTS: tuple[tuple[str, str, str], ...] = (
    ("scripts/sync-from-repo.sh", "_JOBS_SCRAPER_SYNC_REPO", "jobs-scraper-sync-self-XXXXXX.*"),
    ("scripts/sync-working-copy.sh", "_JOBS_SCRAPER_SYNC_WC", "jobs-scraper-wc-sync-self-XXXXXX.*"),
    ("ops/release.sh", "_JOBS_SCRAPER_RELEASE", "jobs-scraper-release-self-XXXXXX.*"),
)


def _env_with_state(prefix: str) -> dict[str, str]:
    """An environment that looks like a child process inherited the state."""
    env = dict(os.environ)
    env[f"{prefix}_SELF"] = str(REPO_ROOT / "does-not-exist")
    env[f"{prefix}_ORIGIN"] = str(REPO_ROOT / "scripts" / "does-not-exist.sh")
    return env


def _run(rel: str, env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(REPO_ROOT / rel), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _temp_copies(pattern: str) -> set[str]:
    return set(glob.glob(os.path.join(tempfile.gettempdir(), pattern)))


@pytest.mark.parametrize(("rel", "prefix", "pattern"), SCRIPTS)
def test_a_child_that_inherits_the_state_does_not_delete_the_script(rel: str, prefix: str, pattern: str) -> None:
    script = REPO_ROOT / rel
    before = script.read_bytes()

    result = _run(rel, _env_with_state(prefix), "--help")

    assert script.is_file(), f"{rel} was deleted by a child that inherited the state"
    assert script.read_bytes() == before, f"{rel} was modified by a child that inherited the state"
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("rel", "prefix", "pattern"), SCRIPTS)
def test_the_temporary_copy_is_cleaned_up(rel: str, prefix: str, pattern: str) -> None:
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("_JOBS_SCRAPER_") and (key.endswith("_SELF") or key.endswith("_ORIGIN")):
            env.pop(key)

    before = _temp_copies(pattern)
    result = _run(rel, env, "--help")

    assert result.returncode == 0, result.stdout + result.stderr
    after = _temp_copies(pattern)
    assert after <= before, f"the temporary copy was left behind: {after - before}"


@pytest.mark.parametrize(("rel", "prefix", "pattern"), SCRIPTS)
def test_the_script_re_execs_on_its_own_terms(rel: str, prefix: str, pattern: str) -> None:
    """The re-exec is keyed on the running script's own path, not on a flag."""
    text = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "exec bash" in text, f"{rel} does not re-exec from a temporary copy"
    assert f'[ "${{BASH_SOURCE[0]}}" != "${{{prefix}_SELF:-}}" ]' in text, (
        f"{rel} does not key its re-exec on its own path"
    )
    assert f"trap 'rm -f -- \"${{{prefix}_SELF}}\"' EXIT" in text, f"{rel} does not clean up the temporary copy by name"


def test_a_release_run_from_a_copy_does_not_use_the_parents_repository() -> None:
    """A copy of the release script works on its own directory, not the parent's.

    This is the loop: the release script's pytest run starts the release
    script again, and if the copy inherits the parent's origin it starts the
    parent's release — which starts another pytest, which starts another copy.
    """
    tmp = Path(tempfile.mkdtemp(prefix="jobs-scraper-release-copy-"))
    try:
        ops = tmp / "ops"
        ops.mkdir()
        shutil.copy2(REPO_ROOT / "ops" / "release.sh", ops / "release.sh")

        env = dict(os.environ)
        env["_JOBS_SCRAPER_RELEASE_SELF"] = str(tmp / "does-not-exist")
        env["_JOBS_SCRAPER_RELEASE_ORIGIN"] = str(REPO_ROOT / "ops" / "release.sh")

        result = subprocess.run(
            ["bash", str(ops / "release.sh"), "--dry-run"],
            cwd=tmp,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    repo_line = next((line for line in result.stdout.splitlines() if "repo:" in line), "")
    assert repo_line, f"the script printed no repository line:\n{result.stdout}"
    assert repo_line.split(None, 1)[1].strip() == str(tmp), (
        "the copy resolved the repository from the inherited origin instead of its own location"
    )
    # It stops at the first gate: the copy is not a checkout.
    assert result.returncode == 1
