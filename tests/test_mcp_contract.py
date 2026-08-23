"""
MCP v2 contract tests (Q14-Q32).

These tests load the MCP server module, list tools via MCPServer.list_tools(),
and assert the schema/annotation/contract requirements from 04_MCP_CONTRACT.md
without requiring a live MCP transport or Google credentials.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# Lazy: import the server module only once.
_SERVER = None


def _server():
    global _SERVER
    if _SERVER is None:
        import server  # noqa: F401
        _SERVER = server
    return _SERVER


def _tools():
    return _run(_server().mcp.list_tools())


def _by_name(name: str):
    for t in _tools():
        if t.name == name:
            return t
    raise AssertionError(f"tool {name!r} not registered; saw {[t.name for t in _tools()]}")


# ── Q14: dependency resolves to MCP v2 ─────────────────────────────
def test_dependency_pinned_to_v2():
    req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # v2 line only — no <2 ceiling
    assert re.search(r"^mcp[><=,\s0-9.]*2(\.0+)?[,\s<>=]", req, re.M), f"requirements.txt must pin mcp>=2: {req!r}"
    # explicitly check no <2 ceiling remains
    assert not re.search(r"^mcp[><=,\s0-9.]*<2", req, re.M), f"must not pin <2: {req!r}"
    # pyproject: same check
    assert re.search(r'"?mcp[><=,\s0-9.]*2(\.0+)?[,\s<>=]"?', pyproject), "pyproject.toml must pin mcp>=2"
    # import the actual installed package to confirm v2
    import mcp
    from importlib.metadata import version
    v = version("mcp")
    assert v.startswith("2."), f"installed mcp is not v2: {v}"


# ── Q15: server uses MCPServer (not FastMCP) ───────────────────────
def test_server_uses_mcpserver_v2():
    # Force fresh import
    sys.modules.pop("server", None)
    import server  # noqa: F401
    s = server
    # class name in v2 is MCPServer
    assert s.mcp.__class__.__name__ == "MCPServer", f"got {s.mcp.__class__.__name__}"
    # not v1 FastMCP
    assert "fastmcp" not in s.mcp.__class__.__module__.lower(), \
        f"module should not be mcp.server.fastmcp: {s.mcp.__class__.__module__}"
    # source file does not import FastMCP
    src = (REPO_ROOT / "server.py").read_text(encoding="utf-8")
    assert "FastMCP" not in src, "server.py must not reference FastMCP (v1)"
    assert "MCPServer" in src, "server.py must import MCPServer"


# ── Q16: canonical tools present ───────────────────────────────────
def test_canonical_tools_present():
    names = {t.name for t in _tools()}
    expected = {"crawl_jobs", "sync_jobs_to_sheet", "audit_sheet", "get_stats"}
    assert expected.issubset(names), f"missing tools: {expected - names}"


# ── Q17: crawl_jobs cannot accept a Sheet write target ─────────────
def test_crawl_jobs_has_no_sheet_write_param():
    t = _by_name("crawl_jobs")
    props = (t.input_schema or {}).get("properties") or {}
    forbidden = {"to_sheet", "sheet_id", "gid", "dry_run"}
    leaked = forbidden & set(props.keys())
    assert not leaked, f"crawl_jobs leaks Sheet write params: {leaked}"


# ── Q18: sync_jobs_to_sheet is the explicit write tool ─────────────
def test_sync_jobs_to_sheet_present_as_write():
    t = _by_name("sync_jobs_to_sheet")
    assert t.annotations.read_only_hint is False
    assert t.annotations.open_world_hint is True
    assert t.annotations.destructive_hint is False
    assert t.annotations.idempotent_hint is False


# ── Q19: source input restricted to linkedin/jora/jobstreet ────────
def test_source_input_enum():
    t = _by_name("crawl_jobs")
    enum = (t.input_schema["properties"]["source"].get("enum") or [])
    assert enum == ["linkedin", "jora", "jobstreet"], f"got {enum}"


# ── Q20: range input restricted to 7 supported ranges ──────────────
def test_range_input_enum():
    t = _by_name("crawl_jobs")
    enum = (t.input_schema["properties"]["range"].get("enum") or [])
    assert enum == ["1h", "24h", "3d", "7d", "14d", "21d", "30d"], f"got {enum}"


# ── Q21: max_pages bounded ─────────────────────────────────────────
def test_max_pages_bounded():
    t = _by_name("crawl_jobs")
    schema = t.input_schema["properties"]["max_pages"]
    any_of = schema.get("anyOf") or [schema]
    found_int = False
    for sub in any_of:
        if sub.get("type") == "integer":
            assert sub.get("minimum") == 1, f"min != 1: {sub}"
            assert sub.get("maximum") is not None and sub["maximum"] <= 1000, f"max too large: {sub}"
            found_int = True
    assert found_int, f"no integer bounded shape: {schema}"


# ── Q22: crawl_jobs annotation (read-only, open-world) ─────────────
def test_crawl_jobs_annotations():
    t = _by_name("crawl_jobs")
    assert t.annotations.read_only_hint is True
    assert t.annotations.open_world_hint is True


# ── Q23: audit_sheet annotation (read-only, NOT open-world) ────────
def test_audit_sheet_annotations():
    t = _by_name("audit_sheet")
    assert t.annotations.read_only_hint is True
    assert t.annotations.open_world_hint is False


# ── Q24: get_stats annotation (read-only, NOT open-world) ──────────
def test_get_stats_annotations():
    t = _by_name("get_stats")
    assert t.annotations.read_only_hint is True
    assert t.annotations.open_world_hint is False


# ── Q26: all canonical tools publish output schemas ────────────────
def test_all_canonical_tools_have_output_schema():
    for name in ("crawl_jobs", "sync_jobs_to_sheet", "audit_sheet", "get_stats"):
        t = _by_name(name)
        assert t.output_schema is not None, f"{name} missing output_schema"


# ── Q27: invalid source rejected before subprocess execution ───────
def test_invalid_source_rejected_by_pydantic():
    from pydantic import ValidationError
    from server import CrawlResult
    try:
        CrawlResult(
            ok=True, source="bad", range="7d", with_jd=False, exit_code=0,
            message="x",  # type: ignore[arg-type]
        )
    except ValidationError:
        return
    raise AssertionError("expected ValidationError for invalid source")


# ── Q28: invalid range rejected by pydantic ────────────────────────
def test_invalid_range_rejected_by_pydantic():
    from pydantic import ValidationError
    from server import CrawlResult
    try:
        CrawlResult(
            ok=True, source="linkedin", range="99h", with_jd=False, exit_code=0,
            message="x",  # type: ignore[arg-type]
        )
    except ValidationError:
        return
    raise AssertionError("expected ValidationError for invalid range")


# ── Q29: subprocess uses sys.executable / list args / cwd ──────────
def test_subprocess_uses_sys_executable_and_cwd():
    import server
    import inspect
    src = inspect.getsource(server)
    # subprocess.run with list args (not shell=True string)
    assert re.search(r"subprocess\.run\(\s*\n?\s*cmd", src), "subprocess.run cmd arg not found"
    assert "shell=True" not in src, "shell=True forbidden"
    # sys.executable is the interpreter (also set PYTHON_EXE)
    assert "sys.executable" in src
    assert "PYTHON_EXE" in src
    # cwd is REPO_ROOT
    assert "REPO_ROOT" in src


# ── Q30: subprocess timeout >= 7200s ───────────────────────────────
def test_subprocess_timeout_default_7200():
    import server
    assert int(server.SUBPROCESS_TIMEOUT) >= 7200, f"timeout too low: {server.SUBPROCESS_TIMEOUT}"


# ── Q31: timeout returns structured failure (not just success text) ─
def test_timeout_returns_structured_failure():
    """Drive _run_subprocess with a 1s timeout and a sleep; assert ok=False, error_code=SUBPROCESS_TIMEOUT."""
    import server
    r = server._run_subprocess(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=1, raw=True,
    )
    assert r["ok"] is False
    assert r["timed_out"] is True
    assert r["error_code"] == "SUBPROCESS_TIMEOUT"


# ── Q32: non-zero exit returns ok=False / error_code ───────────────
def test_nonzero_exit_returns_structured_failure():
    import server
    r = server._run_subprocess(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        timeout=10, raw=True,
    )
    assert r["ok"] is False
    assert r["exit_code"] == 7
    assert r["error_code"] in {"SCRAPER_EXIT_NONZERO", "UPSTREAM_RATE_LIMIT"}


# ── Q31/Q32 supplementary: server has instructions mentioning the contract
def test_server_instructions_present_and_explicit():
    import server
    inst = server.mcp.instructions or ""
    for needle in ("sync_jobs_to_sheet", "CONFIG_MISSING", "untrusted", "7200"):
        assert needle in inst, f"instructions missing {needle!r}: {inst!r}"


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
