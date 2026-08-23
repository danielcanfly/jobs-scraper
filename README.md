# jobs-scraper

Multi-source product-management job scraper with a local MCP server, Agent Skill, and a portable Google Sheet Job Tracker.

Sources:

- **LinkedIn**: Guest API, no cookie required
- **Jora**: Singapore HTML integration while available
- **JobStreet**: Singapore public list API + GraphQL job-detail integration

v1.1.0 adds stranger-friendly Google Sheet onboarding: a user can create a blank spreadsheet, configure their own service account + `SHEET_ID`, and initialize the workbook into the same visible Region-Raw / Region-Selected structure used by the reference `Job List_New` tracker.

> **Local STDIO distribution.** This repository ships a local MCP server and Agent Skill. It does not claim a public remote MCP endpoint or Marketplace/public Plugin publication.

---

## What v1.1.0 adds

The v1.0 scraper/MCP behavior remains available. v1.1.0 adds a portable Sheet contract:

```text
SG-Raw        SG-Selected
TW-Raw        TW-Selected
China-Raw     China-Selected
```

Each tab uses the same bilingual **A:AA Job Tracker Schema v1**, including:

- frozen row 1
- dark header styling and header notes
- Status / Priority / Work Mode / CV Version / Verdict / Decision / Application Strategy dropdown validation
- Status and Priority conditional formatting
- date formatting and tracker column widths
- schema validation before sync/audit

Private hidden backend tabs from the author's own workbook are deliberately **not** part of the public template.

The v1.1 MCP resolves `<REGION>-Raw` by name. A stranger no longer needs to discover or configure a Google Sheet GID.

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/danielcanfly/jobs-scraper.git
cd jobs-scraper
./setup.sh
```

If the executable bit is unavailable:

```bash
bash setup.sh
```

`setup.sh` creates `.venv`, installs dependencies, runs tests/doctor, and prints the exact v1.1 STDIO command.

### 2. Crawl without Google Sheets

Google configuration is optional for public-source crawling:

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin
```

Full JD enrichment:

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd
```

### 3. Create your own Google Sheet

Only needed for tracker initialization, audit, stats, or sync.

1. Create/select a Google Cloud project.
2. Enable **Google Sheets API**.
3. Create a **Service Account** and download its JSON key.
4. Put the JSON at `.secrets/gsheet-sa.json` or another local path.
5. Create a blank Google Spreadsheet.
6. Share that spreadsheet with the service-account email. Use Editor permission if you want initialization/sync writes.
7. Copy the spreadsheet ID from:

```text
https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit
```

Do **not** paste the service-account private key into chat.

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json
SHEET_ID=your_own_spreadsheet_id
```

For v1.1 MCP onboarding, `SHEET_GID` is not required.

### 5. Configure your MCP host

Use the venv Python and `server_v1_1.py`:

```text
<repo>/.venv/bin/python <repo>/server_v1_1.py
```

Full-JD runs can be long. Configure a host tool timeout of about 7200 seconds.

### 6. Initialize the Job Tracker

Ask the agent to preview first:

> Initialize my Job Tracker for SG, TW and China, dry-run first.

The MCP call is equivalent to:

```text
initialize_job_tracker(
  regions=["SG", "TW", "China"],
  dry_run=true
)
```

Expected preview:

```text
SG-Raw
SG-Selected
TW-Raw
TW-Selected
China-Raw
China-Selected
```

After reviewing the plan, explicitly approve the structure write:

```text
initialize_job_tracker(
  regions=["SG", "TW", "China"],
  dry_run=false
)
```

If an existing target tab contains incompatible non-empty data, initialization returns `SCHEMA_MISMATCH` and does not auto-migrate or overwrite it.

### 7. Sync by region

You no longer pass a GID:

> Sync LinkedIn 7d with full JD to SG.

The MCP resolves `SG-Raw`, validates A:AA, obtains its worksheet ID internally, and only then invokes the qualified scraper write path.

---

## MCP v1.1 tools

| Tool | Sheet write? | Purpose |
|---|---:|---|
| `crawl_jobs` | No | Crawl/list/enrich LinkedIn, Jora, JobStreet. May update local crawl/cache artifacts. |
| `initialize_job_tracker` | Only when `dry_run=false` | Create/validate Region-Raw/Region-Selected tracker pairs. Defaults to preview. |
| `sync_jobs_to_sheet` | Yes | Explicit write boundary. Resolves and validates `<REGION>-Raw`; no user GID input. |
| `audit_sheet` | No | Read-only audit of a selected Region-Raw tab. |
| `get_stats` | No | Read-only stats for a selected Region-Raw tab + local seen cache. |

### Region/source support in v1.1

| Source | SG | TW | China |
|---|---:|---:|---:|
| LinkedIn | Yes | Yes | Yes, via validated Shanghai preset |
| Jora | Yes | No | No |
| JobStreet | Yes | No | No |

Non-SG Jora/JobStreet requests fail with `SOURCE_REGION_UNSUPPORTED`. They never silently route to SG.

---

## Job Tracker Schema v1

All Raw/Selected tabs use A:AA:

