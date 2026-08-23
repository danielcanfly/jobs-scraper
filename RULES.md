# sg_product_jobs.py — 完整規範清單

> 最後更新：2026-08-19
> 任何改動都同步更新這份

---

## 1. Filter 規則 (Title Skip)

### 1.1 命中就 Skip（不撈 JD、不打 request）

| 類別 | 詞 |
|---|---|
| 明確太菜 | `intern` / `internship` / `trainee` / `graduate` / `grad` / `entry` / `entry level` / `entry-level` / `junior` / `jr` |
| 助理/支援 | `assistant` / `support` / `coordinator` / `administrator` / `clerk` / `secretary` |
| Analyst track | `product marketing` / `product analyst` / `analyst` |
| QA | `qa` / `test` / `quality assurance` |
| Sales | `sales` / `business development` / `account executive` |
| Specialist | `specialist` |
| 短/臨時 | `temp` / `temporary` / `contract` |

比對：case-insensitive + word boundary `(?<![a-z])(word)(?![a-z])`

### 1.2 Senior Whitelist（豁免 skip 過濾）

兩種判定模式，視 skip 詞決定：

| Skip 詞 | 模式 | 邏輯 |
|---------|------|------|
| `assistant` | **adjacent** | `assistant` 後**直接接** senior 詞才算 |
| `specialist` | **anywhere** | title 任一位置有 senior 詞就算 |

Senior 詞 (anywhere 模式用)：`avp` / `vp` / `vice president` / `director` / `head` / `chief` /
`senior` / `staff` / `principal` / `lead` / `managing director` / `general manager` / `president` /
`ceo` / `cfo` / `cto` / `cmo` / `coo` / `chairman`

`assistant` adjacent 模式用：`vice president` / `director` / `general manager` / `managing director` / `president` / `ceo` / `cfo` / `cto` / `cmo` / `coo` / `chairman` / `head` / `secretary-general`

**assistant (adjacent) 範例：**
- ✅ KEEP: "Assistant Vice President - ..."
- ✅ KEEP: "Assistant Director, ..."
- ✅ KEEP: "Assistant General Manager ..."
- ❌ SKIP: "Assistant to CEO"
- ❌ SKIP: "Personal Assistant"
- ❌ SKIP: "Assistant Product Manager"
- ❌ SKIP: "Assistant Manager, Retail"

**specialist (anywhere) 範例：**
- ✅ KEEP: "AVP, Specialist, Martech Orchestration Product Owner"（AVP 標記）
- ✅ KEEP: "Senior Specialist, Ground (Product Owner)"
- ✅ KEEP: "Specialist, Lead Product Manager"（lead 標記）
- ❌ SKIP: "Project Specialist (Retirement Withdrawals...)"（無 senior 詞）
- ❌ SKIP: "Tech Specialist"（無 senior 詞）
- ❌ SKIP: "Product Marketing Specialist"（先撞 product marketing，被 skip）

---

## 2. JD 抓取規則

- 端點: `GET https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}`
- 不需要 cookie
- Sleep 隨機 3-10 秒
- 抓所有 `::text` (含裸文字節點，**不只** `p/li/h*/strong/span` 內)
- 失敗 / 429 跳過但繼續流程

---

## 3. Visa / Sponsorship 偵測（K 欄）

| 嚴重度 | 觸發詞範例 | K 欄寫入 |
|---|---|---|
| **HARD** | `will not provide sponsorship` / `no sponsorship available` / `Singapore citizens only` / `PR only` / `不提供簽證` / `Taiwan(ese) citizens only` / `僅限台灣公民` / `Chinese citizens only` / `must be a PRC national` / `僅限中國公民` / `上海戶籍優先` | `⚠️ HARD: <matched text>` |
| **SOFT** | `prioritising applicants who have a current right to work` / `do not require.*sponsorship` / `must be authorized to work` / `不需簽證` / `台灣人優先` / `本地人優先` / `Chinese nationals preferred` / `大陸人优先` | `<matched text>` （純原文, 無前綴）|
| **POSITIVE** | `visa sponsorship available` / `we provide sponsorship` / `會提供簽證` | `<matched text>` （純原文, 無前綴）|

如果三層都沒命中 → K 留空。

**三個地區都支援**：Singapore (102454443), Taiwan (104187078), Shanghai (107388191)。visa patterns 跟 LOCATION/GEO_ID 解耦，run 時依當下 --location 自動套用正確的地區詞。

**Visa detection 只跑 Singapore** (2026-08-21): Taiwan/China 工作簽限制不常見（user 確認），push_to_sheet 對非 SG location 直接跳過 visa detection → K 欄留空。`push_to_sheet` 接受 `location` 參數，由 main 傳入。

---

## 4. URL 規範

### 4.1 4 種 URL 用途對照

| 用途 | 完整 URL | 備註 |
|---|---|---|
| **A. 抓 list（API, 不需 cookie）** | `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={URL-encoded}&location={URL-encoded}&geoId={geoId}&f_TPR={r_seconds}&sortBy=DD&start={n*10}` | **要用這條** |
| **B. 抓 JD 全文（API, 不需 cookie）** | `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}` | **要用這條** |
| C. 給人看的搜尋頁 | `https://www.linkedin.com/jobs/search/?keywords={URL-encoded}&location=Singapore&geoId={geoId}&f_TPR={r_seconds}&sortBy=DD` | 瀏覽器開 |
| D. 給人看的職缺頁 | `https://sg.linkedin.com/jobs/view/{slug}-{job_id}` | 瀏覽器開, 但**不要**拿來當 API |

### 4.2 A 的 query 參數完整說明

