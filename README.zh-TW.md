<p align="right">
  <a href="./README.md">English</a> |
  <a href="./README.zh-TW.md">繁體中文</a> |
  <a href="./README.zh-CN.md">简体中文</a>
</p>

# jobs-scraper

這是一套給 LinkedIn 職缺使用的本機爬蟲與追蹤工具，主要面向產品管理相關職位，並提供 CLI、本機 STDIO MCP server、Agent Skill，以及可攜式 Google 試算表職缺追蹤表。

`jobs-scraper` v1.6.6 在五個來源（`linkedin`、`jobstreet`、`cake`、`104` / `onezerofour`）爬取產品管理職缺，並提供完整 JD enrichment 與追蹤流程。整套工具維持本機優先，保留明確的安全 gate，並可選擇把結果同步到使用者自己的 Google 試算表。

## 概覽

這個 repo 適合想要在本機爬取與追蹤 LinkedIn 產品管理職缺、把憑證留在自己電腦上，並視需要同步結果到自己 Google 試算表的人。

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

- 爬取 LinkedIn Guest API 職缺。
- 可選擇抓取完整 JD。
- 以 `(source, job_id)` 去重。
- 可選擇在完整 JD enrichment 前套用使用者自訂的職稱 skip filter。
- 偵測 work mode 與 visa / constraint 訊號。
- 以 formula-safe 格式寫入使用者自己的 Google 試算表。
- 初始化、稽核與檢視可攜式 Region-Raw / Region-Selected 追蹤表。
- 透過 CLI、MCP 與 Agent Skill 入口暴露工作流。

## 架構一覽

v1.2.0 保持對外行為不變，並把程式碼整理成更清楚的區塊：

- 共用 runtime / execution helpers；
- 集中的 region / source policy；
- LinkedIn Guest API source adapter；
- 拆分後的 Job Tracker modules；
- MCP service layer；
- selective Google Sheet reads；
- 內部 typed service errors 對應穩定的 public error code；
- Ruff lint / import gate；
- 排除 byte-frozen equivalence harness 的 scoped Ruff format gate；
- mypy scaffold；
- coverage 報告。

## LinkedIn 地點指定

爬蟲使用 LinkedIn Guest API，並透過 LinkedIn `geoId` 指定搜尋地點。

為了相容既有資料，舊版 Jora／JobStreet 整合曾寫入的 Tracker / cache rows 仍可用於 audit 與 dedup；新的網路請求則不再使用這些舊整合。

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

LinkedIn 可用 `geoId` 指定地點：

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --geo-id 104187078
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

### 中國：三個城市同一張表

中國不只一個地方。`region="China"` 爬的是**上海**；`region="Hangzhou"` 與 `region="Shenzhen"`
各自是獨立的 region。三個都寫進同一張 `China-Raw`：

| Region | 城市 | LinkedIn geoId | 別名 | 寫入 |
|---|---|---|---|---|
| `China` | 上海 Shanghai | `107388191` | `cn`、`china`、`中國`、`shanghai` | `China-Raw` |
| `Hangzhou` | 杭州 | `101821877` | `hz`、`杭州` | `China-Raw` |
| `Shenzhen` | 深圳 | `106750182` | `sz`、`深圳` | `China-Raw` |

城市是 opt-in：預設 region 仍是 `SG` / `TW` / `China`，而且多個城市一起初始化時，
`China-Raw` 只會被建立一次。

CLI 也支援同樣的三個城市，`--location` 會從同一張 preset 表查 geoId：

```text
sg_product_jobs.py 7d --source linkedin --location Hangzhou --to-sheet "<China-Raw URL>"
```

中國職缺**不做簽證判斷**：台灣人可拿通行證入職，所以中國專屬的國籍字眼
（`Chinese citizens only`、`僅限中國公民`、`必須為中國公民`、`上海戶口優先`、`中國人優先`）
不會產生任何訊號。新加坡或台灣職缺若要求國籍，仍照舊是 hard blocker。

## MCP 工具

