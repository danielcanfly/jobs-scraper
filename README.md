# jobs-scraper 🇸🇬

Multi-source job scraper for Singapore tech PM (Product Manager) jobs, syncing to Google Sheets.

Supports 3 sources:
- **LinkedIn** (Guest API, no cookie needed)
- **Jora** (HTML parse, ⚠️ SG site closing 9/9/2026)
- **JobStreet** (Public API + GraphQL)

Designed for personal job-search tracking. Cross-source dedup, visa signal detection, work-mode parsing, all automated.

---

## 🚀 Quick Start (15-20 min first time)

### Step 1: Clone & install
```bash
git clone https://github.com/danielcanfly/jobs-scraper.git
cd jobs-scraper
pip install -r requirements.txt
```

### Step 2: Get Google Cloud credentials (one-time, ~10 min)
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
1. Go to [sheets.new](https://sheets.new) → creates a blank Sheet
2. **Share** the Sheet with the service account email (looks like `jobs-scraper@your-project.iam.gserviceaccount.com`)
   - ⚠️ **Editor** access required
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
# Edit .env:
#   GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json
#   SHEET_ID=<paste your sheet ID>
#   SHEET_GID=<paste your GID, usually 0 for first tab>
```

### Step 5: Run your first scrape
```bash
# List only (no JD fetch, fast, ~30 sec)
python sg_product_jobs.py 7d --source linkedin

# Full pipeline (list + JD + sheet write, ~50 min for 7d)
python sg_product_jobs.py 7d --source linkedin --with-jd --to-sheet "$SHEET_URL"
```

That's it. You should see jobs in your Google Sheet.

---

## 📖 CLI Reference

```
python sg_product_jobs.py [range] [options]

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
  python sg_product_jobs.py 24h --source $src
done

# Deep LinkedIn 14d refresh with JD + sheet
python sg_product_jobs.py 14d --source linkedin --with-jd --to-sheet "$URL"

# JobStreet full 30d sweep (all 5 keywords × 25 pages)
python sg_product_jobs.py 30d --source jobstreet --with-jd --to-sheet "$URL"

# Taiwan instead of Singapore
python sg_product_jobs.py 7d --location Taiwan

# Force re-fetch all JDs (after schema change in your Sheet, etc.)
python sg_product_jobs.py 7d --source linkedin --refetch --to-sheet "$URL"
```

---

## ⚙️ Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `GSPREAD_SA_KEY_PATH` | `.secrets/gsheet-sa.json` | Path to your service account JSON |
| `SHEET_ID` | (empty) | Your Google Sheet ID. **Must override** to use your own sheet |
| `SHEET_GID` | `0` | The sheet tab GID within the spreadsheet |
| `JOBSTREET_KEYWORDS` | `product manager,product director,director of product,head of product,product lead` | Comma-separated JobStreet search keywords |
| `LINKEDIN_GEO_ID` | `102454443` | LinkedIn geoId (Singapore). 104187078=Taiwan, 107388191=Shanghai |

If `SHEET_ID` is empty, the script falls back to the original developer's Sheet — but you'll get a permission error unless you're the developer. **Always set your own `SHEET_ID`.**

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
  - 11-column Google Sheet write (Status, Date, Source, URL, Co, Title, JD, Loc, WM, Visa)
```

See **[RULES.md](RULES.md)** for the full design rules, 14 known gotchas, and historical context.

---

## 🧪 Testing

```bash
python test_helpers.py
```

Should print `27/27 通過, 0 失敗`. Covers:
- HYPERLINK formula generation for all 3 sources
- Sheet row parsing for dedup (LinkedIn digit, Jora 32-hex, JobStreet digit)
- Work mode regex (Title prefix, JD header, Chinese patterns, fallback)

---

## 🤖 Use with Codex / Claude Code

This script is Codex-friendly. Example conversation with Codex:
> "Run `python sg_product_jobs.py 7d --source linkedin --with-jd` in the jobs-scraper repo"

For more advanced integration (MCP server so Codex has native `crawl_jobs()` / `audit_sheet()` tools), build an MCP server wrapper around `sg_product_jobs.py` — out of scope for this repo but straightforward (one file using the `mcp` Python SDK).

---

## 🔧 Troubleshooting

**"gspread.exceptions.SpreadsheetNotFound"**
→ Wrong `SHEET_ID`, or service account email not shared with the Sheet.

**"403 rate limit"** (LinkedIn only)
→ Wait 30-60 min, or reduce `--max-pages`. The script uses random 3-10s sleep + curl_cffi to mimic browser, but heavy testing can still trigger.

**"Cloudflare"** (HTML page, not API)
→ JobStreet HTML pages are blocked. The script uses the public API + GraphQL which is not blocked. If you need HTML page data, you're out of luck.

**Empty results for `daterange=1` (1 day)**
→ Normal. LinkedIn 1h and JobStreet 1d often have 0 jobs because most are posted in 1-3 days.

---

## 📜 License

MIT — do whatever you want, no warranty.

## 🙏 Credits

Built by [@danielcanfly](https://github.com/danielcanfly) for personal job-search tracking. The 3 source integrations and dedup logic are designed to be transparent and auditable — read the code, it's a single 1600-line file.