```
https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
  ?keywords=...        # 必要。URL-encoded。可含 "..." / OR / AND / - (排除)
  &location=Singapore  # free text，會做 fuzzy match
  &geoId=102454443     # ★ 精確地區 ID。建議用這個，比 location 可靠
  &f_TPR=r86400        # 見 §5 time range
  &sortBy=DD           # DD=Date Descending (新→舊), R=Relevance
  &start=0              # ★ 翻頁用，每次 +10。**不是** +25
```

**URL 編碼細節：**
- `(` `)` `:` `,` `+` `%` `&` 都必須 percent-encode
- Python 用 `urllib.parse.quote(s, safe="")` 處理整段 query value
- Boolean 多關鍵字：`('product manager' OR 'product director') AND -recruiter`

### 4.3 B 的 query 參數

```
https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}
```
無 query 參數。job_id 是純數字字串（如 `4430572342`）。

### 4.4 常用地區 geoId

| 地區 | geoId | 來源驗證 |
|---|---|---|
| Singapore | `102454443` | 從 https://www.linkedin.com/jobs/jobs-in-taipei-city,-taiwan?country=tw 等 URL 觀察 |
| Taiwan (country) | `104187078` | https://www.linkedin.com/jobs/jobs-in-taiwan |
| Taipei (city) | `106907071` | https://www.linkedin.com/jobs/search/?geoId=106907071 |
| United States | `103644278` | 文件記載 |
| United Kingdom | `101165590` | 文件記載 |
| Michigan (US 州) | `103051080` | 文件記載 |
| Mumbai (city) | `106164952` | 文件記載 |
| Mumbai metro | `90009639` | 文件記載 |
| Worldwide | `92000000` | 文件記載 |

> 不確定的 geoId → 到 LinkedIn 搜尋頁看 URL 裡的 `geoId=...` 抓出來

### 4.5 完整可用範例（已驗證 200 OK, 2026-08-19）

**A. 抓 24h Singapore PM 系列 list** (page 1):
```
https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
  ?keywords=%22product%20manager%22%20OR%20%22product%20director%22%20OR%20%22director%20of%20product%22%20OR%20%22head%20of%20product%22%20OR%20%22product%20lead%22%20OR%20%22chief%20of%20staff%22
  &location=Singapore
  &geoId=102454443
  &f_TPR=r86400
  &sortBy=DD
  &start=0
```

**B. 抓 job_id=4430572342 的 JD 全文**:
```
https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4430572342
```

**C. 給人看的 24h Singapore PM 系列搜尋頁** (瀏覽器用):
```
https://www.linkedin.com/jobs/search/?keywords=(%22product%20manager%22%20OR%20%22product%20director%22%20OR%20%22director%20of%20product%22%20OR%20%22head%20of%20product%22%20OR%20%22product%20lead%22%20OR%20%22chief%20of%20staff%22)&location=Singapore&geoId=102454443&f_TPR=r86400&sortBy=DD
```

### 4.6 ⚠️ 絕對不要用的 URL（會 403 / 失敗）

| URL 樣式 | 為什麼錯 |
|---|---|
| `https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards?decorationId=...` | Voyager 內部 API，**需要 `li_at` + `JSESSIONID` cookie**，沒 cookie 直接 403 "CSRF check failed"。Daniel 親測確認 Guest API 才是正解。**絕對不要推薦 Voyager。** |
| `https://www.linkedin.com/voyager/api/search/hits?decorationId=...&queryId=...` | 同上，Voyager 搜尋端點 |
| `https://api.linkedin.com/v2/...` | 已棄用的舊版 API |
| `https://www.linkedin.com/jobs/api/...` (沒有 `-guest`) | 404，這個路徑不存在 |

### 4.7 ⚠️ 常見組裝錯誤（Daniel 親測踩過）

| 錯誤 | 正確 |
|---|---|
| `start=0, 25, 50, 75` (當 page size=25) | `start=0, 10, 20, 30` (**page size 是 10 不是 25**) |
| `f_TPR=24h` (英文) | `f_TPR=r86400` (秒數, `r` 前綴) |
| `f_TPR=24` (沒前綴) | `f_TPR=r86400` |
| `geoId=Taiwan` (文字) | `geoId=104187078` (純數字) |
| `keywords=product manager` (沒引號) | `keywords="product manager"` (引號包字串) |
| URL 整段裸貼不 encode | 整段 query value 用 `urllib.parse.quote(s, safe="")` |

### 4.8 寫進 Sheet 的 URL 規則

| 用途 | URL | 寫法 |
|---|---|---|
| **E 欄 Job URL（API 版）** | `https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}` | 純文字 (display text 就是 job_id) 或 `=HYPERLINK(URL, job_id)` |
| 不用 UI 版 | `https://www.linkedin.com/jobs/view/{slug}-{job_id}` | ❌ 不要寫這個 |
| 不用 Voyager 版 | `https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}` | ❌ 不要寫這個（也會被當 unstable）|

---

## 5. Time Range 設定（配 3s sleep, 零累積）

| Range | f_TPR 值 | 預設 MAX_PAGES | 預期抓取 | 安全上限 |
|---|---|---|---|---|
| 1h | `r3600` | 1 | 6 | - |
| 24h | `r86400` | **4** | 30-50 | 4-5 |
| 3d | `r259200` | 7 | ~70 | 7 |
| 7d | `r604800` | 15 | ~150 | 15 |
| 14d | `r1209600` | 30 | ~290 | 25-30 |
| 30d | `r2592000` | 25 | ~240 | 20-25 |

每日總配額 ~50 requests（sliding window），跨多 range 須分天。

---

## 6. Google Sheet 寫入規範

