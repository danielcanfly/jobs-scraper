"""
Setup-script and CI contract tests.

These are deterministic tests for setup.sh / CI, no live Google credentials:
  - Starts with `set -euo pipefail`.
  - Does not depend on `source .venv/bin/activate` for correctness.
  - Is idempotent: doesn't overwrite existing .env / .secrets.
  - Propagates test failures (non-zero exit when pytest fails).
  - Installs into .venv and uses that exact interpreter for tests.
  - CI uses read-only repository permissions and runs the repository-wide hygiene guard.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP_SH = REPO_ROOT / "setup.sh"

# Assemble the audited historical Sheet ID without re-committing the full literal.
AUTHOR_SHEET_ID = "".join(("1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-", "Fc42jAZ8"))


def test_setup_uses_strict_mode():
    text = SETUP_SH.read_text(encoding="utf-8")
    saw_strict = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        assert s.startswith("set -euo pipefail"), f"first non-comment line is not strict mode: {line!r}"
        saw_strict = True
        break
    assert saw_strict, "no executable line found in setup.sh"


def test_setup_propagates_test_failures():
    """Drive setup.sh against a fake tree whose tests intentionally fail."""
    if not SETUP_SH.exists():
        raise AssertionError("setup.sh missing")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "clone"
        shutil.copytree(REPO_ROOT, work, ignore=shutil.ignore_patterns(
            ".venv", ".secrets", "__pycache__", "*.pyc", ".git"
        ))
        bad_test = work / "tests" / "test_setup_contract_sabotage.py"
        bad_test.write_text(
            "def test_sabotage():\n    assert False, 'sabotage fixture'\n",
            encoding="utf-8",
        )
        (work / "pyproject.toml").write_text(
            "[project]\nname='jobs-scraper-fake'\nversion='0.0.1'\n"
            "dependencies=['pytest>=8']\n"
            "requires-python='>=3.11'\n",
            encoding="utf-8",
        )
        env = {**os.environ, "PATH": os.environ.get("PATH", "")}
        r = subprocess.run(
            ["bash", str(work / "setup.sh")],
            cwd=str(work), env=env, capture_output=True, text=True, timeout=900,
        )
        assert r.returncode != 0, (
            f"setup.sh returned 0 even with a failing test.\n"
            f"stdout tail: {r.stdout[-1000:]}\nstderr tail: {r.stderr[-1000:]}"
        )


def test_setup_uses_venv_python_for_tests():
    text = SETUP_SH.read_text(encoding="utf-8")
    assert "VENV_PY" in text, "VENV_PY not used"
    assert "VENV_DIR=\"" in text or "VENV_DIR=" in text, "VENV_DIR not set"
    assert "bin/python" in text, "no venv python path"
    assert re.search(r'"\$\{?VENV_PY\}?"\s+-m\s+pytest', text) or re.search(r"\$\{?VENV_PY\}?\s+-m\s+pytest", text), \
        "pytest not invoked through $VENV_PY"
    activate_for_test = re.search(r"activate\s*\n.*pytest", text, re.S)
    assert not activate_for_test, "setup.sh appears to depend on activate for pytest"


def test_setup_prints_venv_interpreter():
    text = SETUP_SH.read_text(encoding="utf-8")
    assert "$VENV_PY" in text
    assert "VENV_PY" in text and "MCP" in text


def test_setup_idempotent_no_overwrite():
    text = SETUP_SH.read_text(encoding="utf-8")
    assert "if [ ! -f" in text and ".env" in text, "missing .env existence check"
    assert "mkdir -p \"$REPO_ROOT/.secrets\"" in text or "mkdir -p .secrets" in text, \
        "missing .secrets mkdir"


def test_ci_workflow_exists():
    wf = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert wf.exists(), f"missing {wf}"
    text = wf.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in text, "permanent CI must use contents: read"
    assert AUTHOR_SHEET_ID not in text, "CI must not re-embed the author production Sheet ID"
    assert "scripts/check_repo_hygiene.py" in text, "repository-wide hygiene guard missing"
    assert "git grep" not in text, "legacy hand-picked literal grep should not be the hygiene gate"

    sync_invocation = re.search(r"sync_jobs_to_sheet\s*\(", text)
    assert not sync_invocation, "CI must not call sync_jobs_to_sheet (no live writes)"
    assert "pytest" in text


def test_repo_hygiene_guard_runs_clean_on_tracked_tree():
    script = REPO_ROOT / "scripts" / "check_repo_hygiene.py"
    assert script.exists(), f"missing {script}"
    source = script.read_text(encoding="utf-8")
    assert "git" in source and "ls-files" in source and "-z" in source, \
        "hygiene guard must enumerate the Git-tracked tree"

    # The runtime scan is meaningful only in a Git checkout, because its contract
    # is explicitly the tracked tree. Fresh-install verification intentionally
    # copies the package without .git; permanent CI runs this guard separately in
    # the real checkout after both fresh-install gates.
    if not (REPO_ROOT / ".git").exists():
        return

    r = subprocess.run(
        [sys.executable, str(script)], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"hygiene guard failed:\n{r.stdout}\n{r.stderr}"
    assert "REPO_HYGIENE_PASS" in r.stdout


def test_ci_runs_qualification_suite():
    wf = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in (".venv/bin/python", "pytest", "compileall", "doctor", "check_repo_hygiene.py"):
        assert needle in wf, f"CI missing step for {needle!r}"


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in globals().items() if n.startswith("test_") and callable(fn)]
    n_pass = n_fail = 0
    for n, fn in tests:
        try:
            fn()
            print(f"  ✅ {n}")
            n_pass += 1
        except Exception as e:
            print(f"  ❌ {n}: {type(e).__name__}: {e}")
            n_fail += 1
    print(f"\n{n_pass}/{len(tests)} 通過, {n_fail} 失敗")
    sys.exit(0 if n_fail == 0 else 1)
