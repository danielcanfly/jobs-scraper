from __future__ import annotations

import inspect

import runtime_core as RT
import server
import server_v1_1


def test_legacy_server_runtime_names_are_compatibility_aliases():
    assert server.REPO_ROOT == RT.REPO_ROOT
    assert server.PYTHON_EXE == RT.PYTHON_EXE
    assert server.SUBPROCESS_TIMEOUT == RT.SUBPROCESS_TIMEOUT
    assert server.SUMMARY_PREFIX == RT.SUMMARY_PREFIX
    assert server._run_subprocess is RT.run_scraper_subprocess
    assert server._parse_machine_summary is RT.parse_machine_summary


def test_v11_server_uses_shared_runtime_not_legacy_private_helpers():
    source = inspect.getsource(server_v1_1)
    for forbidden in (
        "legacy._run_subprocess",
        "legacy._parse_machine_summary",
        "legacy.REPO_ROOT",
        "legacy.Source",
        "legacy.Range",
    ):
        assert forbidden not in source
    assert "RT.run_scraper_subprocess" in source
    assert "RT.parse_machine_summary" in source
    assert "RT.REPO_ROOT" in source


def test_shared_runtime_owns_subprocess_and_summary_implementation():
    source = inspect.getsource(RT)
    assert "subprocess.run" in source
    assert "cwd=str(REPO_ROOT)" in source
    assert "sys.executable" in source
    assert "JOBS_SCRAPER_SUMMARY=" in source
    assert "UPSTREAM_RATE_LIMIT" in source
    assert "SUBPROCESS_TIMEOUT" in source


def test_shared_machine_summary_matches_legacy_alias_contract():
    text = 'noise\nJOBS_SCRAPER_SUMMARY={"jobs_found":7,"written":3}\n'
    expected = {"jobs_found": 7, "written": 3}
    assert RT.parse_machine_summary(text) == expected
    assert server._parse_machine_summary(text) == expected
    assert RT.parse_machine_summary("human prose only") is None
