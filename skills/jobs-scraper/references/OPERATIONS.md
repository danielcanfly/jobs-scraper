# Operations Reference

## Supported sources

- LinkedIn guest jobs endpoints
- Jora Singapore while available
- JobStreet public/API-backed integration used by the scraper

## Time ranges

`1h`, `24h`, `3d`, `7d`, `14d`, `21d`, `30d`

## Google Sheet prerequisites

Sheet operations require:

- `GSPREAD_SA_KEY_PATH`
- `SHEET_ID`
- `SHEET_GID`

The Sheet must be shared with the configured service-account identity at the permission level required for the requested operation.

Do not store credential JSON in Git.

## Local MCP

Use the interpreter created by the repository setup, normally `.venv/bin/python`, not an unrelated system `python`.

Full-JD calls may require a host tool timeout around two hours. Codex sample config should set `tool_timeout_sec = 7200` or higher.

## Public-source crawling without Google Sheets

`crawl_jobs` does not require `SHEET_ID` / `SHEET_GID` / `GSPREAD_SA_KEY_PATH`. A fresh install can list and enrich jobs from LinkedIn / Jora / JobStreet without any Google configuration.