### 6.1 目標
- Sheet ID: `1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-Fc42jAZ8`
- 工作表: `SG-Raw` (gid=`1119491672`)
- Service Account: `job-scrape@dark-park-493403-n2.iam.gserviceaccount.com`
- Key: `projects/scrapling-test/.secrets/gsheet-sa.json` (chmod 600)

### 6.2 寫入欄位（11 欄，跳 B + J）

| 欄 | 寫入 | 範例 |
|---|---|---|
| A Status | 固定 `"New"` | `New` |
| B Priority | **留空** | (空) |
| C Added At | 今日 ISO | `2026-08-19` |
| D Source | 固定 `"LinkedIn / Minimax"` | `LinkedIn / Minimax` |
| E Job URL | API 版超連結 (HYPERLINK formula) | `=HYPERLINK("https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4430572342","4430572342")` |
| F Company | 從 list 抓 | `OKX` |
| G Job Title | 從 list 抓 | `Product Director, VIP Products` |
| H JD | 全文，**strip 換行變 inline** | (一長串) |
| I Location | 從 list 抓 | `Singapore, Singapore` |
| J Work Mode | 從 JD 文字 / title parse (regex) | `Remote` / `Hybrid` / `Onsite` (空 = 沒抓到; 2026-08-23 統一沒 hyphen) |
| K Visa | 見 §3 visa 規則 | (text 或 ⚠️ HARD:...) |

### 6.3 H 欄處理
- `re.sub(r"\s+", " ", jd_text).strip()` — 換行 / 多空白壓成單空格
- 視覺上失去排版，但語意零損失
- 完整文字可在 formula bar 看

### 6.4 Dedup
- **用 job_id 比對，不是用 URL 字串**（gspread 讀 HYPERLINK 只回顯示文字）
- Sheet 內已存在的 job_id → 跳過，不重寫

---

## 7. Cross-run 狀態

- `seen_jds.jsonl` — 紀錄已抓 JD 的 job_id / jd_hash / 時間 / title / company
- 用 `load_seen_ids()` 讀 → set of job_id
- 沒 JD 文字的 job 視為「未抓」會被重抓（cache 修正）
- `--reset-seen` 清空

---

## 8. 速查：常用指令

```bash
# 環境
cd projects/scrapling-test && source .venv/bin/activate

# 只抓列表（最快）
python sg_product_jobs.py 24h

# 抓列表 + JD
python sg_product_jobs.py 24h --with-jd

# 抓 + 寫 Sheet
python sg_product_jobs.py 24h --with-jd --to-sheet "https://docs.google.com/spreadsheets/d/1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-Fc42jAZ8/edit?gid=1119491672"

# 跳過 skip 過濾（debug 用）
python sg_product_jobs.py 24h --with-jd --no-skip

# 自訂 skip 詞
python sg_product_jobs.py 24h --with-jd --skip-keywords intern junior assistant

# 強制重抓所有 JD（忽略 seen）
python sg_product_jobs.py 24h --with-jd --refetch

# 清空 seen 紀錄
python sg_product_jobs.py --reset-seen

# 改時間範圍
python sg_product_jobs.py 7d --with-jd
python sg_product_jobs.py 14d --with-jd --max-pages 20
```

---

## 9. 已知地雷

1. **Voyager API 不適合**（要 cookie、會 403），用 Guest API
2. **Page size 是 10 不是 25**（每次 +10 offset）
3. **不要用 URL 字串比對做 dedup**（gspread HYPERLINK 只回顯示文字），用 job_id
4. **JD 抓取要用 `::text` getall**（不是只 p/li/h*/strong/span 內的）才能抓到裸文字
5. **scrape 30d 容易被 429**，sleep 拉到 3s+ 比較穩
6. **同一個 run 內也會有 1-2 個重複 job_id**（LinkedIn 偶爾返回 cross-page 重複），用 set 去重
7. **⚠️ push_to_sheet 一定要帶 gid**：傳裸 sheet ID 沒 `#gid=` 會默默 default 到 `0` (jobs_raw)，污染錯的 tab。`push_to_sheet()` 已加防呆 — 沒帶 gid 會 raise。三種合法用法：
   - 完整 URL: `--to-sheet "https://docs.google.com/spreadsheets/d/<ID>/edit?gid=1119491672#gid=1119491672"`
   - 裸 ID + CLI: `--to-sheet <ID> --gid 1119491672`
   - 程式呼叫: `push_to_sheet(jobs, url, gid=1119491672)` 或用 `SG_RAW_URL` 常數
