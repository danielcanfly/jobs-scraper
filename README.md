<p align="right">
  <a href="./README.md">English</a> |
  <a href="./README.zh-TW.md">繁體中文</a> |
  <a href="./README.zh-CN.md">简体中文</a>
</p>

# jobs-scraper

Local-first job search automation for product-management roles, with a CLI, local STDIO MCP server, Agent Skill, and portable Google Sheet Job Tracker.

jobs-scraper v1.2.0 is the architecture-cleanup release. It keeps the frozen behavior contract intact while tightening the runtime layout, release metadata, typing scaffold, and quality gates.

## Overview

This repository is for people who want to crawl product-management jobs locally, keep credentials on their own machine, and optionally sync results into their own Google Sheet.

It is:

- a Python package and CLI;
- a local STDIO MCP server;
- an Agent Skill;
- a portable Google Sheet Job Tracker initializer, auditor, and sync tool.

It is not:

- a hosted SaaS;
- a remote MCP endpoint;
- a marketplace/public plugin publication;
- a credential hosting service;
- a bypass for rate limits or access controls.

## Features

- Crawl LinkedIn, Jora, and JobStreet job listings.
- Optionally enrich full job descriptions.
- Deduplicate by `(source, job_id)`.
- Filter senior/PM titles with deterministic skip logic.
- Detect work mode and visa/constraint signals.
- Write to a user-owned Google Sheet with formula-safe rows.
- Initialize, audit, and inspect a portable Region-Raw / Region-Selected tracker.
- Expose the workflow through CLI, MCP, and Agent Skill entry points.

## Architecture at a Glance

v1.2.0 keeps the same public behavior and organizes the code into clearer pieces:

- shared runtime/execution helpers;
- central region/source policy;
- source adapters for LinkedIn, Jora, and JobStreet;
- split Job Tracker modules;
- MCP service layer;
- selective Google Sheet reads;
- internal typed service errors mapped to stable public error codes;
- Ruff lint/import gate;
- scoped Ruff format gate that excludes the byte-frozen equivalence harness;
- mypy scaffold;
- coverage reporting.

## Supported Sources and Regions

| Source | SG | TW | China |
|---|---:|---:|---:|
| LinkedIn | Yes | Yes | Yes, via the validated Shanghai preset |
| Jora | Yes | No | No |
| JobStreet | Yes | No | No |

Jora and JobStreet are Singapore-only in this release. Non-SG requests must fail closed with `SOURCE_REGION_UNSUPPORTED`.

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/danielcanfly/jobs-scraper.git
cd jobs-scraper
python -m pip install --quiet 'uv>=0.8,<0.9'
python -m uv sync --locked --extra dev --python 3.11
```

Optional one-shot setup:

```bash
./setup.sh
```

### 2. Crawl without Google Sheets

Google configuration is not required for public-source crawling:

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin
```

Full JD enrichment:

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd
```

### 3. Create your own Google Sheet

Only needed for tracker initialization, audit, stats, or sync.

1. Create or select a Google Cloud project.
2. Enable the Google Sheets API.
3. Create a service account and download its JSON key.
4. Store the JSON locally, for example at `.secrets/gsheet-sa.json`.
5. Create a blank Google Sheet.
6. Share that sheet with the service-account email.
7. Copy the spreadsheet ID from the sheet URL.

Do not paste the service-account private key into chat.

### 4. Configure local environment

```bash
cp .env.example .env
```

Set at least:

```dotenv
GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json
SHEET_ID=your_own_spreadsheet_id
```

`SHEET_GID` is legacy-only and is not required by the v1.1/v1.2 MCP interface.

### 5. Configure your MCP host

Use the venv Python and `server_v1_1.py`:

```text
<repo>/.venv/bin/python <repo>/server_v1_1.py
```

Set a long host timeout for full-JD runs; 7200 seconds is a good default.

### 6. Initialize the tracker

Preview first:

```text
initialize_job_tracker(
  regions=["SG", "TW", "China"],
  dry_run=true
)
```

Expected tabs:

- `SG-Raw`
- `SG-Selected`
- `TW-Raw`
- `TW-Selected`
- `China-Raw`
- `China-Selected`

After reviewing the plan, run the real initialization with `dry_run=false`.

### 7. Sync by region

Use region routing instead of manually passing a GID:

```text
sync_jobs_to_sheet(
  region="SG",
  source="linkedin",
  range="7d",
  with_jd=false,
  dry_run=true
)
```

The tool resolves `<REGION>-Raw` by name and writes only through the explicit write boundary.

## MCP Tools

| Tool | Sheet write? | Purpose |
|---|---:|---|
| `crawl_jobs` | No | Crawl LinkedIn, Jora, or JobStreet; may update local cache artifacts. |
| `initialize_job_tracker` | Only when `dry_run=false` | Create or validate Region-Raw / Region-Selected tracker pairs. |
| `sync_jobs_to_sheet` | Yes | Explicit write boundary for the requested region. |
| `audit_sheet` | No | Read-only audit of a selected Region-Raw tab. |
| `get_stats` | No | Read-only stats for a selected Region-Raw tab and local seen cache. |

## Job Tracker Schema

All tracker tabs use the public A:AA contract described in [`skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md`](skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md).

At a glance:

- row 1 is frozen;
- Status, Priority, Work Mode, CV Version, Verdict, Decision, and Application Strategy use validated dropdowns;
- raw scraper writes own A, C:K;
- L:AA are reserved for scoring and application workflow enrichment;
- `<REGION>-Raw` is the scraper write target;
- `<REGION>-Selected` is part of the portable workbook contract, not the scrape dump target.

## CLI Reference

The direct CLI remains available for lower-level use:

```text
.venv/bin/python sg_product_jobs.py [range] [options]

