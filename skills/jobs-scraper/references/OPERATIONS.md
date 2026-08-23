# Operations Reference

## Supported sources

- LinkedIn guest jobs endpoints
- Jora Singapore while available
- JobStreet public/API-backed integration used by the scraper

## Time ranges

`1h`, `24h`, `3d`, `7d`, `14d`, `21d`, `30d`

## Google Sheet prerequisites

v1.1.0 Sheet operations require:

- `GSPREAD_SA_KEY_PATH`
- `SHEET_ID`

`SHEET_GID` is no longer an onboarding requirement for the v1.1.0 MCP entrypoint. The server resolves the exact `<REGION>-Raw` worksheet by name and uses its worksheet ID internally.

The Sheet must be shared with the configured service-account identity at the permission level required for the requested operation.

Do not store credential JSON in Git and do not paste service-account private keys into chat.

## First-time tracker setup

1. Create a blank Google Spreadsheet owned by the user.
2. Share it with the user's service-account identity.
3. Set `SHEET_ID` and `GSPREAD_SA_KEY_PATH`.
4. Call `initialize_job_tracker(regions=[...], dry_run=true)`.
5. Review the planned Region-Raw/Region-Selected tabs.
6. Only after explicit approval, call `initialize_job_tracker(..., dry_run=false)`.

Default regions create:

- `SG-Raw` / `SG-Selected`
- `TW-Raw` / `TW-Selected`
- `China-Raw` / `China-Selected`

Each tab is initialized with the exact `Job Tracker Schema v1` A:AA contract, frozen header row, native dropdown validation, conditional formatting, notes, date formatting, and tracker column widths.

If a non-empty target tab already exists with the wrong schema, initialization returns `SCHEMA_MISMATCH` and performs no destructive migration.

## Region routing

`sync_jobs_to_sheet(region=...)`, `audit_sheet(region=...)`, and `get_stats(region=...)` resolve `<REGION>-Raw` automatically.

- LinkedIn: SG, TW, China (China uses the validated Shanghai LinkedIn preset).
- Jora: SG only.
- JobStreet: SG only.

A non-SG Jora/JobStreet request fails with `SOURCE_REGION_UNSUPPORTED`; it must not silently write to an SG tab.

## Local MCP

Use the interpreter created by repository setup, normally `.venv/bin/python`, not an unrelated system `python`.

For v1.1.0, run the STDIO server with:

```bash
.venv/bin/python server_v1_1.py
```

Full-JD calls may require a host tool timeout around two hours. Codex sample config should set `tool_timeout_sec = 7200` or higher.

## Public-source crawling without Google Sheets

`crawl_jobs` does not require `SHEET_ID` or `GSPREAD_SA_KEY_PATH`. A fresh install can list and enrich jobs from LinkedIn / Jora / JobStreet without any Google configuration.

## Backward compatibility

`server.py` remains the frozen v1.0.0 entrypoint during the v1.1.0 development/qualification line. It still supports the legacy explicit `SHEET_GID` flow. The v1.1.0 host entrypoint is `server_v1_1.py`.