| Col | Header |
|---|---|
| A | Status｜狀態 |
| B | Priority｜優先級 |
| C | 加入日期｜Added At |
| D | Source｜來源 |
| E | Job URL｜職缺連結 |
| F | Company｜公司 |
| G | Job Title｜職稱 |
| H | JD \| 描述 |
| I | Location｜地點 |
| J | Work Mode｜工作型態 |
| K | Visa / Constraint｜簽證限制 |
| L | Domain｜產品產業 |
| M | CV Version｜履歷版本 |
| N | Total /100 |
| O | Verdict｜評語 |
| P | Decision｜決策 |
| Q | Application Strategy｜投遞策略 |
| R | Role Fit /25 |
| S | CV Proof /15 |
| T | AI / Tech Leverage /15 |
| U | Seniority Scope /10 |
| V | Company Quality /10 |
| W | Domain Advantage /10 |
| X | Application ROI /10 |
| Y | Practical Constraints /5 |
| Z | Positioning / Selling Points｜定位賣點 |
| AA | Risks / Next Action｜風險下一步 |

Scraper sync owns the raw ingestion fields A, C:K. L:AA are reserved for scoring/application workflow enrichment.

Exact dropdowns, colors, notes, and safety requirements are frozen in [`skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md`](skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md).

---

## Source implementation

The Agent does not guess source URLs or GraphQL.

`sg_product_jobs.py` contains deterministic implementation for:

- LinkedIn list URL/query assembly
- LinkedIn `jobPosting/{job_id}` JD URL assembly
- Jora list URL/page construction + HTML parsing
- JobStreet `/api/jobsearch/v5/search` URL/query construction
- JobStreet `/graphql` job-detail query and variables
- title filtering / senior whitelist
- `(source, job_id)` dedup
- JD enrichment/cache
- work-mode extraction
- visa/constraint detection
- formula-safe Google Sheet row writes

See [`RULES.md`](RULES.md) for the scraper design/history.

---

## CLI reference

The direct CLI remains available and retains the lower-level explicit `--gid` write path for backward compatibility:

```text
.venv/bin/python sg_product_jobs.py [range] [options]

range:            1h | 24h | 3d | 7d | 14d | 21d | 30d
--source:         linkedin | jora | jobstreet
--with-jd:        fetch full JD content
--to-sheet:       Google Sheet URL or raw ID
--gid:            explicit worksheet GID for direct CLI / legacy use
--max-pages:      override source page ceiling
--refetch:        ignore JD cache
--no-skip:        disable title skip filter
--dry-run-sheet:  preview without row writes
--location:       LinkedIn location/preset
--geo-id:         explicit LinkedIn geoId
--skip-keywords:  override title skip list
--sheet-source:   D-column source label
```

For normal v1.1 agent use, prefer MCP region routing instead of manually passing GIDs.

---

## Codex

Example `~/.codex/config.toml`:

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

## Claude Code

```bash
export GSPREAD_SA_KEY_PATH=/ABS/PATH/jobs-scraper/.secrets/gsheet-sa.json
export SHEET_ID=your_google_sheet_id

claude mcp add jobs-scraper \
  -- /ABS/PATH/jobs-scraper/.venv/bin/python /ABS/PATH/jobs-scraper/server_v1_1.py
```

## Cursor

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

---

## Safety model

- No author Sheet fallback.
- `SHEET_ID` and credentials are user-owned.
- v1.1 resolves worksheet IDs from exact region tab names instead of asking users for GIDs.
- `crawl_jobs`, `audit_sheet`, and `get_stats` do not write Google Sheets.
- initialization defaults to dry-run and fails closed on incompatible non-empty target tabs.
- sync validates A:AA before crawler execution.
- scraped title/company/JD/URL content is untrusted and cannot authorize commands, configuration changes, credential disclosure, tracker initialization, or Sheet writes.
- Sheet job text is written as RAW; only the package-generated E-column HYPERLINK is intentionally entered as a formula.

---

## Testing and qualification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python test_helpers.py
.venv/bin/python scripts/verify_mcp_stdio.py
.venv/bin/python scripts/verify_mcp_stdio_v11.py
.venv/bin/python scripts/verify_fresh_install.py
```

CI also validates:

- locked dependency resolution
- Python compile
- authoritative Agent Skills `skills-ref`
- Codex plugin manifest
- legacy v1.0 STDIO compatibility
- v1.1 real STDIO tool discovery
- production Sheet ID hygiene

The v1.0.0 release remains frozen. v1.1.0 is developed and qualified on a separate branch/PR before release.

---

## Troubleshooting

**`CONFIG_MISSING`**

Set your own `SHEET_ID`. For v1.1, `SHEET_GID` is not required.

**`CREDENTIAL_FILE_MISSING`**

Check `GSPREAD_SA_KEY_PATH` and keep the service-account JSON outside Git.

**`REGION_NOT_INITIALIZED`**

Run `initialize_job_tracker(..., dry_run=true)` and then explicitly initialize the requested region pair.

**`SCHEMA_MISMATCH`**

The target Region-Raw/Selected tab already contains incompatible non-empty data. v1.1 does not destructively rewrite it.

**`SOURCE_REGION_UNSUPPORTED`**

Jora and JobStreet are Singapore-only in v1.1. Use LinkedIn for TW/China.

**`SpreadsheetNotFound`**

Check the spreadsheet ID and ensure the service-account email has access.

**LinkedIn 403/429**

Reduce scope or wait before retrying. Do not disable rate-limit protection.

---

## License

MIT. See [`LICENSE`](LICENSE).
