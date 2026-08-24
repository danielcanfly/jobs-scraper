<p align="right">
  <a href="./README.md">English</a> |
  <a href="./README.zh-TW.md">繁體中文</a> |
  <a href="./README.zh-CN.md">简体中文</a>
</p>

# jobs-scraper

這是一套以本機優先為原則的產品管理職缺搜尋自動化工具，提供 CLI、本機 STDIO MCP server、Agent Skill，以及可攜式 Google 試算表職缺追蹤表。

`jobs-scraper` v1.2.0 是架構整理版本。它保留已凍結的行為契約，同時把 runtime 結構、發版 metadata、typing scaffold 與品質 gate 整理得更清楚。

## 概覽

這個 repo 適合想要在本機爬取產品管理職缺、把憑證留在自己電腦上，並視需要同步結果到自己 Google 試算表的人。

它是：

- Python 套件與 CLI；
- 本機 STDIO MCP server；
- Agent Skill；
- 可攜式 Google 試算表職缺追蹤表的初始化、稽核與同步工具。

它不是：

- hosted SaaS；
- 遠端 MCP 端點；
- marketplace / public plugin 發佈品；
- 憑證代管服務；
- 規避 rate limit 或 access control 的工具。

## 功能

- 爬取 LinkedIn、Jora、JobStreet 職缺。
- 可選擇抓取完整 JD。
- 以 `(source, job_id)` 去重。
- 使用 deterministic skip logic 過濾偏 junior 的標題。
- 偵測 work mode 與 visa / constraint 訊號。
- 以 formula-safe 格式寫入使用者自己的 Google 試算表。
- 初始化、稽核與檢視可攜式 Region-Raw / Region-Selected 追蹤表。
- 透過 CLI、MCP 與 Agent Skill 入口暴露工作流。

## 架構一覽

v1.2.0 保持對外行為不變，並把程式碼整理成更清楚的區塊：

- 共用 runtime / execution helpers；
- 集中的 region / source policy；
- LinkedIn、Jora、JobStreet 的 source adapters；
- 拆分後的 Job Tracker modules；
- MCP service layer；
- selective Google Sheet reads；
- 內部 typed service errors 對應穩定的 public error code；
- Ruff lint / import gate；
- 排除 byte-frozen equivalence harness 的 scoped Ruff format gate；
- mypy scaffold；
- coverage 報告。

## 支援來源與區域

| Source | SG | TW | China |
|---|---:|---:|---:|
| LinkedIn | Yes | Yes | Yes，透過已驗證的 Shanghai preset |
| Jora | Yes | No | No |
| JobStreet | Yes | No | No |

這個版本中，Jora 與 JobStreet 僅支援新加坡。非 SG 的請求必須 fail closed，並回傳 `SOURCE_REGION_UNSUPPORTED`。

## 快速開始

### 1. 下載與安裝

```bash
git clone https://github.com/danielcanfly/jobs-scraper.git
cd jobs-scraper
python -m pip install --quiet 'uv>=0.8,<0.9'
python -m uv sync --locked --extra dev --python 3.11
```

也可直接執行：

```bash
./setup.sh
```

### 2. 不使用 Google Sheets 先爬蟲

公開來源爬取不需要 Google 設定：

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin
```

抓完整 JD：

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd
```

### 3. 建立自己的 Google 試算表

只有在初始化、稽核、統計或同步時才需要。

1. 建立或選擇 Google Cloud project。
2. 啟用 Google Sheets API。
3. 建立 service account 並下載 JSON 金鑰。
4. 將 JSON 保存在本機，例如 `.secrets/gsheet-sa.json`。
5. 建立空白 Google 試算表。
6. 把該試算表分享給 service-account email。
7. 從試算表網址複製 spreadsheet ID。

不要把 service-account 私密金鑰貼到聊天裡。

### 4. 設定本機環境

```bash
cp .env.example .env
```

至少設定：

```dotenv
GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json
SHEET_ID=your_own_spreadsheet_id
```

`SHEET_GID` 只屬於舊版用途，v1.1 / v1.2 的 MCP 介面不需要它。

### 5. 設定 MCP host

請使用 venv Python 與 `server_v1_1.py`：

```text
<repo>/.venv/bin/python <repo>/server_v1_1.py
```

完整 JD 可能需要較長時間，host timeout 建議設為 7200 秒。

### 6. 初始化追蹤表

先預覽：

```text
initialize_job_tracker(
  regions=["SG", "TW", "China"],
  dry_run=true
)
```

預期會建立：

