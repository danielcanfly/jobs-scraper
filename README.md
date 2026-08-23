# jobs-scraper 🇸🇬

Multi-source job scraper for Singapore tech PM (Product Manager) jobs, syncing to Google Sheets.

Supports 3 sources:
- **LinkedIn** (Guest API, no cookie needed)
- **Jora** (HTML parse, ⚠️ SG site closing 9/9/2026)
- **JobStreet** (Public API + GraphQL)

Designed for personal job-search tracking. Cross-source dedup, visa signal detection, work-mode parsing, all automated.

> **Local STDIO distribution.** This repository ships the scraper CLI, the
> local MCP server, the Agent Skill (`skills/jobs-scraper/SKILL.md`) and the
> Codex plugin packaging manifest (`.codex-plugin/plugin.json`). It does
> **not** ship a public remote Plugin; a stable public HTTPS Streamable HTTP
> endpoint and Marketplace submission are a separate future lane and are not
> represented by anything in this repo.

---

## 🚀 Quick Start (15-20 min first time)

### Step 1: Clone & install

```bash
git clone https://github.com/danielcanfly/jobs-scraper.git
cd jobs-scraper
./setup.sh
```

`setup.sh` creates `.venv/`, installs from `pyproject.toml` (incl. `[dev]`
extras for pytest), runs the test suite, and runs `scripts/doctor.py`. It
prints the exact interpreter path to use for the MCP host at the end.

If `./setup.sh` is not executable on your system, run `bash setup.sh`.

> Re-running `./setup.sh` is safe: it does not overwrite your existing
> `.env` or `.secrets/`.

### Step 2: Get Google Cloud credentials (one-time, ~10 min)

> **Optional for public-source crawling.** All three sources work without any
> Google configuration. You only need a service account if you want to use
> the Google Sheet read/write tools.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create or select a project
2. **APIs & Services** → **Library** → search "Google Sheets API" → **Enable**
3. **IAM & Admin** → **Service Accounts** → **Create Service Account**
   - Name: anything (e.g. `jobs-scraper`)
   - Skip optional steps, click **Done**
4. Click the new service account → **Keys** tab → **Add Key** → **Create new key** → **JSON**
   - A `.json` file downloads (this is your auth credential)
5. Move the JSON file to `jobs-scraper/.secrets/gsheet-sa.json`
   ```bash
   mkdir -p .secrets
   mv ~/Downloads/your-project-*.json .secrets/gsheet-sa.json
   ```

### Step 3: Create a Google Sheet

> Only required for `audit_sheet` / `get_stats` / `sync_jobs_to_sheet`. The
> scraper will fail-closed with a structured `CONFIG_MISSING` error if these
> tools are called without `SHEET_ID` / `SHEET_GID` configured. There is
> **no fallback to the package author's Sheet**.

