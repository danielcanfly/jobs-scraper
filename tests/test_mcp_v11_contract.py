from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _tools():
    import server_v1_1

    return _run(server_v1_1.mcp.list_tools())


def _by_name(name: str):
    for tool in _tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"tool {name!r} missing; saw {[t.name for t in _tools()]}")


def test_v11_server_version_and_tool_set():
    import server_v1_1

    assert server_v1_1.mcp.version == "1.2.1"
    assert {t.name for t in _tools()} == {
        "crawl_jobs",
        "initialize_job_tracker",
        "sync_jobs_to_sheet",
        "audit_sheet",
        "get_stats",
    }


def test_sync_is_region_aware_and_does_not_expose_gid():
    tool = _by_name("sync_jobs_to_sheet")
    props = tool.input_schema["properties"]
    assert props["region"]["enum"] == ["SG", "TW", "China"]
    assert "gid" not in props
    assert "sheet_gid" not in props
    assert "sheet_id" not in props
    assert tool.annotations.read_only_hint is False


def test_initializer_defaults_to_preview_and_is_idempotent_hint():
    tool = _by_name("initialize_job_tracker")
    props = tool.input_schema["properties"]
    assert props["dry_run"]["default"] is True
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is False
    assert tool.annotations.idempotent_hint is True


def test_read_tools_are_region_aware_and_read_only():
    for name in ("audit_sheet", "get_stats"):
        tool = _by_name(name)
        assert tool.input_schema["properties"]["region"]["enum"] == ["SG", "TW", "China"]
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False


def test_v11_config_no_longer_requires_sheet_gid(monkeypatch, tmp_path):
    import job_tracker as JT

    key = tmp_path / "sa.json"
    key.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SHEET_ID", "user-owned-sheet-id-1234567890")
    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(key))
    monkeypatch.delenv("SHEET_GID", raising=False)
    cfg = JT.check_tracker_config()
    assert not isinstance(cfg, dict)
    assert cfg[1] == "user-owned-sheet-id-1234567890"


def test_non_sg_jora_and_jobstreet_fail_before_crawl():
    import server_v1_1

    for source in ("jora", "jobstreet"):
        ok, reason = server_v1_1._source_region_supported(source, "TW")
        assert ok is False
        assert "Singapore-only" in (reason or "")
    assert server_v1_1._source_region_supported("linkedin", "TW")[0] is True
    assert server_v1_1._source_region_supported("linkedin", "China")[0] is True