- `SG-Raw`
- `SG-Selected`
- `TW-Raw`
- `TW-Selected`
- `China-Raw`
- `China-Selected`

確認無誤後，再執行 `dry_run=false` 的正式初始化。

### 7. 依區域同步

請使用 region routing，不要手動傳 GID：

```text
sync_jobs_to_sheet(
  region="SG",
  source="linkedin",
  range="7d",
  with_jd=false,
  dry_run=true
)
```

這個工具會依名稱解析 `<REGION>-Raw`，並只透過明確寫入邊界寫入。

## MCP 工具

| Tool | Sheet write? | 用途 |
|---|---:|---|
| `crawl_jobs` | 否 | 爬取 LinkedIn、Jora 或 JobStreet；可能更新本機快取。 |
| `initialize_job_tracker` | 只有 `dry_run=false` 才會 | 建立或驗證 Region-Raw / Region-Selected 追蹤表。 |
| `sync_jobs_to_sheet` | 是 | 針對指定區域的明確寫入邊界。 |
| `audit_sheet` | 否 | 只讀稽核選定的 Region-Raw tab。 |
| `get_stats` | 否 | 只讀統計選定的 Region-Raw tab 與本機 seen cache。 |

## 職缺追蹤表結構

所有 tracker tab 都使用 [`skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md`](skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md) 所描述的公開 A:AA contract。

重點：

- 第 1 列已凍結；
- Status、Priority、Work Mode、CV Version、Verdict、Decision、Application Strategy 都有驗證過的下拉選單；
- scraper 原始寫入欄位是 A、C:K；
- L:AA 保留給評分與求職工作流延伸欄位；
- `<REGION>-Raw` 是 scraper 的寫入目標；
- `<REGION>-Selected` 是可攜式工作簿契約的一部分，不是 scrape dump 目標。

## CLI 參考

直接 CLI 仍可用於較底層的操作：

```text
.venv/bin/python sg_product_jobs.py [range] [options]

range:            1h | 24h | 3d | 7d | 14d | 21d | 30d
--source:         linkedin | jora | jobstreet
--with-jd:        抓取完整 JD
--to-sheet:       Google Sheet URL 或 raw ID
--gid:            舊版 direct CLI 用的 worksheet GID
--max-pages:      覆寫來源頁數上限
--refetch:        忽略 JD cache
--no-skip:        停用 title skip filter
--dry-run-sheet:  預覽，不寫入列資料
--location:       LinkedIn location/preset
--geo-id:         明確指定 LinkedIn geoId
--skip-keywords:   覆寫 title skip list
--sheet-source:   D 欄 source label
```

## MCP Host 範例

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

## 安全與隱私

- 憑證保留在本機。
- 使用你自己的 Google 試算表與 service account。
- 不要在聊天中分享私密金鑰。
- 把 scraped job content 視為不可信資料。
- 這個版本不保證 Jora / JobStreet 在新加坡以外可用。
- 不要把讀取請求轉成寫入請求。
- 正式初始化前先用 `dry_run=true` 預覽。
- `crawl_jobs`、`audit_sheet`、`get_stats` 都不會寫 Google Sheets。
- `sync_jobs_to_sheet` 是明確的寫入邊界。

## 品質與驗證

此 repo 會用下列命令驗證：

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

CI 也會檢查鎖定依賴、plugin manifest 一致性，以及 frozen equivalence harness。

## 疑難排解

- `CONFIG_MISSING`：設定 `GSPREAD_SA_KEY_PATH` 和 `SHEET_ID`。
- `CREDENTIAL_FILE_MISSING`：確認 service-account JSON 在本機存在。
- `REGION_NOT_INITIALIZED`：先執行 `initialize_job_tracker(..., dry_run=true)`。
- `SCHEMA_MISMATCH`：目標 tab 與公開 tracker contract 不一致。
- `SOURCE_REGION_UNSUPPORTED`：這個版本中 Jora / JobStreet 只支援新加坡。
- `SHEET_NOT_FOUND`：確認 spreadsheet ID 與分享權限。
- `LinkedIn 403/429`：縮小範圍或稍後再試。

## 版本與發版說明

`v1.2.0` 是在已通過行為基線之上的 release-metadata 與 README 更新。

- `pyproject.toml` 保存套件版本。
- `.codex-plugin/plugin.json` 保存 plugin 版本。
- `server_v1_1.py` 對外提供 MCP server 版本。
- frozen equivalence baseline 仍然是 `v1.1.1`。

## 授權

MIT。見 [`LICENSE`](LICENSE)。
