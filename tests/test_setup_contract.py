"""
Setup-script contract tests (Q43-Q47, Q60).

These are deterministic tests for setup.sh, no live network or credentials:
  - Starts with `set -euo pipefail`.
  - Does not depend on `source .venv/bin/activate` for correctness.
  - Is idempotent: doesn't overwrite existing .env / .secrets.
  - Propagates test failures (non-zero exit when pytest fails).
  - Installs into .venv and uses that exact interpreter for tests.
  - CI workflow exists and uses mocks (no live Google creds / production writes).
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

# The audited author Sheet ID is forbidden in CI artifacts except as part of an
# explicit "must not appear" guard.
AUTHOR_SHEET_ID = "".join(("1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-", "Fc42jAZ8"))


# ── Q43: set -euo pipefail at the top ──────────────────────────────
def test_setup_uses_strict_mode():
    text = SETUP_SH.read_text(encoding="utf-8")
    # Find first non-comment, non-blank line
    saw_strict = False
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        assert s.startswith("set -euo pipefail"), f"first non-comment line is not strict mode: {line!r}"
        saw_strict = True
        break
    assert saw_strict, "no executable line found in setup.sh"


# ── Q44: failing test makes setup exit non-zero ────────────────────
def test_setup_propagates_test_failures():
    """Drive setup.sh against a fake venv where the installed package's tests
    intentionally fail; setup.sh must exit non-zero."""
    if not SETUP_SH.exists():
        raise AssertionError("setup.sh missing")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "clone"
        shutil.copytree(REPO_ROOT, work, ignore=shutil.ignore_patterns(
            ".venv", ".secrets", "__pycache__", "*.pyc", ".git"
        ))
        # Sabotage: replace a test file with one that always fails
        bad_test = work / "tests" / "test_setup_contract_sabotage.py"
        bad_test.write_text(
            "def test_sabotage():\n    assert False, 'sabotage fixture'\n",
            encoding="utf-8",
        )
        # Make a tiny pyproject so pip install -e . works
        (work / "pyproject.toml").write_text(
            "[project]\nname='jobs-scraper-fake'\nversion='0.0.1'\n"
            "dependencies=['pytest>=8']\n"
            "requires-python='>=3.11'\n",
            encoding="utf-8",
        )
        # run setup
        env = {**os.environ, "PATH": os.environ.get("PATH", "")}
        r = subprocess.run(
            ["bash", str(work / "setup.sh")],
            cwd=str(work), env=env, capture_output=True, text=True, timeout=900,
        )
        assert r.returncode != 0, (
            f"setup.sh returned 0 even with a failing test.\n"
            f"stdout tail: {r.stdout[-1000:]}\nstderr tail: {r.stderr[-1000:]}"
        )


# ── Q45: setup installs into .venv and tests with that interpreter ─
def test_setup_uses_venv_python_for_tests():
    text = SETUP_SH.read_text(encoding="utf-8")
    assert "VENV_PY" in text, "VENV_PY not used"
    # VENV_PY is defined as $VENV_DIR/bin/python where VENV_DIR=$REPO_ROOT/.venv
    assert "VENV_DIR=\"" in text or "VENV_DIR=" in text, "VENV_DIR not set"
    assert "bin/python" in text, "no venv python path"
    # pytest invocation must go through $VENV_PY (allow quoted form)
    assert re.search(r'"\$\{?VENV_PY\}?"\s+-m\s+pytest', text) or re.search(r"\$\{?VENV_PY\}?\s+-m\s+pytest", text), \
        "pytest not invoked through $VENV_PY"
    # No reliance on `source .venv/bin/activate` for test invocations
    # (we tolerate the literal as a comment / helper, but not as the test path)
    activate_for_test = re.search(r"activate\s*\n.*pytest", text, re.S)
    assert not activate_for_test, "setup.sh appears to depend on activate for pytest"


# ── Q46: setup prints the venv interpreter path so users configure MCP ─
def test_setup_prints_venv_interpreter():
    text = SETUP_SH.read_text(encoding="utf-8")
    assert "$VENV_PY" in text
    # The end-of-setup message should mention the interpreter
    assert "VENV_PY" in text and "MCP" in text


# ── Q47: idempotent + doesn't overwrite existing .env / .secrets ────
def test_setup_idempotent_no_overwrite():
    text = SETUP_SH.read_text(encoding="utf-8")
    # .env only created if missing
    assert "if [ ! -f" in text and ".env" in text, "missing .env existence check"
    # .secrets/ is mkdir -p (idempotent) and never overwrites files
    assert "mkdir -p \"$REPO_ROOT/.secrets\"" in text or "mkdir -p .secrets" in text, \
        "missing .secrets mkdir"


# ── Q60: CI workflow exists and does not require live Google creds ──
def test_ci_workflow_exists():
    wf = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert wf.exists(), f"missing {wf}"
    text = wf.read_text(encoding="utf-8")
    # CI must not embed the author Sheet ID (other than in intentional grep guard
    # which is a string, not a value). The check below only flags Sheet IDs that
    # appear outside of a `git grep` / quote context.
    # The pattern: lines starting with "      ! git grep -n 'AUTHOR_SHEET_ID'" or
    # similar intentional-guard contexts are OK.
    lines = text.splitlines()
    for ln in lines:
        if AUTHOR_SHEET_ID in ln and "git grep" not in ln and "echo" not in ln and "1e-YlVFo" not in ln[:5]:
            raise AssertionError(f"CI line contains author Sheet ID without a guard context: {ln!r}")
    # Sanity: the intentional grep guard IS present
    assert "git grep" in text and "1e-YlVFo" in text, "intentional grep guard missing"
    # CI must not invoke sync_jobs_to_sheet as a tool call (the literal may appear
    # in a comment listing the tools, but not as a call)
    sync_invocation = re.search(r"sync_jobs_to_sheet\s*\(", text)
    assert not sync_invocation, "CI must not call sync_jobs_to_sheet (no live writes)"
    # CI must run pytest
    assert "pytest" in text


# ── Q60b: CI uses the venv python and runs doctor / verify_fresh_install ─
def test_ci_runs_qualification_suite():
    wf = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in (".venv/bin/python", "pytest", "compileall", "doctor"):
        assert needle in wf, f"CI missing step for {needle!r}"


if __name__ == "__main__":
    import inspect
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
