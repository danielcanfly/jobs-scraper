<p align="right">
  <a href="./README.md">English</a> |
  <a href="./README.zh-TW.md">繁體中文</a> |
  <a href="./README.zh-CN.md">简体中文</a>
</p>

# jobs-scraper

A local-first multi-source job scraper and tracking toolkit for product-management roles, with a CLI, local STDIO MCP server, Agent Skill, and portable Google Sheet Job Tracker.

jobs-scraper v1.6.6 crawls product-management roles across five sources — `linkedin`, `jobstreet`, `cake`, `104` / `onezerofour` — with JD enrichment and tracking. It keeps the workflow local-first, preserves explicit safety gates, and can optionally sync results into a user-owned Google Sheet.

## Overview

This repository is for people who want to crawl and track product-management roles locally across several job boards, keep credentials on their own machine, and optionally sync results into their own Google Sheet.

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

- Crawl five sources — LinkedIn Guest API, JobStreet GraphQL, 104 job API, and Cake job API.
- Optionally enrich full job descriptions.
- Apply the frozen title skip filter v8.5 during JD enrichment; [`SKIP.md`](SKIP.md) is the semantics authority.
- Deduplicate by `(source, job_id)`.
- Detect work mode and visa/constraint signals.
- Write to a user-owned Google Sheet with formula-safe rows.
- Keep one shared `seen_jds.jsonl` as the crawl/dedup source of truth.
- Initialize, audit, and inspect a portable Region-Raw / Region-Selected tracker.
- Expose the workflow through CLI, MCP, and Agent Skill entry points.

## Architecture at a Glance

v1.2.0 keeps the same public behavior and organizes the code into clearer pieces:

- shared runtime/execution helpers;
- central region/source policy;
- a LinkedIn Guest API source adapter;
- split Job Tracker modules;
- MCP service layer;
- selective Google Sheet reads;
- internal typed service errors mapped to stable public error codes;
- Ruff lint/import gate;
- scoped Ruff format gate that excludes the byte-frozen equivalence harness;
- mypy scaffold;
- coverage reporting.

## LinkedIn Location Targeting

The scraper uses LinkedIn's Guest API and supports location targeting through LinkedIn `geoId` values.

For backward compatibility, historical tracker/cache rows created by older Jora or JobStreet integrations remain readable for audit and deduplication. Those integrations are no longer used for new network requests.

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

LinkedIn location targeting can be set with `geoId`:

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --geo-id 104187078
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

### China: three cities, one Sheet tab

China is not a single place. `region="China"` crawls **Shanghai**; `region="Hangzhou"` and
`region="Shenzhen"` are regions of their own. All three write into the same `China-Raw` tab:

| Region | City | LinkedIn geoId | Aliases | Writes to |
|---|---|---|---|---|
| `China` | Shanghai | `107388191` | `cn`, `china`, `中國`, `shanghai` | `China-Raw` |
| `Hangzhou` | Hangzhou | `101821877` | `hz`, `杭州` | `China-Raw` |
| `Shenzhen` | Shenzhen | `106750182` | `sz`, `深圳` | `China-Raw` |

The city regions are opt-in: the default region set stays `SG` / `TW` / `China`, and
`initialize_job_tracker` never creates `China-Raw` twice when several of them are listed.

The same cities are available on the CLI, where `--location` resolves the geoId from the same
preset table:

```text
sg_product_jobs.py 7d --source linkedin --location Hangzhou --to-sheet "<China-Raw URL>"
```

A China posting carries **no visa judgement**: a Taiwan resident can take a permit into mainland
China, so China-specific citizenship wording (`Chinese citizens only`, `僅限中國公民`,
`必須為中國公民`, `上海戶口優先`, `中國人優先`) produces no signal. A Singapore or Taiwan posting
that requires any citizenship is still a hard blocker.

## MCP Tools

