# ops/ — 抓取 supervisor 與運維工具

這個資料夾是**抓取流程的操作面**：誰在跑、跑哪個 range、怎麼切塊、state 記在哪、
怎麼清掉重跑、怎麼量池子多深。這些是經過實跑調出來的東西，不該只存在某台機器的某個目錄裡。

程式碼本體在 repo 根目錄（`sg_product_jobs.py` + `jobs_scraper/sources/*.py`）；
這裡只放**怎麼驅動它**。

## 目錄分工

| 位置 | 放什麼 | 版控 |
|---|---|---|
| repo `ops/` | 這些腳本（source of truth）| ✅ |
| `$JOBS_SCRAPER_RUNTIME_DIR`（預設 `~/.minimax-agent/projects/.runs`）| `*.log`、`*_chunk_state.txt`、pid、`.bak-*` | ❌ 不進版控 |

執行期狀態與腳本分開，是為了讓 repo 保持乾淨（CI 的 hygiene 掃全樹），
而且 state 檔可以在換機器時直接沿用。

## 環境變數

| 變數 | 預設 | 用途 |
|---|---|---|
| `JOBS_SCRAPER_DIR` | `~/.minimax/plugins/jobs-scraper` | 程式碼 + venv + `.env` 所在（plugin runtime）|
| `JOBS_SCRAPER_RUNTIME_DIR` | `~/.minimax-agent/projects/.runs` | log / state 所在 |
| `UPSTREAM_DIR` | `~/.minimax-agent/projects/jobs-scraper-unified` | upstream repo（`gen_sha256sums.py`、`update_freeze_v168.py` 用）|
| `SHEET_ID` | 必須設定 | China 系列 runner 寫入的試算表；**沒有就 fail-closed 不跑** |

沒有任何一支腳本寫死帳號、憑證、試算表 ID 或家目錄絕對路徑。

## 三個 runner

| 腳本 | 抓什麼 | 切塊 |
|---|---|---|
| `run_sg_chunked.sh <range>` | LinkedIn（`SG_SOURCES=linkedin`）| 引擎預設 max pages 切成 N 個**頁面區間** |
| `run_sg_jobstreet.sh <range>` | JobStreet（keyword 軸：每個 keyword 一段區間）| 每個 keyword 自己的區間計畫 |
| `run_tw_chunked.sh <range>` | 104 / 台灣（keyword 軸）| 同上，區間計畫寫在腳本裡 |

`run_chain.sh` 把 SG → TW 的多個 range 串成一條鏈，一次一個（同一張 Sheet 不能平行寫）。

### 為什麼是「頁面區間」而不是「累計頁數」

舊的切塊方式第 N 塊爬第 1..N 頁 → 前面每一頁每跑一塊就重爬一次（30d JobStreet 實測
2,179 次分頁請求換 ~406 頁的池子，5.4× 重複）。改成區間式後每頁只抓一次；
跨塊去重靠既有的 `seen_jds.jsonl` + 對目標分頁的 pre-detail dedup，不需要在 adapter 裡處理。

### state 檔的用途（以及陷阱）

state 檔記的是「這個頁面區間已經爬過」，key 形如 `linkedin:1-27`。
它的用途是**同一輪內的續跑保護**：中途被殺時 state 還在，下次從未完成的塊接續。

**但它不是跨輪的 cache**：區間計畫是固定的，下一輪再跑同一個 range 會全部命中 → 整輪跳過
→ 池子裡新長出來的職缺一個都撿不到。所以**每輪新的抓取之前要先清 state**：

```bash
bash ops/reset_state.sh 7d     # 清空 + 留 .bak-<時間戳>
```

`reset_state.sh` 會同時處理 SG（`sg<N>` 與 `sg<N>js`）與 TW（`tw<N>`）的 state 檔。

## 怎麼跑

```bash
# 1. 清上一輪的 state
bash ops/reset_state.sh 7d

# 2. 跑（用 launchctl 讓它脫離終端機，被殺也不會留半死行程）
launchctl submit -l com.mavis.sg7 -- /usr/bin/env SG_SOURCES=linkedin \
  /bin/bash "$PWD/ops/run_sg_chunked.sh" 7d

# 3. 看進度
tail -f ~/.minimax-agent/projects/.runs/sg7.log
wc -l < ~/.minimax-agent/projects/.runs/sg7_chunk_state.txt

# 4. 跑完 supervisor 會自己 launchctl remove 掉那個 label
```

`tw_paused.flag` 是 TW 的暫停開關：內容含 `paused` → 該 range 直接跳過（exit 2）；
改成 `run` 恢復。用「內容」而不是「檔案存在」是因為刪檔會被權限閘擋。

## 量池子多深

104 的搜尋是模糊匹配，**沒有天然池底**：`metadata.pagination` 裡的 `total` 三個 range
都是 1,001（那是顯示上限），`lastPage` English keyword 150、中文「產品經理」7d 只有 110，
而實測 page 200 還有資料。所以深度是**預算**不是池深 —— 用 `probe_pool_depth*.py` 量，
結果記在 `probe_*.py` 的註解裡。

JobStreet 有真正的池底：每個 keyword 的最後一塊會讀到空頁 → 該塊記成「pool 到底」，
不是缺口。LinkedIn 一路到分頁天花板（`start=1000`）或連續兩頁 0 new 才停。

## 私有狀態的備份（不要放 GitHub）

`.env`（試算表 ID）與 `.secrets/gsheet-sa.json`（Service Account **私鑰**）
**不進任何 GitHub repo**（含 private）：git 歷史永久留著、刪檔救不回來、
repo 一旦轉 public 或加了協作者就外洩、而且 GitHub 自己在掃 secret。

用 `openssl` 加密後放進密碼管理器：

```bash
# 加密 (會問 passphrase)
tar -czf - -C "$JOBS_SCRAPER_DIR" .env .secrets \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -out jobs-scraper-secrets.enc

# 解開
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -in jobs-scraper-secrets.enc \
  | tar -xzf - -C "$JOBS_SCRAPER_DIR"
```

passphrase 本身放密碼管理器，不要跟加密檔放在一起。

## 這些腳本怎麼被檢查

CI 對整個 repo 跑 `ruff format --check` 與 `ruff check`，所以 `ops/` 裡的 Python
也必須乾淨。`scripts/check_repo_hygiene.py` 掃**全樹**，所以任何寫死的試算表 ID、
Service Account 身分或私鑰片段都會讓 CI 失敗 —— 這是刻意的，寫死的識別碼就是會外洩的東西。
