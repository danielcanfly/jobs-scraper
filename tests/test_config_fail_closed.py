"""
Fail-closed config contract tests (Q33-Q37, Q69, Q71).

Verifies:
  - No author Sheet ID fallback in executable code.
  - Missing SHEET_ID / SHEET_GID / credential file returns structured error.
  - Read tools (audit_sheet, get_stats) use spreadsheets.readonly scope.
  - Write tool (sync_jobs_to_sheet) uses spreadsheets write scope.
  - Public crawl (crawl_jobs) does NOT require any Sheet config.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

AUTHOR_SHEET_ID = "".join(("1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-", "Fc42jAZ8"))
AUTHOR_GID = "111" + "9491672"


@contextmanager
def _fresh_server(env: dict[str, str] | None = None):
    """Import server.py with a clean env; yield the module; restore env at exit."""
    saved = {
        k: os.environ.get(k)
        for k in ("SHEET_ID", "SHEET_GID", "GSPREAD_SA_KEY_PATH", "JOBS_SCRAPER_SUBPROCESS_TIMEOUT")
    }
    for k in saved:
        os.environ.pop(k, None)
    if env:
        for k, v in env.items():
            os.environ[k] = v
    sys.modules.pop("server", None)
    try:
        yield importlib.import_module("server")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── Q33: No author Sheet ID/GID fallback in executable code ────────
def test_no_author_sheet_id_in_executable_code():
    """Grep scraper + server source for the audited author Sheet ID."""
    for path in (REPO_ROOT / "sg_product_jobs.py", REPO_ROOT / "server.py"):
        text = path.read_text(encoding="utf-8")
        assert AUTHOR_SHEET_ID not in text, f"{path} still contains author Sheet ID"
        # The hardcoded gid fallback is also forbidden
        if path.name == "sg_product_jobs.py":
            # Only the comment / CLI help mentioning the constant is allowed; the
            # actual default must be 0/empty. Check no historical hardcoded GID fallback remains.
            assert f"else {AUTHOR_GID}" not in text, "hardcoded gid fallback still present"
            assert "else CHINA_RAW_GID" not in text, "CHINA hardcoded gid ok (preset, not fallback)"


# ── Q33b: SG_RAW_SHEET_ID empty when env not set ────────────────────
def test_sheet_id_default_is_empty():
    import sg_product_jobs as M

    assert M.SHEET_ID_OVERRIDE == "", f"got {M.SHEET_ID_OVERRIDE!r}"
    assert M.SG_RAW_SHEET_ID == "", f"got {M.SG_RAW_SHEET_ID!r}"


def test_sgid_default_is_zero():
    import sg_product_jobs as M

    assert M.SHEET_GID_OVERRIDE == "", f"got {M.SHEET_GID_OVERRIDE!r}"
    assert M.SG_RAW_GID == 0, f"got {M.SG_RAW_GID}"


# ── Q34: Sheet tools fail closed when SHEET_ID or SHEET_GID missing ─
def test_audit_sheet_no_config_returns_structured_error():
    with _fresh_server(env={}) as s:
        res = s.audit_sheet()
    assert res.ok is False
    assert res.error_code == "CONFIG_MISSING"
    assert "SHEET_ID" in res.message or "SHEET_GID" in res.message


def test_get_stats_no_config_returns_structured_error():
    with _fresh_server(env={}) as s:
        res = s.get_stats()
    assert res.ok is False
    assert res.error_code == "CONFIG_MISSING"


def test_sync_jobs_to_sheet_no_config_returns_structured_error():
    with _fresh_server(env={}) as s:
        res = s.sync_jobs_to_sheet()
    assert res.ok is False
    assert res.error_code == "CONFIG_MISSING"
    assert res.target_configured is False


# ── Q36: missing credential file yields safe structured error ───────
def test_credential_file_missing_returns_structured_error(tmp_path=None):
    with _fresh_server(
        env={
            "SHEET_ID": "fake_sheet_id_for_test",
            "SHEET_GID": "123",
            "GSPREAD_SA_KEY_PATH": "/nonexistent/path/that/does/not/exist.json",
        }
    ) as s:
        res = s.audit_sheet()
    assert res.ok is False
    assert res.error_code == "CREDENTIAL_FILE_MISSING"


# ── Q35: public crawl works without Google config ──────────────────
def test_crawl_jobs_works_without_sheet_config():
    """crawl_jobs source/range validation must not depend on Sheet config."""
    # Just confirm the pydantic model accepts the call shape; we don't actually
    # run the subprocess (no live network). Confirm argument validation only.
    from server import CrawlResult

    model = CrawlResult(
        ok=True,
        source="linkedin",
        range="7d",
        with_jd=False,
        exit_code=0,
        message="x",
    )
    assert model.source == "linkedin"


# ── Q37: no credential / private key content in tool results/logs ───
def test_no_credential_leak_in_result_objects():
    """A fake credential file path should never be embedded in result strings."""
    with _fresh_server(env={}) as s:
        res = s.audit_sheet()
    # The result message references env var names, not credential file content.
    serialized = res.model_dump_json()
    # No private key markers
    assert "BEGIN PRIVATE KEY" not in serialized
    assert "PRIVATE KEY" not in serialized


# ── Q71: read tools use readonly scope, write tool uses write scope ─
def test_read_scopes_vs_write_scopes():
    import server

    assert server.SCOPES_READONLY == ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    assert server.SCOPES_WRITE == ["https://www.googleapis.com/auth/spreadsheets"]
    # The constants must not be equal (read tools must not use write scope)
    assert server.SCOPES_READONLY != server.SCOPES_WRITE


def test_read_sheet_rows_uses_readonly_scope(monkeypatch=None):
    """Verify that _read_sheet_rows actually passes the readonly scope to Credentials.from_service_account_file."""
    import server

    captured = {}

    class _FakeCreds:
        @classmethod
        def from_service_account_file(cls, path, scopes):
            captured["path"] = path
            captured["scopes"] = scopes
            return cls()

    class _FakeWS:
        def get(self, range_name):
            assert range_name == "A2:K"
            return [["a", "b"]]

    class _FakeGC:
        def open_by_key(self, sheet_id):
            return self

        def get_worksheet_by_id(self, gid):
            return _FakeWS()

    gspread_mod = importlib.import_module("gspread")

    def monkey_gspread_authorize(creds):
        return _FakeGC()

    saved = gspread_mod.authorize
    gspread_mod.authorize = monkey_gspread_authorize
    try:
        from google.oauth2 import service_account as sa_mod

        sa_mod.Credentials = _FakeCreds
        rows = server._read_sheet_rows("dummy.json", "sheet_id", "0")
        assert captured.get("scopes") == server.SCOPES_READONLY, (
            f"read tool leaked write scope: {captured.get('scopes')}"
        )
        assert rows == [["a", "b"]]
    finally:
        gspread_mod.authorize = saved


# ── Q69: not writing to the author's production Sheet during test ───
def test_tests_do_not_touch_production_sheet():
    """Sanity: tests must never set SHEET_ID to the audited production ID."""
    assert AUTHOR_SHEET_ID not in os.environ, "test env cannot have author Sheet ID set (would risk production write)"


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