| Tool | Sheet write? | 用途 |
|---|---:|---|
| `crawl_jobs` | 否 | 爬取 LinkedIn；可能更新本機快取。 |
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
--source:         linkedin | jobstreet | cake | 104 | onezerofour
--with-jd:        抓取完整 JD
--to-sheet:       Google Sheet URL 或 raw ID
--gid:            舊版 direct CLI 用的 worksheet GID
--max-pages:      覆寫來源頁數上限
--refetch:        忽略 JD cache
--no-skip:        關閉所有標題過濾（包含 v8.5 語意群組）
--dry-run-sheet:  預覽，不寫入列資料
--location:       LinkedIn location/preset
--geo-id:         明確指定 LinkedIn geoId
--skip-keywords:   額外的標題關鍵詞比對，疊加在 v8.5 語意群組之上
--sheet-source:   D 欄 source label
```

完整 JD enrichment 預設會套用凍結的 title skip filter v8.5，語意規範以 [`SKIP.md`](SKIP.md) 為準。用 `--no-skip` 可抓取每一份 JD；用 `--skip-keywords` 可在 v8.5 語意群組之上額外加上關鍵詞比對：

```bash
python sg_product_jobs.py 14d --source linkedin --with-jd --skip-keywords intern junior assistant
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
- Jora 已從主動網路來源移除（網站已關站）；舊 Tracker rows 仍可被 audit 讀取並正常 dedup round-trip。JobStreet 自 v1.4.0 起重新成為主動來源。
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
- `SOURCE_REGION_UNSUPPORTED`：請求的來源／地區組合不受支援。v1.4.0 將 LinkedIn / JobStreet 導向 `SG-Raw`，104 / Cake 導向 `TW-Raw`；已退役的 `jora` 會被拒絕。
- `SHEET_NOT_FOUND`：確認 spreadsheet ID 與分享權限。
- `LinkedIn 403/429`：縮小範圍或稍後再試。

## 版本與發版說明

`v1.8.1` 為目前版本：修掉 v1.8.0 帶進來的節奏 bug —— 104 的預算從來沒作用在真正該受節奏管的請求上。104 的 list paging 跑在 adapter 自己的 `ThreadPoolExecutor` worker 裡，而 Python 3.11 的新 thread 以乾淨的 context 起步 → 引擎在主執行緒釘住的 source 在 worker 裡看不見 → 每個 104 list 頁都落回全域 3–10s。跑 TW 7d 時看得很清楚：list 的 sleep 是 4.8s、6.8s、9.4s、4.9s、3.2s，而同一輪的 detail sleep 是 1.5–1.7s（104 的值）。現在節奏 hook 是在 worker thread 裡被呼叫的 → source 就釘在那裡。預算也改成按「總請求率」選，而不是按「兩個請求的間隔」，因為 104 的 list API 對同時在飛的請求數敏感：8 個 keyword worker 各 1.0–2.0s = 聚合 2.1 req/s，一輪開頭就被回 403；單 worker 1.0–2.0s = 聚合 0.5–1.0 req/s → 走完 50 頁（1,010 筆）零失敗。現在單 keyword 用 104 的預算，多 keyword 平行維持全域預算（那是一直以來跑得動 104 的速率）。