8. **⚠️ 改 `build_list_url` 簽名要同步所有呼叫端** (2026-08-20): 加 `location/geo_id` 參數時漏改 `fetch_list_page` 函數簽名跟 `crawl_list` 內呼叫，導致 NameError 被 try/except 吃掉、main 看到 0 jobs。**debug 口訣**：crawl_list 拿到 0 jobs 不要直接怪 IP block，先看 log 是不是有 `NameError` 或其他 exception
9. **debug 工具用對** (2026-08-20): 偵測問題用 `scrapling.fetchers.Fetcher` 拿到空 body，但 `curl_cffi.requests` 正常 10 jobs。**永遠用 `cc_requests`** (跟 production 一致) 來測試，避免誤判。scrapling Fetcher 不會維持 session cookies
10. **⚠️ gspread 不會自動擴展 sheet rows** (2026-08-20): sheet max rows 是寫死的（user 可手動縮），寫超過會 `400 exceeds grid limits`。**已加防呆**: `push_to_sheet` 內檢查 `end_row > ws.row_count` 就自動 `ws.add_rows(extra)`
11. **gspread 讀 hyperlink 預設只回顯示文字** (2026-08-20): `cell.value` 或 `get_all_values()` 用 `UNFORMATTED_VALUE` 拿不到 formula。要驗證 hyperlink 是否寫入成功，要用 `valueRenderOption=FORMULA` 透過 raw API 查（gspread 沒內建）。`USER_ENTERED` 寫入是會解 formula 的
12. **手動 copy sheet 會 strip HYPERLINK** (2026-08-20): 從 SG-Raw 用 "select all + paste values only" 複製到 TW-Raw 時，formula 被拔掉只剩純文字 job_id。要保留 hyperlink 要用 "paste with formula"，或寫一次性 script 補
13. **⚠️ 不要假裝換資料來源** (2026-08-21): 之前 user 手動從 SG-Raw 複製 402 筆到 TW-Raw、把 I 欄改成「台灣」就當台灣資料。但實際 job_id 是 SG 的，點開 hyperlink 還是 SG 職缺。**改 I 欄不叫換國家**。要拿真台灣職缺必須從台灣 geoId fetch。已清掉 402 個假台灣
14. **⚠️ 真的 429 累積上限** (2026-08-21): 修了 NameError bug 後又跑 TW 14d (91) + 21d (29) + 30d (34) + SG 測試 = 累積 150+ requests，**LinkedIn 真的回 429**。之前 14:00 推測「配額寬度比預期大」其實是當天還沒到上限。**長期累積後 IP-level block 24hr 真的會發生**。要：1) 跨多 range 分天跑 或 2) cache 命中率要拉高減少 fetch 數
15. **⚠️ 用 `cc_requests.Session` 不是 `cc_requests.get`** (2026-08-21): 每次 `cc_requests.get(...)` 都是新 session 沒 cookies，**容易在多次 request 後被 429**。修法: module 層建 `_cc_session = cc_requests.Session(impersonate="chrome")`，所有 fetch 改用 `_cc_session.get(...)`。瀏覽器測網址正常不代表 Python request 也正常 — Python 沒 cookie/JS 看起來更像 bot

---

## 10. 跑一次會發生的流程

```
1. 讀 seen_jds.jsonl → 已知 job_id set
2. 載入 JD cache: 掃所有 sg_product_jobs_*_jd.json (排除當前 run 將寫的檔) → {job_id: jd_text}
3. GET list page (start=0, 10, 20, 30, ...)
4. dedup list (job_id in set)
5. 對每個 unique job:
   a. 標題跑 skip filter
   b. 命中 → jd_skipped, continue
   c. 不命中 → 優先看 json_cache (跨 run) → cached, copy JD
   d. json_cache miss → 才 fetch
6. 隨機 sleep 3-10s
7. push_to_sheet:
   - 讀 sheet → 解 job_id set
   - 過濾已存在的 job_id
   - 組 11 欄 rows
   - 寫到下一個空白 row
7. append seen_jds.jsonl (新抓的)
8. 存 JSON 檔
```

---

## 11. Jora 來源 (sg.jora.com) — 2026-08-22 新增

### 11.1 基本事實
- **網址**: `https://sg.jora.com` (新加坡分站, Jora 是 Indeed/Seek 集團的 aggregator)
- **無公開 API**, 只能 HTML parse
- **無 cookie/Cloudflare**: 比 LinkedIn/JobStreet 簡單, 不用 `solve_cloudflare`
- **⚠️ Jora SG 9/9/2026 關站**, 關站前能撈多少就撈多少
- **頁面大小**: 15 unique jobs/page (HTML 內每個 job render 兩次, 短 href + 帶 tracking 參數的長 href, 所以 30 個 link 但只有 15 unique hash)

### 11.2 URL 結構

| 用途 | URL | 備註 |
|---|---|---|
| 抓 list (HTML) | `https://sg.jora.com/j?a={Nd}&l={location}&q={keyword}&p={N}` | `a=Nd` 是時間過濾 (1h/24h/3d/7d/14d/21d/30d), `p=N` 是 page |
| 抓 JD (HTML) | `https://sg.jora.com/job/{Title-slug}-{hash}?{params}` | hash 是 32 字 hex, slug 可能含 dash |

時間過濾格式:
- `1h` / `24h` / `3d` / `7d` / `14d` / `21d` / `30d` (跟 LinkedIn `f_TPR=r{seconds}` 完全不同)

### 11.3 Job ID 規則
- LinkedIn: 純數字 (e.g. `4430572342`)
- **Jora: URL 內的 32 字 hex hash** (e.g. `3edbbb646574ed2a0a926fee537b0e7c`)
- 不會跟 LinkedIn 撞 → 同一個 seen_jds.jsonl 可以兩種都記

### 11.4 MAX_PAGES (Jora 2026-08-22 確認)
```
JORA_MAX_PAGES = {
    "1h":  5,
    "24h": 10,
    "3d":  30,
    "7d":  30,
    "14d": 40,
    "21d": 40,
    "30d": 40,
}
```
- Jora 沒像 LinkedIn 末頁 0% 退化的問題, p1-25 都穩定 15 unique
- 每頁 15 unique → coverage: 1d=71% / 3d=55% / 7d=29% / 14d=23% / 21d=18% / 30d=14%
- user 鎖定 2026-08-22:「寧可多撈 不要放過」

### 11.5 Sheet 寫入差異 (vs LinkedIn)
| 欄 | LinkedIn | Jora |
|---|---|---|
| D Source | `LinkedIn / Minimax` | `Jora / Minimax` |
| E URL | `=HYPERLINK(".../jobPosting/4430572342","4430572342")` (顯示 short id) | `=HYPERLINK(".../job/Title-slug-hash?...","...完整 URL...")` (**完整 URL 當 display**, hash 必須在內才能 dedup) |
| F Company | 從 list 抓 | **list 沒公司**, 從 JD 頁 `h1 + *` 元素解 (格式 `Company – Location`) |
| G Title | 從 list 抓 | 從 URL slug 解, 可能不精準, JD 頁的 h1 較準 |

