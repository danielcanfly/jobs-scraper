from __future__ import annotations

from pathlib import Path

import pytest

import server
from jobs_scraper.mcp_services import errors, sheet_config, tracker


def test_legacy_config_typed_error_maps_to_existing_public_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("SHEET_ID", "your_google_sheet_id_here")
    monkeypatch.setenv("SHEET_GID", "0")
    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", str(tmp_path / "sa.json"))

    with pytest.raises(errors.ConfigMissing) as raised:
        sheet_config.check_legacy_sheet_config_or_raise(Path.cwd())

    public = sheet_config.check_legacy_sheet_config(Path.cwd())
    assert isinstance(public, dict)
    assert public["error_code"] == "CONFIG_MISSING"
    assert public["message"] == raised.value.message


def test_credential_typed_error_preserves_public_code(monkeypatch):
    monkeypatch.setenv("SHEET_ID", "user-sheet")
    monkeypatch.setenv("SHEET_GID", "123")
    monkeypatch.setenv("GSPREAD_SA_KEY_PATH", "/not/here.json")

    with pytest.raises(errors.CredentialFileMissing) as raised:
        sheet_config.check_legacy_sheet_config_or_raise(Path.cwd())

    assert raised.value.error_code == "CREDENTIAL_FILE_MISSING"
    assert raised.value.message == "credential file not found: /not/here.json"


def test_server_maps_typed_sheet_not_found_without_leaking_exception_name(monkeypatch):
    monkeypatch.setattr(server, "_check_sheet_config", lambda: ("/tmp/key.json", "sheet", "123"))
    monkeypatch.setattr(
        server,
        "_read_sheet_rows",
        lambda *_args: (_ for _ in ()).throw(errors.SheetNotFound("could not read sheet: RuntimeError: boom")),
    )

    result = server.audit_sheet()
    assert result.ok is False
    assert result.error_code == "SHEET_NOT_FOUND"
    assert result.message == "could not read sheet: RuntimeError: boom"
    assert "SheetNotFound" not in result.message


def test_tracker_config_dict_is_raised_as_typed_internal_error():
    with pytest.raises(errors.CredentialFileMissing) as raised:
        tracker._cfg_or_raise(lambda: {
            "ok": False,
            "error_code": "CREDENTIAL_FILE_MISSING",
            "message": "credential file not found: /tmp/nope.json",
        })
    assert raised.value.message == "credential file not found: /tmp/nope.json"


def test_tracker_public_payload_keeps_existing_error_code_and_message():
    payload = tracker.sync_region_payload(
        "TW",
        "jobstreet",
        "7d",
        with_jd=False,
        max_pages=None,
        refetch=False,
        dry_run=True,
        cfg_reader=lambda: pytest.fail("config must not be consulted"),
    )
    assert payload["ok"] is False
    assert payload["error_code"] == "SOURCE_REGION_UNSUPPORTED"
    assert payload["message"] == "jobstreet is currently Singapore-only in v1.1.0; use source='linkedin' for region=TW"