`v1.8.0` 為目前版本：慢的不是網路，是引擎在等。2026-11-24 對照線上 API 實測：2026-11-24 對照線上 API 實測：JobStreet list 一頁純網路 0.80s、JobStreet JD 0.29s、LinkedIn list 一頁 0.92s，而引擎在**每個**請求之後都睡 3–10s（平均 6.5s）。sg 30d 的 JobStreet 階段 3h51m 發了 1,750 個請求：80% 在睡、6% 在網路上、14% 在 process 啟動與讀表。由此得到三個改動。第一，每個來源有自己的節奏，而且預算就放在各自的 adapter 裡：JobStreet 0.5–1.0s（公開 list API 與 GraphQL 實測 0.5s 間隔連發 200 個請求零失敗、10 req/s 零失敗）、LinkedIn 1.5–3.0s（Guest API 真的會回 429，所以保守保留 30/60/90s 的 retry ladder）、104 1.0–2.0s（detail API 實測 0.3s 間隔連發 59 筆零失敗；而它的 list API 原本**完全沒有**一般性的節拍 → 8 個 keyword worker 會無間隔連打，實測密集 burst 之後回過 403）、Cake 維持 3–10s（Cake 在 2–5s 就回 429）。預算可以用 `JOBS_SCRAPER_<SOURCE>_SLEEP_MIN` / `_MAX` 從環境變數覆寫，不用改 code。第二，塊改成「爬自己的頁區間」而不是「重爬整個前綴」：舊 supervisor 是累計式切塊，第 N 塊爬第 1..N 頁 → 前面每一頁每跑一塊就重抓一次，30d 的 JobStreet 發了 2,179 次分頁請求但池子只需要 ~406 頁（5.4×，`product lead` 一個 keyword 就 7.5×），LinkedIn 同樣吃了 3.55×。現在每塊擁有自己的區間（`--start-page` / `--max-pages`），只爬自己那幾頁；跨塊去重不受影響，因為 seen file 與「對目標分頁做 pre-detail dedup」本來就跨 process 存活。第三，抓 JD 改成 thread pool（預設 3 個 worker，`JOBS_SCRAPER_JD_WORKERS`），不再是一個接一個的 `for` 迴圈：thread 只做網路 I/O，seen file、計數器與輸出順序都留在主 thread → `seen_jds.jsonl` 不會交錯、Sheet 的 row 順序也不變。區間超出池子時回空資料，那是「結束」而不是「缺口」。

現在寫入起點會在「知道要寫幾列」之後才定：只有當那個洞連續塞得下整批列時才用它，否則一律 append 到最後。塞得下的洞還是會被填，所以正常情況的行為不變。

`v1.6.9` 修好了 104 這個 source —— 它原本根本沒跟 104 講上話。`https://www.104.com.tw/jobs/search/api/jobs` 每一個請求都回 403 block 頁，而 104 首頁回 200 —— 少了兩個東西。第一，瀏覽器的 XHR 一定會帶 `sec-fetch-dest` / `sec-fetch-mode` / `sec-fetch-site` 這組 header，104 的 bot 保護會看它們，所以 adapter 現在補上這三個，再加 `x-requested-with: XMLHttpRequest` 與 `Origin`。第二，這台機直連 104 API 也被拒，所以 104 的 list 與 detail fetch 現在跟其他 adapter 一樣走共用的 `resolve_proxies()`。症狀是最危險的那種：不是報錯，是空爬 —— `無資料，結束` 加上 exit 0 看起來像「台灣這週沒有產品職缺」，實際上請求根本沒到 API。

`v1.6.8` 讓每個 JobStreet keyword 都爬到自己的池底。一個五個 keyword 的 crawl，實際只爬到一個。JobStreet 的 list API 一次只吃一個 keyword，所以 crawl 會把 keyword 依序跑完再跨 keyword 用 `job_id` 去重 —— 但結束一個 keyword 的軟停，量的是「對**整輪** crawl 而言是新的」筆數：第一個 keyword 把共用的 `seen` set 填滿之後，後面每個 keyword 的第一頁幾乎沒有「新的」，於是全部停在那裡，5 個 keyword 有 4 個在第 1 頁就被放棄，7d 那輪只拿到 ~250 筆，而 API 自己回報的總數是 ~2,600。現在這個訊號量的是「對**那個 keyword** 而言是新的」筆數，所以每個 keyword 都會翻到自己的池底，而兩個 keyword 都撈到的職缺仍然只回傳一次。頁數預算也跟著改：每個 keyword 都爬自己的池子之後，只按第一個 keyword 定的預算會截斷其他 keyword，於是重新釘在 API 回報的最大池深上（`1h` 20 頁、`24h` 20、`3d` 40、`7d` 73、`14d` 120、`21d` 168、`30d` 220）—— v1.6.7 的 `1h` / `24h` / `3d` 連這都蓋不住，所以三個一起拉高，免得修好軟停只是換一種截斷。重試用完仍失敗的 keyword 現在只結束自己，不會把整輪的成果一起丟掉，而且失敗仍然看得到（`FAIL` 行照印，最後還會列出失敗的 keyword）。代價是成比例的：JobStreet 的 list 請求大約多 5 倍、unique 職缺大約多 7 倍（7d 預期從 ~250 變成 ~1,800 筆），所以跑起來會比較久。