### 11.6 CLI 用法
```bash
# 抓 Jora SG 7d (30 頁 ≈ 50 min)
python sg_product_jobs.py 7d --source jora --max-pages 30 --with-jd --to-sheet "$SG_RAW_URL"

# 抓 Jora SG 1d (15 頁, smaller run)
python sg_product_jobs.py 1d --source jora --with-jd --to-sheet "$SG_RAW_URL"
```

### 11.7 已知地雷
- **403 rate limit**: 短時間大量 request 會被 ban session 幾分鐘, 程式會自動 retry 30/60/90s
- **每頁只有 15 unique** (不是 30): HTML 把每個 job render 兩次, 一個短 href 一個帶 tracking 參數長 href
- **「到底了」判斷**: 之前用 `len(jobs) < 25` (LinkedIn 標準), 改為 `len(new_jobs) < 10` (Jora 15/page 的 heuristic)
- **dedup 依賴完整 URL**: E 欄要寫完整 URL, 不能截斷 80 chars, 否則 hash 被切掉, push_to_sheet 會把已存在的 Jora job 當新資料重寫
- **Jora 沒有 f_TPR 格式**: 跟 LinkedIn `f_TPR=r{seconds}` 完全不同, Jora 用 `a=Nd` 純文字
- **沒 API**: 所有 list / JD 都用 HTML parse, 比 LinkedIn API 慢

---

## 12. JobStreet SG 來源 (sg.jobstreet.com) — 2026-08-22 整合

### 12.1 為什麼用 JobStreet
- LinkedIn 已經穩定, Jora SG 9/9/2026 關站 → 找新 source
- JobStreet SG 有**公開 API + GraphQL**, **不需要 Cloudflare solve**
- HTML 頁面被 Cloudflare 擋 403, 但 API endpoint 不會
- handoff doc: `/Users/huaihsuanhuang/.minimax/v2/assets/2026/08/22/.../jobstreet_api_handoff.md` (另一個 agent 找的, 已獨立驗證 OK)

### 12.2 List API
```
GET https://sg.jobstreet.com/api/jobsearch/v5/search
?siteKey=SG-Main
&keywords={URL-encoded}
&where=Singapore
&worktype=242            # 242=FT, 244=Contract, 243=PT
&daterange=7             # 1/3/7/14/31
&page={N}
&pageSize=20             # max ~100, 200 會 400
```

對應 UI: `https://sg.jobstreet.com/product-manager-jobs/in-Singapore/full-time?daterange=7`

回傳結構:
```json
{
  "data": [...20 jobs...],
  "totalCount": 953,
  "info": {"timeTaken": 11, "source": "JobSearch-sm"},
  "userQueryId": "...",
  "location": {...},
  "searchParams": {...},
  "solMetadata": {...}
}
```

實測 totalCount (2026-08-22, "product manager" + FT + Singapore):
- daterange=1 → 0 (1 天內沒有 FT PM)
- daterange=3 → 384
- daterange=7 → 953
- daterange=14 → 1634
- daterange=31 → 3028

### 12.3 列表欄位 (per job)
- `id` (純數字 e.g. `94145676`) ← **跟 LinkedIn 同型別, dedup 會撞**
- `title`
- `companyName` / `employer.name` / `advertiser.description`
- `employer.companyUrl` ← **這個 HTML 不會被 Cloudflare 擋**
- `locations[].label` / `seoHierarchy[].contextualName`
- `workTypes` (e.g. `["Full time"]`)
- `workArrangements.data[].label.text` (Onsite / Hybrid / Remote — 2026-08-23 統一沒 hyphen) — **比 LinkedIn 準**
- `salaryLabel` (e.g. `$6,500 – $8,500 per month`, 22% 有)
- `listingDate` / `listingDateDisplay`
- `teaser` (部分 JD 摘要, 完整要打 GraphQL)
- `classifications[].classification.description` (e.g. "Marketing & Communications")
- `isFeatured` (廣告 flag)
- `roleId`, `tracking` (base64 內部用, 沒用)

### 12.4 Detail GraphQL
```
POST https://sg.jobstreet.com/graphql
Content-Type: application/json
```
```json
{
  "query": "query getJobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { id title abstract content status isExpired createdAt { dateTimeUtc } updatedAt { dateTimeUtc } expiresAt { dateTimeUtc } advertiser { id name } location { label } workTypes { label } } } }",
  "variables": {"jobId": "94145676"}
}
```

**重要**: 完整 JD 在 `job.content` (HTML), **不是 `description`**。content 用 BeautifulSoup 轉純文字。

回傳 content 範例 (Tech Data Product Manager):
```html
<strong><strong>Job Purpose:</strong></strong><br>
<p>The Product Manager has overall responsibility for achieving the sales and profit targets...</p>
<strong><strong>Responsibilities:</strong></strong><br>
<ul>
 <li>Creation of business plans...</li>
 ...
</ul>
```
BS4 轉純文字後: 1k-5k chars

### 12.5 ⚠️ JobStreet 限制 / 已知地雷
- **HTML 頁面全部 403 Cloudflare managed challenge**: `/job/{slug-id}`, `/product-manager-jobs/...` 都擋
  - 但 API 不會, 抓資料正常
  - **E 欄 URL 只能組構造的** `https://sg.jobstreet.com/job/{title-slug}-{id}` (會 403 但格式對)
  - 公司頁 `/companies/{name-id}` **不會**被擋, 可當公司 URL