| Tool | Sheet write? | Purpose |
|---|---:|---|
| `crawl_jobs` | No | Crawl LinkedIn; may update local cache artifacts. |
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
--source:         linkedin | jobstreet | cake | 104 | onezerofour
--with-jd:        fetch full JD content
--to-sheet:       Google Sheet URL or raw ID
--gid:            explicit worksheet GID for legacy direct CLI use
--max-pages:      override source page ceiling
--refetch:        ignore JD cache
--no-skip:        disable every title filter (including the v8.5 groups)
--dry-run-sheet:  preview without row writes
--location:       LinkedIn location/preset
--geo-id:         explicit LinkedIn geoId
--skip-keywords:  extra title keyword match, on top of the v8.5 groups
--sheet-source:   D-column source label
```

Full-JD enrichment applies the frozen title skip filter v8.5 by default; [`SKIP.md`](SKIP.md) is the semantics authority. Use `--no-skip` to fetch every JD, and `--skip-keywords` to add extra keyword matches on top of the v8.5 groups:

```bash
python sg_product_jobs.py 14d --source linkedin --with-jd --skip-keywords intern junior assistant
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
- Jora is retired as an active network source (the site closed in 2026); its historical tracker rows remain audit-readable and dedup round-trip. JobStreet is an active source again as of v1.4.0.
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
- `SOURCE_REGION_UNSUPPORTED`: the requested source/region combination is unsupported. v1.4.0 routes LinkedIn/JobStreet to `SG-Raw` and 104/Cake to `TW-Raw`; the retired `jora` source is rejected.
- `SHEET_NOT_FOUND`: verify the spreadsheet ID and sharing permissions.
- `LinkedIn 403/429`: reduce scope or wait before retrying.

## Versioning and Release Notes