range:            1h | 24h | 3d | 7d | 14d | 21d | 30d
--source:         linkedin | jora | jobstreet
--with-jd:        fetch full JD content
--to-sheet:       Google Sheet URL or raw ID
--gid:            explicit worksheet GID for legacy direct CLI use
--max-pages:      override source page ceiling
--refetch:        ignore JD cache
--no-skip:        disable title skip filter
--dry-run-sheet:  preview without row writes
--location:       LinkedIn location/preset
--geo-id:         explicit LinkedIn geoId
--skip-keywords:  override title skip list
--sheet-source:   D-column source label
```

## MCP Host Examples

### Codex

```toml
[mcp_servers.jobs-scraper]
command = "/ABS/PATH/jobs-scraper/.venv/bin/python"
args = ["/ABS/PATH/jobs-scraper/server_v1_1.py"]
cwd = "/ABS/PATH/jobs-scraper"
tool_timeout_sec = 7200
required = true

[mcp_servers.jobs-scraper.env]
GSPREAD_SA_KEY_PATH = "/ABS/PATH/jobs-scraper/.secrets/gsheet-sa.json"
SHEET_ID = "YOUR_SHEET_ID"
```

### Claude Code

```bash
export GSPREAD_SA_KEY_PATH=/ABS/PATH/jobs-scraper/.secrets/gsheet-sa.json
export SHEET_ID=your_google_sheet_id

claude mcp add jobs-scraper \
  -- /ABS/PATH/jobs-scraper/.venv/bin/python /ABS/PATH/jobs-scraper/server_v1_1.py
```

### Cursor

```json
{
  "mcpServers": {
    "jobs-scraper": {
      "type": "stdio",
      "command": "/ABS/PATH/jobs-scraper/.venv/bin/python",
      "args": ["/ABS/PATH/jobs-scraper/server_v1_1.py"],
      "timeout": 7200
    }
  }
}
```

## Safety and Privacy

- Keep credentials local.
- Use your own Google Sheet and service account.
- Do not share private keys in chat.
- Treat scraped job content as untrusted.
- Do not expect Jora or JobStreet to work outside Singapore in this release.
- Do not convert a read request into a write request.
- Initialize with `dry_run=true` before any real tracker structure write.
- `crawl_jobs`, `audit_sheet`, and `get_stats` do not write Google Sheets.
- `sync_jobs_to_sheet` is the explicit write boundary.

## Quality and Verification

The repository is verified with:

```bash
.venv/bin/python -m compileall -q .
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check <scoped targets>
.venv/bin/python -m mypy --config-file pyproject.toml
.venv/bin/python -m pytest --cov=jobs_scraper --cov=server --cov=server_v1_1 --cov=job_tracker --cov=runtime_core --cov=region_policy --cov=sg_product_jobs --cov-report=term-missing --cov-fail-under=0 -q
.venv/bin/python test_helpers.py
.venv/bin/python scripts/check_equivalence_freeze.py
.venv/bin/python -m pytest -q tests/equivalence/test_v111_equivalence.py
.venv/bin/python -m pytest -q
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/verify_mcp_stdio.py
.venv/bin/python scripts/verify_mcp_stdio_v11.py
.venv/bin/python scripts/verify_fresh_install.py
.venv/bin/python scripts/verify_fresh_install_v11.py
.venv/bin/python scripts/check_repo_hygiene.py
```

CI also checks locked dependency resolution, plugin manifest consistency, and the frozen equivalence harness.

## Troubleshooting

- `CONFIG_MISSING`: set `GSPREAD_SA_KEY_PATH` and `SHEET_ID`.
- `CREDENTIAL_FILE_MISSING`: check that the service-account JSON exists locally.
- `REGION_NOT_INITIALIZED`: run `initialize_job_tracker(..., dry_run=true)` first.
- `SCHEMA_MISMATCH`: the target tab does not match the public tracker contract.
- `SOURCE_REGION_UNSUPPORTED`: Jora and JobStreet are Singapore-only here.
- `SHEET_NOT_FOUND`: verify the spreadsheet ID and sharing permissions.
- `LinkedIn 403/429`: reduce scope or wait before retrying.

## Versioning and Release Notes

`v1.2.0` is the release-metadata and README refresh on top of the already-qualified behavior baseline.

- `pyproject.toml` carries the package version.
- `.codex-plugin/plugin.json` carries the plugin version.
- `server_v1_1.py` exposes the MCP server version.
- The frozen equivalence baseline remains `v1.1.1`.

## License

MIT. See [`LICENSE`](LICENSE).