- **HTML 頁面無法繞過** (2026-08-22 測試 8 種方法全部失敗):
  1. ❌ curl_cffi chrome impersonate → 403
  2. ❌ 加 referer / 完整 browser header (Sec-Fetch-*) → 403
  3. ❌ Scrapling StealthyFetcher `solve_cloudflare=True` → 卡死 2 分鐘, managed challenge 解不掉
  4. ❌ Playwright (chromium headless, 移除 webdriver flag) → 403, 標題 "Just a moment..."
  5. ❌ Mobile UA (iPhone Safari) → 403
  6. ❌ Googlebot UA → 403
  7. ❌ Wayback Machine (CDX API) → 沒 snapshot
  8. ❌ Google cache → 回的是 interstitial 不是真內容
  9. ❌ Indeed SG 鏡像 (`/viewjob?jk=`) → 401 需要登入
  10. ❌ `lite.jobstreet.com` / `m.sg.jobstreet.com` / `/amp/job/...` → DNS 沒解 / 404 / 403
- **GraphQL `content` 欄位 = HTML 頁面的 JD 本體** (Tech Data 那筆: 3652 chars, 33 li, 6 strong, 1 p, 2 ul, 3 br)
  - 缺的只是 page chrome (apply button / company sidebar / related jobs / reviews)
  - **對個人用途的求職追蹤, GraphQL 完全夠用**, 不需要 HTML 頁
- **API 不支援 Boolean OR**: `keywords=product manager OR product director` 只回 159 (非聯集)
  - 策略: 分次打不同 keyword, 用 `job.id` 去重
- **pageSize 上限 100**: 200 會回 HTTP 400
- **page 1 之間不重複** (驗證過 page 1 vs page 2 0 overlap)
- **GraphQL introspection 禁用**: 沒法用 `__schema` 探索欄位, 用 handoff doc 的固定 query 就好
- **intl 限制**: GraphQL `errors[].message` 給字串, 可拿來 debug
- **robots.txt disallow 範圍**: `/graphql`, `/api/jobsearch/` 都禁, 但個人用途不算; AI bots (GPTBot/CCBot/anthropic-ai) 額外禁 `/companies` + `*/job/`, 不影響我們

### 12.6 壓力測結果 (2026-08-22, curl_cffi impersonate chrome)
- List API 30 reqs 0.3s sleep = 0 fail
- GraphQL 50 reqs 0.3s sleep = 0 fail (~28s)
- GraphQL 200 reqs 0.5s sleep = 0 fail (~156s)
- GraphQL 100 reqs 0.1s sleep (10 req/s) = 0 fail (~37s)
- 並行 5 reqs threadpool = 0.39s 全部完成
- **結論: 保守用 0.5-1s sleep, 3-5 req/s 應該很安全, 不需要 retry/ban 機制**

### 12.7 Sheet 寫入差異
| 欄 | LinkedIn | Jora | JobStreet |
|---|---|---|---|
| D Source | `LinkedIn / Minimax` | `Jora / Minimax` | `JobStreet / Minimax` |
| E URL | `=HYPERLINK(".../jobPosting/{id}","{id}")` | `=HYPERLINK("...完整 Jora URL...","...完整 Jora URL...")` | `=HYPERLINK(".../job/{id}",".../job/{id}")` (純 id, 2026-08-23 從 slug-id 改成純 id, 跟 row 1350 手動測的格式一致) |
| F Company | 從 list 抓 | 從 JD h1+* 抓 | 從 list 的 `companyName` 或 `employer.name` |
| G Title | 從 list 抓 | 從 URL slug 解 | 從 list 抓 |
| I Location | list 給 | 從 JD 抓 | list 的 `locations[0].label` |
| J Work Mode | regex parse | regex parse | `workArrangements` 結構化 (Remote/Hybrid/Onsite) |

### 12.8 ⚠️ Dedup 跨 source 碰撞問題
- LinkedIn job_id: 純數字 (e.g. `4430572342`)
- Jora job_id: 32-char hex (e.g. `3edbbb64...`)
- **JobStreet job_id: 純數字 (e.g. `94145676`) — 會跟 LinkedIn 撞！**
- 修法: 進 seen_jds.jsonl 時 prefix source: `linkedin:4430572342`, `jobstreet:94145676`
- 或: 在 push_to_sheet dedup 用 `(source, job_id)` tuple 而非單一 job_id
- 詳見 RULES.md §13 (待寫)

### 12.9 排序策略
- `sortmode=ListedDate` (預設就用) → 新到舊
- `sortmode=Relevance` → 跟預設一樣, 不太準
- `sortmode=` 空白 → 跟 Relevance 一樣

### 12.10 多 keyword 策略
- 目標: `product manager OR product director OR director of product OR head of product OR product lead OR chief of staff`
- 實作: 5 個 keyword 各自打 list API (各約 50 頁 max), 合併用 `job.id` 去重
- 跨 keyword 重疊率 ~57% (5 kw × 100 = 500 raw → 218 unique)
- 預估最終 unique: 5 kw × 50 頁 × 20 = 5000 raw → ~2200 unique (7d 範圍)

### 12.11 Python 範例 (確認可跑)
```python
from curl_cffi import requests as cc_requests
from bs4 import BeautifulSoup
import re

s = cc_requests.Session(impersonate="chrome")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

# 1) List
r = s.get("https://sg.jobstreet.com/api/jobsearch/v5/search", params={
    "siteKey": "SG-Main", "keywords": "product manager", "where": "Singapore",
    "worktype": "242", "daterange": "7", "page": "1", "pageSize": "20",
}, timeout=30, headers=HEADERS)
data = r.json()["data"]  # 20 jobs

# 2) GraphQL detail
r = s.post("https://sg.jobstreet.com/graphql",
    json={"query": "query getJobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { id title content advertiser { name } } } }",
          "variables": {"jobId": "94145676"}},
    headers={**HEADERS, "Content-Type": "application/json"}, timeout=30)
job = r.json()["data"]["jobDetails"]["job"]

# 3) HTML → text
html = job.get("content") or ""
jd_text = re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
```