`v1.6.7` is the current release. Two budgets that were guesses, and a 400 that was retried for three minutes. v1.6.6 pinned the LinkedIn page budgets to Shanghai's pool depths, but Singapore's pools are deeper for every long range — 7d holds about 600 postings against Shanghai's 400 — so those budgets still truncated a Singapore run; the budgets are now pinned to the deepest measured pool per range across both cities (`1h` 8 pages, `24h` 15, `3d` 35, `7d` 80, and 100 for `14d`/`21d`/`30d`, where 100 is the Guest API's own pagination ceiling). JobStreet's budgets were never measured at all — the table carried a comment predicting ~600 unique postings for 7d while the actual result was ~250, because the five keywords share one `seen` set and the 50% soft-stop abandons four of them on their first page — and the API's own totals are far larger than the budgets were (7d's largest keyword matches 955 postings, 14d's 1670, 30d's 3251, against 15/30/25 pages); they are now sized for the largest keyword's pool plus headroom. A non-429 4xx on a LinkedIn list page no longer burns the retry ladder: the adapter's docstring and the frozen contract both said such a response is a caller bug and is raised without retrying, but `raise_for_status()` raised inside the `try` and the broad `except Exception` caught it, so the page was retried four times (30+60+90s) before the crawl gave up — it now raises `FatalListPageError` immediately, exactly like the JobStreet adapter. And the API's pagination ceiling is an end rather than a failure: `start=1000` answers HTTP 400 instead of an empty page, which used to abort the whole chunk and made the supervisor read the FAIL as a coverage gap; a crawl that reaches it now ends with what it collected.

- `v1.6.6` fixed two failures that shared one shape: the run looked successful while it had quietly done less than it was asked to. A range's page budget has to cover the pool that range actually has. The LinkedIn range table gave `30d` a 25-page budget — 250 postings — while Shanghai's 30-day pool holds about 700, so the crawl stopped at the budget, the run reported success, and the postings past the budget were never seen. The budgets are now pinned to the pool depths measured against the live Guest API on 2026-11-22 (`1h` under 50, `24h` about 100, `3d` about 250, `7d` about 400, `14d` about 290, `21d` about 300, `30d` about 700 postings). A budget is a ceiling, not a target: the crawl ends itself after two consecutive pages with no new posting, so a city with a small pool still stops early and a wider budget costs it nothing. The pre-detail dedup now reads the tab the run is about to write to — the target gid is resolved the way the writer resolves it (explicit `--gid`, then the `#gid=` inside `--to-sheet`, then the source-label mapping) instead of always reading `SG-Raw` for a `LinkedIn / Minimax` run, which made a China run fetch the JDs of postings the Sheet was going to discard anyway. The release pipeline is green again: v1.6.5 bumped the package version but not `uv.lock`, so CI failed at its very first gate and stayed red on GitHub.

- `v1.6.5` fixed two LinkedIn Guest API failures that could end a run quietly. A legitimately empty list page is 26 bytes and yields no parseable root; the list parser used to raise on it, which ended the page loop, the chunk and the whole run — on 2026-11-21 all three chunks of one city crawl died that way and wrote zero rows while still exiting 0. It now parses to zero jobs, so the crawl moves on to the next page, and the empty page is still never retried, because it is a real answer rather than a failure. The JD fetch gained the same 30/60/90s ladder the list fetch has: a 429, a 5xx or a connection error is retried instead of giving up, because a job whose JD never arrives is skipped by the Sheet writer and would otherwise vanish from the run without failing it. Neither fix is China-specific — both are properties of the Guest API and hit every region the same way. China is three crawlable places instead of one, and a China posting no longer carries a visa judgement. `China` is Shanghai, while `Hangzhou` and `Shenzhen` are regions of their own with verified LinkedIn geoIds (`101821877`, `106750182`); all three write into the same `China-Raw` tab, and the city regions stay opt-in so the default region set is still `SG` / `TW` / `China`. The China-specific citizenship patterns (`Chinese citizens only`, `僅限中國公民`, `必須為中國公民`, `上海戶口優先`, `中國人優先`) were removed from the visa signal — a Taiwan resident can take a permit into mainland China — while the generic Singapore/Taiwan coverage is unchanged. The crawl path can also be told which way out to take: the LinkedIn Guest API answers a direct request with HTTP 451 from some networks, and the Google Sheets API times out on a direct connection there, while both work through a proxy. `JOBS_SCRAPER_PROXY` (or the standard `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`) selects one, `doctor` reports which proxy is in effect and whether it is still reachable, and nothing set means a direct connection as before. Earlier releases:

- `v1.6.4` made China three crawlable places and dropped the China-specific visa judgement.

- `v1.6.2` kept the jobs payload out of the generated Sheet-write worker: it used to be serialised into the worker's *Python* source as a string literal, so a 30-page run produced a multi-megabyte source file that CPython had to pull through its tokenizer before the write could start — a memory spike landing exactly on the Sheet write. The payload now lives in its own JSON file and the generated worker stays a few kilobytes.

- `v1.6.1` fixed the Sheet-write subprocess: the generated worker embedded its arguments with a JSON encoder, so the default `gid=None` became the bare token `null` inside generated *Python* source and the worker died with `NameError: name 'null' is not defined` before it ever reached Google. Because the write only falls back to the in-process path when the subprocess fails, every run silently lost the subprocess timeout guard and wrote the Sheet unguarded. Arguments are now embedded as Python literals.

Earlier releases:

- `v1.6.0` gave the JobStreet list page the same retry ladder LinkedIn has had since v1.3.1: a transient 429, 5xx, connection error or JSON decode error sleeps 30/60/90s and retries instead of ending the keyword crawl. Before that, one flaky page could end a run with zero jobs — the process printed "no data, ending" and still exited 0, so the caller saw a successful run that had collected nothing.

Earlier releases:

- `v1.6.2` kept the jobs payload out of the generated Sheet-write worker source.
- `v1.6.1` embedded the generated worker's arguments as Python literals instead of JSON.
- `v1.6.0` gave the JobStreet list page the same 30/60/90s retry ladder LinkedIn had.
- `v1.5.0` split every source's fetching layer into `jobs_scraper/sources/`: five active sources, the frozen title skip filter v8.5, the LinkedIn list-page 429 retry, and the corrected three-phase Sheet write order.
- `v1.3.1` added the LinkedIn list-page 429 retry at the source layer.
- `v1.3.0` retired Jora and JobStreet and narrowed the active source contract to LinkedIn while preserving historical tracker-row parsing.

- `pyproject.toml` carries the package version.
- `.codex-plugin/plugin.json` carries the plugin version.
- `server_v1_1.py` exposes the MCP server version.
- The active frozen equivalence baseline is `v1.6.7` and explicitly protects the five-source contract, the one-adapter-per-source split, the JobStreet list-page retry ladder, the LinkedIn empty-page and JD retry rules, the crawl-budget rule that a range's page ceiling must cover its measured pool in every known city, the pagination-ceiling rule that the Guest API's 1000-result window is an end rather than a failure, the Sheet-target rule that the pre-detail dedup reads the tab the run writes to, and the generated-worker rules.

## License

MIT. See [`LICENSE`](LICENSE).