1. Go to [sheets.new](https://sheets.new) → creates a blank Sheet
2. **Share** the Sheet with the service account email (looks like `jobs-scraper@your-project.iam.gserviceaccount.com`)
   - ⚠️ **Editor** access required for `sync_jobs_to_sheet` (the read tools
     use a read-only OAuth scope and only need **Viewer**)
3. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/[THIS_PART_IS_SHEET_ID]/edit
   ```
4. Copy the GID from the URL (after `?gid=`):
   ```
   https://docs.google.com/spreadsheets/d/.../edit?gid=[THIS_PART]
   ```

### Step 4: Configure

```bash
cp .env.example .env
# Edit .env (fill in your own values; empty values fail-closed on Sheet tools):
#   GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json
#   SHEET_ID=<paste your sheet ID>
#   SHEET_GID=<paste your GID, usually 0 for first tab>
```

### Step 5: Run your first scrape

```bash
# Use the venv interpreter (the one setup.sh printed at the end)
.venv/bin/python sg_product_jobs.py 7d --source linkedin

# Full pipeline (list + JD + sheet write, ~50-100 min for 7d)
.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd --to-sheet "$SHEET_URL"
```

> ⏱️ **Full-JD runs are slow.** A 7-day LinkedIn run with JD enrichment takes
> roughly 50–100 minutes. The scraper subprocess has a 7200-second (2 hour)
> ceiling. If you wire the scraper into a Codex or Claude MCP host, also
> raise the host's `tool_timeout_sec` to 7200 or higher (see [MCP section](#-use-with-codex--claude-code)).

That's it. You should see jobs in your Google Sheet.

---

## 📖 CLI Reference

```
.venv/bin/python sg_product_jobs.py [range] [options]

range:        1h | 24h | 3d | 7d | 14d | 21d | 30d  (default: 24h)
--source:     linkedin | jora | jobstreet          (default: linkedin)
--with-jd:    fetch full JD content for each job   (default: list only)
--to-sheet:    Google Sheet URL or ID, with gid     (required for sheet write)
--max-pages:   override max pages per source         (default: per-source defaults)
--refetch:     ignore cache, re-fetch all JDs
--no-skip:     don't filter titles by skip list
--dry-run-sheet:  print what would be written, don't actually write
--location:    override default "Singapore"          (uses KNOWN_GEO_IDS preset)
--geo-id:      override LinkedIn geoId              (e.g. 104187078 for Taiwan)
--skip-keywords: override the 24-word skip list
--sheet-source:  override D-column label            (default "LinkedIn / Minimax")
```

### Common recipes

```bash
# Daily check on LinkedIn + Jora + JobStreet (no JD, fast)
for src in linkedin jora jobstreet; do
  .venv/bin/python sg_product_jobs.py 24h --source $src
done

# Deep LinkedIn 14d refresh with JD + sheet
.venv/bin/python sg_product_jobs.py 14d --source linkedin --with-jd --to-sheet "$URL"

# JobStreet full 30d sweep (all 5 keywords × 25 pages)
.venv/bin/python sg_product_jobs.py 30d --source jobstreet --with-jd --to-sheet "$URL"

# Taiwan instead of Singapore
.venv/bin/python sg_product_jobs.py 7d --location Taiwan

# Force re-fetch all JDs (after schema change in your Sheet, etc.)
.venv/bin/python sg_product_jobs.py 7d --source linkedin --refetch --to-sheet "$URL"
```

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GSPREAD_SA_KEY_PATH` | `.secrets/gsheet-sa.json` | Path to your service account JSON. Must be a real file path; missing files yield `CREDENTIAL_FILE_MISSING`. |
| `SHEET_ID` | **(empty, fail-closed)** | Your Google Sheet ID. **Must override** to use your own sheet. Empty = Sheet tools return `CONFIG_MISSING`; no fallback to author. |
| `SHEET_GID` | **(empty, fail-closed)** | The sheet tab GID. Empty = `CONFIG_MISSING`. |
| `JOBSTREET_KEYWORDS` | `product manager,product director,director of product,head of product,product lead` | Comma-separated JobStreet search keywords |
| `LINKEDIN_GEO_ID` | `102454443` | LinkedIn geoId (Singapore). 104187078=Taiwan, 107388191=Shanghai |

> The scraper does **not** read or fall back to a hard-coded Sheet ID.
> Every Google Sheet tool checks env at call time and returns
> `CONFIG_MISSING` (or `CREDENTIAL_FILE_MISSING`) when the user has not
> supplied their own.

---

## 🏗️ Architecture (1-minute overview)

```
sg_product_jobs.py (~1600 lines, single file)
│
├── 🟢 LinkedIn  → /jobs-guest/jobs/api/...  (Guest API, no cookie)
├── 🟡 Jora      → HTML parse (sg.jora.com)
└── 🟢 JobStreet → /api/jobsearch/v5/search + /graphql

Shared across all sources:
  - 24-word skip filter (assistant/intern/junior/etc. → skip)
  - Senior whitelist (Senior PM / VP Product / etc. → keep)
  - 3-tier visa detection (HARD / SOFT / POSITIVE)
  - Work mode parser (Onsite / Hybrid / Remote)
  - (source, job_id) tuple dedup across sources + runs
  - 11-column Google Sheet write, two-phase (E=HYPERLINK USER_ENTERED, rest=RAW)
```

See **[RULES.md](RULES.md)** for the full design rules, 14 known gotchas, and historical context.

---

## 🩺 Doctor

`./setup.sh` runs `scripts/doctor.py` automatically. Run it any time:

```bash
.venv/bin/python scripts/doctor.py
```

It checks Python version, venv interpreter, imports, presence of required
files, fail-closed Sheet config, and that no `.env` / `.secrets` are tracked
by Git. Never prints credential content or private key material.

---

## 🧪 Testing

```bash
.venv/bin/python -m pytest -q
```

Should print `47 passed` (27 original helper tests + 20 contract tests for
the MCP v2 server, fail-closed config, two-phase sheet write, and the setup
contract). Tests are deterministic, do not require Google credentials, and
do not touch a production Sheet.

### Fresh-install qualification

```bash
.venv/bin/python scripts/verify_fresh_install.py
```

Copies the repository into a temp directory, builds a fresh venv, installs
from `pyproject.toml`, compiles all source, runs pytest, imports the MCP
server, lists the 4 tools, and validates the Skill frontmatter — without
any Google credentials. Used by the CI workflow.

---

## 🤖 Use with Codex / Claude Code / Cursor

This repo ships an MCP server (`server.py`, MCP **v2 line**) that exposes
4 tools. Read tools never write to your Sheet. The single write tool
(`sync_jobs_to_sheet`) is the explicit write boundary.

| Tool | Reads Sheet | Writes Sheet | Notes |
|---|---|---|---|
| `crawl_jobs`        | no  | no  | Public-source crawl; max 1h/24h/3d/7d/14d/21d/30d |
| `sync_jobs_to_sheet` | no  | yes | Explicit write. Requires `SHEET_ID` / `SHEET_GID` / `GSPREAD_SA_KEY_PATH`. Supports `dry_run`. |
| `audit_sheet`       | yes (read-only scope) | no  | Dedup, URL dups, cross-source collisions, visa/work-mode distributions |
| `get_stats`         | yes (read-only scope) | no  | Row counts and per-source distributions |

### Setup MCP server

`./setup.sh` installs the SDK. Then point your agent at the venv
interpreter the script printed (it is **not** a system `python`).

#### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.jobs-scraper]
command = "/ABS/PATH/jobs-scraper/.venv/bin/python"
args = ["/ABS/PATH/jobs-scraper/server.py"]
cwd = "/ABS/PATH/jobs-scraper"
tool_timeout_sec = 7200   # full-JD runs are 50-100 min; default 60s is too short
required = true

[mcp_servers.jobs-scraper.env]
GSPREAD_SA_KEY_PATH = "/ABS/PATH/jobs-scraper/.secrets/gsheet-sa.json"
SHEET_ID = "YOUR_SHEET_ID"
SHEET_GID = "YOUR_TAB_GID"
```

> Codex's default `tool_timeout_sec` is **60 seconds**, which is too short
> for a full-JD run. Raise it to 7200. The scraper subprocess inside the
> server also has a 7200s ceiling.

#### Claude Code

```bash
claude mcp add jobs-scraper \
  -- /ABS/PATH/jobs-scraper/.venv/bin/python /ABS/PATH/jobs-scraper/server.py
```

Then in your shell, set the env vars before launching Claude Code:

```bash
export GSPREAD_SA_KEY_PATH=/Users/you/jobs-scraper/.secrets/gsheet-sa.json
export SHEET_ID=your_google_sheet_id
export SHEET_GID=0
```

#### Cursor (`~/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "jobs-scraper": {
      "type": "stdio",
      "command": "/ABS/PATH/jobs-scraper/.venv/bin/python",
      "args": ["/ABS/PATH/jobs-scraper/server.py"],
      "timeout": 7200
    }
  }
}
```

> **Secrets in config**: prefer forwarding by env var name (Codex `env`,
> Claude Code shell export) rather than embedding credential values.

After setup, you can ask your agent:

> "用 crawl_jobs 跑 LinkedIn 7d 帶 JD"
> "用 audit_sheet 看一下"
> "用 get_stats 顯示現在狀態"
> "用 sync_jobs_to_sheet 跑 24h dry-run (先不寫)"

---

## 🔧 Troubleshooting

**"gspread.exceptions.SpreadsheetNotFound"**
→ Wrong `SHEET_ID`, or service account email not shared with the Sheet.

**`CONFIG_MISSING` from any Sheet tool**
→ `SHEET_ID` or `SHEET_GID` is empty in your environment. Edit `.env`.

**`CREDENTIAL_FILE_MISSING` from any Sheet tool**
→ The `GSPREAD_SA_KEY_PATH` file does not exist. Place your service
account JSON there.

**"403 rate limit"** (LinkedIn only)
→ Wait 30-60 min, or reduce `--max-pages`. The script uses random 3-10s sleep + curl_cffi to mimic browser, but heavy testing can still trigger.

**"Cloudflare"** (JobStreet HTML page, not API)
→ JobStreet HTML pages are blocked. The script uses the public API + GraphQL which is not blocked. If you need HTML page data, you're out of luck.

**Empty results for `daterange=1` (1 day)**
→ Normal. LinkedIn 1h and JobStreet 1d often have 0 jobs because most are posted in 1-3 days.

---

## 📜 License

MIT — do whatever you want, no warranty. See [LICENSE](LICENSE).

## 🙏 Credits

Built by [@danielcanfly](https://github.com/danielcanfly) for personal job-search tracking. The 3 source integrations and dedup logic are designed to be transparent and auditable — read the code, it's a single 1600-line file.