---

## 13. Cross-Source Dedup 設計 (2026-08-22 完成)

### 13.1 問題
- LinkedIn / JobStreet 都是純數字 job_id, **會撞**
- 例: LinkedIn job `12345` 跟 JobStreet job `12345` 是不同職缺, 但 dedup set 會誤判
- Jora 32-char hex 不撞

### 13.2 修法 (已實作)
- seen_jds.jsonl 每行加 `source` 欄位 (`"linkedin"` / `"jora"` / `"jobstreet"`)
- 舊記錄沒 source 欄位 → `load_seen_ids` 從 job_id 格式推斷:
  - 32-char hex → "jora"
  - 純數字 → "linkedin" (預設, 因 2026-08-22 之前都是 LinkedIn + Jora)
- `load_seen_ids` 回傳 `set[tuple[source, job_id]]`
- `load_jd_cache_from_jsons` 用 `(source, job_id)` 當 key
- `push_to_sheet.existing_keys` 用 `(source, job_id)` tuple set
  - 從 D 欄解 source ("LinkedIn / Minimax" / "Jora / Minimax" / "JobStreet / Minimax")
  - 從 E 欄解 job_id (LinkedIn digit 或 /jobPosting/\d+ / Jora 32-hex / JobStreet 構造的 slug-id)

### 13.3 影響
- 已有的 1814 筆 seen_jds.jsonl 不用重寫, 自動從格式推斷
- 既有的 1348 筆 sheet 資料不用動, push_to_sheet 新邏輯從 D + E 重新解 (source, job_id) tuple

### 13.4 新 source 加入流程 (以後加新 source 步驟)
1. 確認 source 自己的 job_id 格式 (避免跟現有撞)
2. 進 `parse_*_list_page` 加 `source: "newsrc"` 欄位
3. 進 `enrich_with_jd` dispatch 加 `elif src == "newsrc"`
4. 進 `push_to_sheet` E 欄加 `elif job_source == "newsrc"`
5. 進 CLI `--source` choices 加 "newsrc"
6. 進 `main()` location/sheet_source/crawl dispatch 加分支
7. 進 `load_seen_ids` 的 source 推斷邏輯 (從格式推)

---

## 14. JobStreet SG 整合結果 (2026-08-22)

### 14.1 程式改動
- `sg_product_jobs.py` 新增:
  - 常數: `JOBSTREET_TPR`, `JOBSTREET_MAX_PAGES`, `JOBSTREET_KEYWORDS` (5 個), `JOBSTREET_LOCATION`, `JOBSTREET_LIST_API`, `JOBSTREET_GRAPHQL`, `JOBSTREET_BASE`, `JOBSTREET_WORKTYPE_FT`
  - 函數: `build_jobstreet_list_url`, `parse_jobstreet_list_page`, `fetch_jobstreet_jd`, `crawl_jobstreet_list`
  - 新增第三個 source: `--source {linkedin,jora,jobstreet}`
- D 欄: `"JobStreet / Minimax"`
- E 欄: `https://sg.jobstreet.com/job/{id}` (純 id, 2026-08-23 從 `{title-slug}-{id}` 改成純 id; 雖然 HTML 會 403, 但 user 認為人類讀的話沒差)
- Sheet dedup 改為 (source, job_id) tuple (見 §13)

### 14.2 MAX_PAGES 鎖定 (跟 LinkedIn 一樣)
```
JOBSTREET_MAX_PAGES = {
    "1h":  1, "24h": 4, "3d": 7, "7d": 15, "14d": 30, "21d": 30, "30d": 25
}
```
**50% 軟停**: `crawl_jobstreet_list` 每頁檢查, 若 `len(new_jobs) < 10` (50% of pageSize=20) 或 jobs 空就 break
- JobStreet 頁面資料穩定 20/page, 50% 軟停通常只在最後一頁 (totalCount/20 餘數) 觸發

### 14.3 預期覆蓋 (5 keyword × N 頁 × 20/page + 跨 keyword dedup)
| Range | MAX_PAGES | Raw 抓取 | 預期 Unique | totalCount (pm FT SG) |
|---|---|---|---|---|
| 3d | 7 | 700 | ~350 | 384 |
| 7d | 15 | 1500 | ~600 | 953 |
| 14d | 30 | 3000 | ~1200 | 1634 |
| 21d | 30 | 3000 | ~1300 | 2313 |
| 30d | 25 | 2500 | ~1100 | 3003 |
| **總** | | **10700 raw** | **~4500 unique** | |

(50% 軟停會自動 cover 那些 totalCount < 預期的, 不會硬跑到 max_pages)

### 14.4 CLI 用法
```bash
# 抓 JobStreet SG 7d (15 頁 × 5 kw × 20 = 1500 raw → ~600 unique)
python sg_product_jobs.py 7d --source jobstreet --with-jd --to-sheet "$SG_RAW_URL"

# 自訂 max pages
python sg_product_jobs.py 7d --source jobstreet --max-pages 30 --with-jd --to-sheet "$SG_RAW_URL"

# 一次跑 5 個 range
bash run_all_jobstreet.sh
```

### 14.5 work_mode 處理
- LinkedIn / Jora: 從 JD 文字 regex parse (不準, 30% 命中率)
- **JobStreet: 從 list API 的 `workArrangements.data[].label.text` 直接拿, 結構化, 100% 準**
  - 實測 7d 100 筆: Onsite=86, Hybrid=13, Remote=1 (2026-08-23 統一 "Onsite" 沒 hyphen)
  - 跑 JobStreet 時, J 欄直接用 list 給的 work_mode, 不需要 regex parse