- `v1.6.7` 為兩個憑空猜的預算上限，加上一個被重試三分鐘的 400。v1.6.6 把 LinkedIn 的頁數上限釘在**上海**的池深上，但新加坡的池每個長 range 都更深 —— 7d 約 600 筆對上海的 400 —— 所以那些上限對新加坡來說仍在截斷；現在改成依兩個城市實測最深的池：1h 8 頁、24h 15、3d 35、7d 80，14d/21d/30d 都是 100 —— 100 是 Guest API 自己的分頁天花板，不是猜的。JobStreet 的上限則從來沒量過 —— 表格註解預期 7d 會有 ~600 筆 unique，實際只有 ~250，因為 5 個 keyword 共用同一個 seen set，50% 軟停讓其中四個在第 1 頁就被放棄 —— 而 API 自己回報的總數遠大於原本的上限（7d 最大的 keyword 匹配 955 筆、14d 1670、30d 3251，原上限卻是 15/30/25 頁）；現在依最大 keyword 的池子加上餘裕來設。LinkedIn list page 上的非 429 4xx 不再走 retry ladder：adapter 的 docstring 與凍結契約都寫明那是 caller bug、應該直接 raise，但 `raise_for_status()` 在 `try` 裡 raise、被寬鬆的 `except Exception` 接走，於是那一頁被重試四次（30+60+90s）才放棄 —— 現在跟 JobStreet adapter 一樣立刻拋 `FatalListPageError`。而 API 的分頁天花板是「結束」不是「失敗」：`start=1000` 回的是 HTTP 400 而不是空頁，原本會讓整塊 abort、supervisor 把那個 FAIL 讀成 coverage 缺口；現在撞到天花板會帶著已收到的職缺正常收尾。

- `v1.6.6` 修掉兩個長得同一副模樣的問題： run 看起來成功，實際上安靜地少做了該做的事。一個 range 的頁數上限必須蓋得住那個 range 真正的池子。LinkedIn 的 range 表原本給 `30d` 25 頁（250 筆），但上海 30 天的池子有約 700 筆，於是 crawl 在上限處停下、run 回報成功、剩下的職缺從來沒被看見。新的上限依 2026-11-22 對 Guest API 實測的池深設定（`1h` 少於 50、`24h` 約 100、`3d` 約 250、`7d` 約 400、`14d` 約 290、`21d` 約 300、`30d` 約 700 筆）。上限是天花板而不是目標：crawl 連續 2 頁沒有新職缺就會自己結束，所以池子小的城市照樣提早停，放寬上限對它們沒有成本。pre-detail dedup 現在讀的是這一輪要寫進去的那個分頁 —— 目標 gid 的解析跟寫入層一致（explicit `--gid` → `--to-sheet` 內的 `#gid=` → label 映射），不再讓 `LinkedIn / Minimax` 一律讀 `SG-Raw`，那會讓中國的 run 去抓 Sheet 根本不會寫進去的職缺 JD。發布流程也恢復綠燈：v1.6.5 有 bump 套件版本卻沒 bump `uv.lock`，CI 在第一道關卡就掛掉，GitHub 上一直是紅的。