### 14.6 seen_jds.jsonl 變化
- 舊格式 `{job_id, jd_hash, fetched_at, title, company}` (沒 source)
- 新格式 + `source` 欄位
- 1814 筆舊記錄不動, 讀取時從 job_id 格式推斷 source (linkedin/jora)
- 新 JobStreet 寫入時帶 `source: "jobstreet"`

### 14.7 已知小雷
- JobStreet pageSize 上限 100, 超過回 400 (RULES §12.5)
- daterange=1 (1d) 偶爾有 0-1 個 job (LinkedIn 1h 沒有對應)
- 構造的 /job/{slug-id} URL HTML 會 403 (RULES §12.5), 但 E 欄照樣寫完整 URL
- `push_to_sheet` dedup 多了一個 D 欄解析, 比之前慢一點 (~0.1s)

### 14.8 JobStreet 跑一次會發生的流程 (2026-08-23 跑完驗證)
```
1. 讀 seen_jds.jsonl → 已知 (source, job_id) set
2. 載入 JD cache: 掃所有 *_product_jobs_*_jd.json → {(source, job_id): jd_text}
3. 對 5 個 keyword 各跑 list API (product manager / director / head of product / product lead / director of product):
   a. 對每個 keyword 從 page 1 跑到 max_pages (含 50% 軟停)
   b. 跨 keyword 用 job.id 去重
4. 對每個 unique job 抓 GraphQL detail (HTML content → BS4 → 純文字)
5. 跳過 skip 標題, 命中 json_cache 不重抓
6. 寫到 SG-Raw, D 欄 "JobStreet / Minimax", E 欄 構造 URL
```

### 14.9 JobStreet 第一次完整跑結果 (2026-08-23)
| Range | Crawled | Skip | Dedup | Fetched | Wrote | Sheet Rows |
|---|---|---|---|---|---|---|
| 7d (first) | 329 | 106 | 20 | 223 | **205** | 1370-1574 |
| 3d | 165 | 45 | 99 | 21 | **21** | 1575-1595 |
| 7d (re-run) | 328 | 106 | 224 | 0 | **0** | (cached) |
| 14d | 630 | 210 | 218 | 204 | **204** | 1596-1799 |
| 21d | 627 | 230 | 300 | 99 | **99** | 1800-1898 |
| 30d | 550 | 178 | 304 | 70 | **70** | 1899-1968 |
| **總** | **2629** | **875** | **1165** | **617** | **599** | |

- 加上 smoke test 20 筆 → Sheet 累計 **619 JobStreet**
- 全部 0 個 fetch error
- 跑完 5 個 range ~76 分鐘 (00:59 → 02:15)

### 14.10 JobStreet visa HARD hits (2026-08-23)
- SINGAUTO PTE LTD | Head of IT and Innovation | `Permanent Residents only`
- SmartX Technology Limited | Partner Business Manager, Southeast | `Must be a Singapore citizen`
- SmartX Technology Limited | Partner Business Director, Pan-ASEA | `Must be a Singapore citizen`

### 14.11 JobStreet work mode (結構化, 100% 準)
- Onsite: 560 (90.5%) — 2026-08-23 從 "On-site" 統一改成 "Onsite" (560 筆 backfill)
- Hybrid: 59 (9.5%)
- Remote: 5 (0.8%)
- (比 LinkedIn 用 regex parse 準得多, LinkedIn 那邊 J 欄常空)

### 14.12 E 欄 URL 格式改: `/job/{slug-id}` → `/job/{id}` (2026-08-23)
- **舊格式**: `https://sg.jobstreet.com/job/product-manager-storage-devices-94145676`
- **新格式**: `https://sg.jobstreet.com/job/94145676`
- **原因**: Cloudflare 一視同仁擋 HTML 頁 (有 slug 或沒 slug 都 403), user 認為人類讀的話純 id 比較簡潔
- **做法**:
  1. 改 `push_to_sheet` 的 `elif job_source == "jobstreet":` 區塊 (1 行改, 拿掉 slug 構造)
  2. Backfill 618 筆現有 sheet 資料 (rows 1351-1968), 用 batch_update 一次寫完
  3. 從舊 URL regex `-(\d+)$` 解出 job_id, 構造新 formula
- **驗證**: 618/618 全部 format 正確
- **行 1350** 之前 user 手動先改一筆測試, 確認 OK 後才做全 backfill
- **可達性沒改善**: 純 id 跟帶 slug 一樣 403 (user 知道, 接受)

### 14.13 J 欄 work mode 統一: "On-site" → "Onsite" (2026-08-23)
- **舊值**: `On-site` (有 hyphen) — JobStreet API 直接吐這個, LinkedIn/Jora regex 也吐這個
- **新值**: `Onsite` (沒 hyphen) — user 指定統一格式
- **改動位置** (5 處, 都在 `extract_work_mode` 跟 `parse_jobstreet_list_page`):
  - `_norm()` helper (line 471-475)
  - 2c "WORK OPTION" direct return (line 500-501)
  - 中文 cn_patterns "现场..." (line 508)
  - fallback pattern (line 518)
  - JobStreet list parser normalize: `wm.replace("On-site", "Onsite")` (line 1135-1136)
- **Backfill**: 560 筆 J 欄 `On-site` → `Onsite` (rows 2-1968, 用 batch_update 一次寫完)
- **驗證**: 0 個 `On-site` 殘留, 560 個 `Onsite` (匹配)
- **未來新規則**: 所有 work mode 值都用 `Onsite` / `Hybrid` / `Remote` (沒 hyphen)