- `v1.6.5` 修掉兩個會讓一輪 run 靜默死掉的 LinkedIn Guest API 問題。合法的空 list page 只有 26 bytes、解析不出 root，原本 list parser 會直接 raise，於是 page loop、chunk、整輪 run 一起死 —— 2026-11-21 有一個城市的 crawl 三個塊全部這樣死掉、一列都沒寫進 Sheet，process 還 exit 0。現在空頁會被解析成 0 筆，crawl 會繼續抓下一頁；而且空頁依然不會被重試，因為它是合法答案而不是故障。JD 抓取也補上跟 list fetch 同一套 30/60/90s retry ladder：429、5xx、連線錯誤會重試而不是放棄 —— 因為沒有 JD 的職缺會被 Sheet 寫入層整列跳過，等於職缺就這樣從 run 裡消失。兩個修正都跟中國無關，是 Guest API 的通性，每個 region 都會踩到。中國變成三個可爬的城市，而且中國職缺不再帶簽證判斷。`China` 是上海，`Hangzhou` 與 `Shenzhen` 各自是獨立的 region，geoId 已實抓驗證（`101821877`、`106750182`）；三個都寫進同一張 `China-Raw`，城市是 opt-in，預設 region 仍是 `SG` / `TW` / `China`。中國專屬的國籍字眼（`Chinese citizens only`、`僅限中國公民`、`必須為中國公民`、`上海戶口優先`、`中國人優先`）已從簽證判斷移除——台灣人可拿通行證入職——但新加坡／台灣的通用判斷完全不變。爬蟲路徑也可以被指定要走哪一條出口。LinkedIn Guest API 在某些網路區段對直連回 HTTP 451，Google Sheets API 在同一種環境直連會 timeout，但走 proxy 兩邊都正常。用 `JOBS_SCRAPER_PROXY`（或標準的 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`）指定，`doctor` 會顯示目前生效的 proxy 並探它還活著嗎；都沒設就維持直連。較早版本：

- `v1.6.4` 中國變成三個可爬的城市，並移除中國專屬的簽證判斷。

- `v1.6.2` 把 jobs 資料移出「產生的 Sheet 寫入 worker」原始碼：之前它是被序列化成一個字串字面值寫進 worker 的 *Python* 原始碼裡的，一輪 30 頁的 run 會產生好幾 MB 的原始碼，CPython 得先把整個字串拉過 tokenizer 才能開始寫入 —— 那個記憶體尖峰正好落在寫 Sheet 的那一刻。現在 jobs 放獨立 JSON 檔，worker 用 `json.load()` 讀，產生的 worker 維持 KB 級。

- `v1.6.1` 修掉 Sheet 寫入 subprocess 的一個 bug：生成的 worker 用 JSON 編碼器把參數嵌進「產生的 Python 原始碼」裡，預設的 `gid=None` 於是變成裸的 `null` token，worker 還沒連上 Google 就先 `NameError: name 'null' is not defined` 死掉。因為寫入流程只有在 subprocess 失敗時才會退回 in-process，每一次 run 其實都悄悄失去了那層 subprocess 的 timeout 保護。現在參數改用 Python 字面值嵌入。

較早版本：

- `v1.6.2` 把 jobs 資料移出生成的 Sheet 寫入 worker 原始碼。
- `v1.6.1` 把生成 worker 的參數改用 Python 字面值，不再用 JSON。
- `v1.6.0` 把 LinkedIn 自 v1.3.1 就有的 30/60/90s retry ladder 補給了 JobStreet list page。
- `v1.3.1` 在 source layer 新增 LinkedIn list page 429 retry。
- `v1.3.0` 移除 Jora 與 JobStreet 網路整合，主動來源 contract 收斂為 LinkedIn，同時保留歷史 Tracker row 的解析能力。

- `pyproject.toml` 保存套件版本。
- `.codex-plugin/plugin.json` 保存 plugin 版本。
- `server_v1_1.py` 對外提供 MCP server 版本。
- 目前 frozen equivalence baseline 為 `v1.8.1`，明確保護五來源 contract、「每個來源一個 adapter」的拆分、JobStreet list page 的 retry ladder、LinkedIn 空頁與 JD retry 規則、「range 的頁數上限必須蓋得住每個已知城市的實測池深」規則、「每個 JobStreet keyword 都要爬到自己的池底」規則、「Guest API 1000 筆分頁視窗是結束而不是失敗」規則、「pre-detail dedup 讀的是要寫入的那個分頁」規則、「生成 worker」的相關規則、per-source 節奏規則、頁區間規則，以及平行抓 JD 規則。

## 授權

MIT。見 [`LICENSE`](LICENSE)。
