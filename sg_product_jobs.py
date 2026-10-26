"""
sg_product_jobs — 多源職缺爬蟲 + Google Sheet 同步

支援的 source:
  - linkedin:  /jobs-guest/jobs/api/...  (Guest API, 不需 cookie)
  - jobstreet: sg.jobstreet.com  (公開 API + GraphQL)
  - cake:      www.cake.me  (API search + public detail URL, 2026-08-30)

DEPRECATED 2026-09-09: jora (sg.jora.com) 已關站, 從 active crawling code 移除。
back-compat 保留: JORA_BASE 常數、`build_e_formula("jora", ...)` 分支、
`parse_sheet_row_to_key` 的 "Jora / Minimax" + 32-hex URL 解析, 讓既有 ~885 筆 sheet rows
跟 seen_jds.jsonl 仍能被 dedup 邏輯識別 (參 RULES.md §13)。

Single source of truth: RULES.md (4 種 URL, MAX_PAGES, skip list, sheet 11 欄, dedup, visa)
"""

__version__ = (
    "1.4.0"  # 2026-10-26: unified single-line release (5 sources + skip filter v8.5 + 429 retry + 3-phase sheet write)
)

# 原始 module 註解保留:
# LinkedIn Guest API — 新加坡 Product 系列職缺
# **不需要 cookie**, 純 HTTP
#
# 特色:
#   - 隨機 sleep 3-10s 模擬人類節奏
#   - 可選 --with-jd 加抓職缺全文 (JD)
#   - 可選 --to-sheet 把結果寫到 Google Sheet
#   - 自動用 job_id 去重跨頁 + 跨 run
#   - 配額友善 (sleep + MAX_PAGES)
#
# 環境: projects/scrapling-test/.venv
# 執行:
#   python sg_product_jobs.py                          # 只抓列表 (預設 Singapore)
#   python sg_product_jobs.py --with-jd                # 抓列表 + 全文
#   python sg_product_jobs.py --with-jd --to-sheet <url>  # 抓完直接寫到 Sheet
#   python sg_product_jobs.py 14d --with-jd            # 換 time range
#   python sg_product_jobs.py 7d --with-jd --location Taiwan  # 換國家 (preset)

import argparse
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

from bs4 import BeautifulSoup
from curl_cffi import requests as cc_requests
from scrapling.parser import Adaptor

# 全域 session: 維持 cookies 跟 connection pool, 降低被 LinkedIn rate limit 觸發 429 的機率
_cc_session = cc_requests.Session(impersonate="chrome")


# ─────────────────────────────────────────────────────────────
# 環境變數讀取 (2026-08-23 新增, 讓別人 fork repo 自己客製化)
# 設定方式: 從 .env.example 複製成 .env, 填值; 或直接 export 環境變數
# 沒設會 fallback 到下面 hardcoded 預設值 (原開發者自己的設定)
# ─────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv

    load_dotenv()  # 自動讀 .env (沒這個檔也不會 error)
except ImportError:
    pass  # 沒裝 python-dotenv 也沒關係, 用實際 env 變數

# 預設值 (fail-closed: 留空代表 user 沒設, 寫入/讀取工具必須報 CONFIG_MISSING)
SHEET_SA_KEY = os.getenv("GSPREAD_SA_KEY_PATH", ".secrets/gsheet-sa.json")
SHEET_ID_OVERRIDE = os.getenv("SHEET_ID", "")  # 留空 → SG_RAW_SHEET_ID="" → 寫入/讀取 fail-closed
SHEET_GID_OVERRIDE = os.getenv("SHEET_GID", "")  # 留空 → SG_RAW_GID=0 → 寫入/讀取 fail-closed
JOBSTREET_KEYWORDS_OVERRIDE = os.getenv("JOBSTREET_KEYWORDS", "")  # 留空 = 用預設 5 kw
# 例: JOBSTREET_KEYWORDS="product manager,product director,head of product"
CAKE_KEYWORDS_OVERRIDE = os.getenv("CAKE_KEYWORDS", "")  # 留空 = 用預設 9 kw
# 例: CAKE_KEYWORDS="product manager,產品經理,product director"


# ─────────────────────────────────────────────────────────────
# 篩選條件
# ─────────────────────────────────────────────────────────────
KEYWORDS = (
    '"product manager" OR "product director" OR "director of product" '
    'OR "head of product" OR "product lead" OR "chief of staff"'
)
GEO_ID = "102454443"  # Singapore (default; 跑其他國家用 --location/--geo-id 覆寫)
LOCATION = "Singapore"  # 對應 GEO_ID 的顯示文字
# 常用其他 geoId (驗證過)
KNOWN_GEO_IDS = {
    "Singapore": ("102454443", "Singapore"),
    "Taiwan": ("104187078", "Taiwan"),
    "Hong Kong": ("105015875", "Hong Kong"),  # 待驗證
    "Japan": ("105080838", "Japan"),  # 待驗證
    "Shanghai": ("107388191", "Shanghai"),  # 中國城市, 30,000+ jobs
}
# 不放 f_WT → onsite/remote/hybrid 全收
PAGE_SIZE = 10  # Guest API 實際 page size (不是 25)

# time range 預設值 + 各 range 的 MAX_PAGES 建議
TIME_RANGES = {
    "1h": ("r3600", 1),
    "24h": ("r86400", 4),
    "3d": ("r259200", 7),
    "7d": ("r604800", 15),
    "14d": ("r1209600", 30),
    "21d": ("r1814400", 30),  # 3 週
    "30d": ("r2592000", 25),
}
# JORA_BASE — DEPRECATED 2026-09-09: Jora SG 關站
# 只保留給 `build_e_formula("jora", ...)` back-compat 分支用 (讓既有 ~885 筆 sheet rows 的 E 欄
# formula 仍能被 round-trip 解析)
JORA_BASE = "https://sg.jora.com"

# JobStreet (sg.jobstreet.com) — 2026-08-22 整合
# 用 /api/jobsearch/v5/search 抓 list + /graphql 抓 JD content
# HTML 頁 100% Cloudflare blocked, 走 GraphQL 完全 OK (詳見 RULES.md §12.5)
JOBSTREET_TPR = {
    "1h": "1",
    "24h": "1",
    "3d": "3",
    "7d": "7",
    "14d": "14",
    "21d": "21",
    "30d": "30",
}
# MAX_PAGES 跟 LinkedIn 一樣 (邏輯都跟 LinkedIn 一樣), 50% 軟停由 crawl_jobstreet_list 跑時判斷
# 預期覆蓋 (product manager + FT + 5 keyword + dedup):
# 1d=1 / 3d=7*20=140 raw → ~80 unique / 7d=15*20=300 → ~200 / 14d=30*20=600 → ~400 / 30d=25*20=500 → ~350
# 7d 的 totalCount 是 953, 5 keyword × 15 page × 20 = 1500 raw, 預期 unique ~600
JOBSTREET_MAX_PAGES = {
    "1h": 1,
    "24h": 4,
    "3d": 7,
    "7d": 15,
    "14d": 30,
    "21d": 30,
    "30d": 25,
}
# 可被 JOBSTREET_KEYWORDS env var 覆寫 (見上面 env 讀取區塊)
# 例: JOBSTREET_KEYWORDS="product manager,product director,head of product"
if JOBSTREET_KEYWORDS_OVERRIDE:
    JOBSTREET_KEYWORDS = [k.strip() for k in JOBSTREET_KEYWORDS_OVERRIDE.split(",") if k.strip()]
else:
    JOBSTREET_KEYWORDS = [
        "product manager",
        "product director",
        "director of product",
        "head of product",
        "product lead",
    ]
JOBSTREET_LOCATION = "Singapore"
JOBSTREET_LIST_API = "https://sg.jobstreet.com/api/jobsearch/v5/search"
JOBSTREET_GRAPHQL = "https://sg.jobstreet.com/graphql"
JOBSTREET_BASE = "https://sg.jobstreet.com"
JOBSTREET_WORKTYPE_FT = "242"

# Cake (www.cake.me) — 2026-08-30 整合
# Search API 是 POST JSON; list response 內就帶完整 JD description, detail URL 可由 page.path + path 組出
CAKE_API_BASE = "https://api.cake.me/api/client/v2"
CAKE_WEB_BASE = "https://www.cake.me"
CAKE_LIST_API = f"{CAKE_API_BASE}/jobs/search"
CAKE_FACET_API = f"{CAKE_API_BASE}/jobs/facet-search"
CAKE_SUGGESTION_API = f"{CAKE_API_BASE}/jobs/query-suggestion/search"
CAKE_DETAIL_PAGE_URL = f"{CAKE_WEB_BASE}/companies/{{page_path}}/jobs/{{job_path}}"
CAKE_JOB_SOURCE = ["cake", "external"]
CAKE_JOB_TYPES = ["full_time"]
CAKE_SENIORITY_LEVELS = ["mid_senior_level", "executive", "director"]
CAKE_LOCATIONS = [
    "香港",
    "Singapore",
    "United States",
    "Taipei City",
    "China",
    "台北市, 台灣",
    "新北市, 台灣",
    "New Taipei City",
]
CAKE_PAGE_SIZE = 10
# P1-03: 預設 sort_by="latest" (popularity 不能證明 ranged coverage COMPLETE)
CAKE_SORT_BY = os.getenv("CAKE_SORT_BY", "latest")
CAKE_LOCATION_SCOPE = "Global"
CAKE_SHEET_SOURCE_LABEL = "Cake / Minimax"
if CAKE_KEYWORDS_OVERRIDE:
    CAKE_KEYWORDS = [k.strip() for k in CAKE_KEYWORDS_OVERRIDE.split(",") if k.strip()]
else:
    CAKE_KEYWORDS = [
        "product manager",
        "product director",
        "director of product",
        "head of product",
        "product lead",
        "產品經理",
        "產品總監",
        "產品主管",
        "PM",
    ]
# Cake API 本身沒有捕捉到穩定的 time filter；這裡仍沿用 range→max_pages 的節流方式，
# 只是 page budget，不是時間窗。client-side 會用 content_updated_at 過濾 (見 crawl_cake_list)。
# 14d/21d/30d 從 ONEZEROFOUR_MAX_PAGES 對齊降一階 (cake server 對高 page 429 敏感, 2026-08-30 實測)
CAKE_MAX_PAGES = {
    "1h": 1,
    "24h": 4,
    "3d": 7,
    "7d": 15,
    "14d": 15,
    "21d": 20,
    "30d": 25,
}
# Client-side time filter (content_updated_at 對 cutoff 過濾)
# Repair9 P1-02: 1h 改 1 hour (不是 1 day); 24h/3d/7d/14d/21d/30d 維持 days
# 注意: content_updated_at 精度是秒級 (ISO 8601 UTC), 但 Cake API 沒 h/m 級的時間窗 server filter
# 所以 client-side 仍然要算實際 hours/days 對 content_updated_at 過濾
CAKE_TIME_FILTER = {
    "1h": ("hours", 1),
    "24h": ("days", 1),
    "3d": ("days", 3),
    "7d": ("days", 7),
    "14d": ("days", 14),
    "21d": ("days", 21),
    "30d": ("days", 30),
}

# 104 (www.104.com.tw) — 2026-08-29 整合 (A 階段: 從 smoke_104.py 搬進主流程)
# 半公開 API, 沒 Cloudflare, 純 Referer + User-Agent header 就通
# 8 keyword × MAX_PAGES 平行 (8 workers), detail API 2 階段抓完整 JD
# RULES.md §15 完整設計文檔
ONEZEROFOUR_LIST_API = "https://www.104.com.tw/jobs/search/api/jobs"
ONEZEROFOUR_DETAIL_API = "https://www.104.com.tw/job/ajax/content/{slug}"  # {slug} placeholder
ONEZEROFOUR_BASE_URL = "https://www.104.com.tw"
ONEZEROFOUR_AREAS = "6001001000,6001002000"  # 台北+新北 (硬寫, 不開放 CLI 改)
# isnew 合法值: 0/3/7/14/30 (其他 400, 含 21, RULES §15.7)
ONEZEROFOUR_TPR = {
    "1h": 0,  # 退化: 1h 沒對應合法值, 用 0
    "24h": 0,
    "3d": 3,
    "7d": 7,
    "14d": 14,
    "21d": 30,  # 退化: 21 會 400, 用 30
    "30d": 30,
}
# MAX_PAGES 跟 LinkedIn/JobStreet 對齊 (邏輯統一); 30d 額外加 50 涵蓋
ONEZEROFOUR_MAX_PAGES = {
    "1h": 1,
    "24h": 4,
    "3d": 7,
    "7d": 15,
    "14d": 30,
    "21d": 30,
    "30d": 50,  # 30d 用 50 (B 階段實測, 涵蓋 ~14%)
}
# 可被 ONEZEROFOUR_KEYWORDS env var 覆寫 (跟 JobStreet 一樣設計)
if ONEZEROFOUR_KEYWORDS_OVERRIDE := os.getenv("ONEZEROFOUR_KEYWORDS", ""):
    ONEZEROFOUR_KEYWORDS = [k.strip() for k in ONEZEROFOUR_KEYWORDS_OVERRIDE.split(",") if k.strip()]
else:
    ONEZEROFOUR_KEYWORDS = [
        "Product Manager",
        "Product Director",
        "Director of Product",
        "Head of product",
        "Product Lead",
        "產品經理",
        "產品總監",
        "產品主管",
        "PM",
    ]
ONEZEROFOUR_LOCATION = "Taiwan"  # 104 只抓台灣, 跟 LinkedIn/Jora/JobStreet 限定 SG 不一樣
ONEZEROFOUR_SHEET_SOURCE_LABEL = "104 / Minimax"
# 104/Cake 寫到 TW-Raw。Repair10 canonical default gid=764063873。
# Plugin vNext 可顯式提供 TW_RAW_GID；未提供時仍精確維持 canonical default。
TW_RAW_GID_OVERRIDE = os.getenv("TW_RAW_GID", "").strip()
if TW_RAW_GID_OVERRIDE and not TW_RAW_GID_OVERRIDE.isdigit():
    raise ValueError("TW_RAW_GID must be a numeric worksheet gid")
ONEZEROFOUR_TW_RAW_GID = int(TW_RAW_GID_OVERRIDE) if TW_RAW_GID_OVERRIDE else 764063873
# P1-04 (Repair9 v2 HPM): Cake 是 Taiwan-intake, 一律寫到 TW-Raw
# 跟 104 共用同一個 gid; 實際 Location 仍由 Cake API 提供 (Taipei/Singapore/California/etc)
CAKE_TW_RAW_GID = ONEZEROFOUR_TW_RAW_GID

DEFAULT_TPR = "24h"

# 隨機 sleep 區間 (人類節奏)
SLEEP_MIN = 3.0
SLEEP_MAX = 10.0

# 跨 run 的「已抓過 JD」記錄檔
#
# 這是 single source of truth: 所有執行 context (plugin runtime / working copy)
# 必須讀寫同一份檔案, 否則同一職缺會被重抓並重複寫入 Sheet。
# 預設是相對路徑 (跟執行時的工作目錄), 跨 context 執行時用
# JOBS_SCRAPER_SEEN_FILE 指定絕對路徑, 不要各自維護一份。
SEEN_FILE = os.environ.get("JOBS_SCRAPER_SEEN_FILE", "seen_jds.jsonl")
TZ_LOCAL = timezone(timedelta(hours=7))  # GMT+7

# VISA / SPONSORSHIP 偵測 (三層級)
# 註：先比 SOFT，再比 HARD，最後比 POSITIVE (第一個命中優先)
VISA_PATTERNS = {
    "HARD": [
        # English — 不提供 / 不能 sponsor
        r"will\s+not\s+(?:provide\s+)?sponsorship",
        r"will\s+not\s+sponsor",
        r"cannot\s+(?:provide\s+)?sponsorship",
        r"cannot\s+sponsor",
        r"do(?:es)?\s+not\s+(?:provide\s+)?sponsorship",
        r"do(?:es)?\s+not\s+sponsor",
        r"sponsorship\s+(?:is\s+)?not\s+(?:available|provided|offered)",
        r"no\s+sponsorship\s+(?:available|provided|offered)",
        # English — 身份限制 (硬性)
        r"PR\s+only",
        r"permanent\s+residents?\s+only",
        r"citizens?\s+and\s+PRs?\s+only",
        r"citizens?\s+only",
        r"Singapore(?:n)?\s+(?:citizens?|PRs?)(?:\s+and\s+(?:citizens?|PRs?))?\s+only",
        r"must\s+be\s+(?:a\s+)?(?:Singapore(?:n)?\s+)?(?:citizen|PR)",
        r"already\s+authorized\s+to\s+work\s+in\s+Singapore",
        # Chinese (硬性)
        r"不提供\s*簽證",
        r"不(?:提|辦|處)理\s*(?:簽證|工作證|EP|visa)",
        r"僅限\s*(?:新加坡|本地)?\s*(?:公民|PR|永久居民)",
        r"公民(?:及|和|與)?\s*PR\s*優先",
        r"(?:必須|需|須)\s*為?\s*(?:新加坡)?\s*(?:公民|PR)",
        # Taiwan (硬性)
        r"Taiwan(?:ese)?\s+(?:citizens?|nationals?|PRs?)\s+only",
        r"must\s+be\s+(?:a\s+)?Taiwan(?:ese)?\s+(?:citizen|national)",
        r"僅限\s*(?:台灣|本地)?\s*(?:公民|國民|永久居民)",
        r"(?:必須|需|須)\s*為?\s*(?:台灣)?\s*(?:公民|國民)",
        # China / Shanghai (硬性)
        r"Chinese\s+(?:citizens?|nationals?)\s+only",
        r"PRC\s+(?:citizens?|nationals?)\s+only",
        r"must\s+be\s+(?:a\s+)?(?:Chinese|PRC)\s+(?:citizen|national)",
        r"僅限\s*(?:中國|大陆|本地|滬)?\s*(?:公民|國民|戶籍|戶口)",
        r"(?:必須|需|須)\s*為?\s*(?:中國|大陸|本地)?\s*(?:公民|國民|戶籍|上海)",
        r"上海(?:戶籍|戶口)\s*(?:優先|優先考慮|居民)",
    ],
    "SOFT": [
        # English — 優先現有工作權 / 不要求 sponsor / etc.
        r"prioritis(?:e|ing)\s+applicants?\s+who\s+have\s+(?:a\s+)?(?:current\s+)?(?:right|authorization)\s+to\s+work",
        r"do(?:es)?\s+not\s+require\s+(?:\w+\s+)?sponsorship",
        r"do(?:es)?\s+not\s+(?:provide|require)\s+(?:\w+\s+)?sponsor",
        r"existing\s+(?:work\s+)?authorisation",
        r"existing\s+(?:work\s+)?authorization",
        r"must\s+(?:already\s+)?(?:be\s+)?(?:legally\s+)?(?:authoriz|authoris)(?:ed|ation)?\s+to\s+work",
        r"candidates?\s+with\s+(?:valid\s+)?work\s+(?:visa|permit|pass|right)",
        r"新加坡(?:人|公民|PR)優先",
        r"不(?:需|用)要?\s*(?:提供|辦理)?\s*(?:簽證|visa|工作證)",
        r"不(?:能|可以)\s*(?:提供|辦理)\s*(?:簽證|visa|工作證|EP)",
        r"台灣(?:人|公民)?\s*優先",
        # China / Shanghai
        r"Chinese\s+(?:citizens?|nationals?)\s+preferred",
        r"(?:大陸|中国|大陆)\s*(?:人|公民|國民)?\s*(?:優先|优先)",
        r"本地人?\s*(?:優先|优先)",
        r"中國(?:人|公民|國民)\s*(?:優先|优先)",
    ],
    "POSITIVE": [
        # English — 明確說會 sponsor
        r"visa\s+sponsorship\s+(?:is\s+)?(?:available|provided|offered)",
        r"sponsorship\s+(?:is\s+)?available",
        r"we\s+(?:do\s+)?sponsor",
        r"we\s+provide\s+(?:visa\s+)?sponsorship",
        r"會(?:提供|辦理)\s*(?:簽證|visa|工作證|EP)",
    ],
}

DEFAULT_SHEET_SOURCE = "LinkedIn / Minimax"

# 預設 Google Sheet 目標 (fail-closed: 沒設 env 時 Sheet ID/GID 留空,
# 寫入/讀取工具必須回報 CONFIG_MISSING 結構化錯誤, 不可 fallback 到 author 的 Sheet)
# 可被 SHEET_ID / SHEET_GID env var 覆寫 (見上面 env 讀取區塊)
SG_RAW_GID = int(SHEET_GID_OVERRIDE) if SHEET_GID_OVERRIDE.isdigit() else 0
SG_RAW_SHEET_ID = SHEET_ID_OVERRIDE or ""
SG_RAW_URL = f"https://docs.google.com/spreadsheets/d/{SG_RAW_SHEET_ID}/edit?gid={SG_RAW_GID}#gid={SG_RAW_GID}"
# China-Raw (Shanghai 用的, user 2026-08-21 建)
CHINA_RAW_GID = 488353479
CHINA_RAW_URL = f"https://docs.google.com/spreadsheets/d/{SG_RAW_SHEET_ID}/edit?gid={CHINA_RAW_GID}#gid={CHINA_RAW_GID}"

# JD 抓取前的標題關鍵字過濾 (省配額) — v8.5 Bounded Repair
# 設計重點 (per SKIP_FILTER_V8_5_BOUNDED_REPAIR_DISPATCH):
#   1) 移除「senior marker 可全域救回 skip hit」的錯誤
#   2) 加入精準 target-role guard
#   3) 將 sales/quality/support/test 從裸 contextual token 改為 role-shaped exclusion
#   4) 移除 contract/temp/temporary 的 unconditional hard skip
#   5) 收窄 assistant/specialist 例外條件
#   6) 保持 104 source-specific 行為
# 結構: 5 個 semantic groups (TARGET / ENTRY / HARD_NON_TARGET / CONTEXTUAL / SPECIALIST),
#       取代 v8.4 的單一 DEFAULT_SKIP_KEYWORDS + 全域 senior rescue
# DEFAULT_SKIP_KEYWORDS 仍保留為 v8.4 內容, 給 `enrich_with_jd` 的 `skip_pat` 參數做
#   backward-compat 佔位 (v8.5 內部不再用); 真正的 skip 邏輯由 5 個 semantic groups 驅動。

# v8.5 DEPRECATED: kept for backward compat with `enrich_with_jd` calling pattern.
# v8.5 internal logic uses semantic groups below.
DEFAULT_SKIP_KEYWORDS = [
    # 保留 v8.4 內容 (DEPRECATED, not used by v8.5 match_skip_reason)
    "intern",
    "internship",
    "trainee",
    "graduate",
    "grad",
    "entry",
    "entry level",
    "entry-level",
    "junior",
    "jr",
    "assistant",
    "support",
    "coordinator",
    "administrator",
    "clerk",
    "secretary",
    "product marketing",
    "product analyst",
    "product designer",
    "product designers",
    "product validation",
    "product certification",
    "qa",
    "test",
    "quality assurance",
    "quality",
    "account manager",
    "account managers",
    "key account manager",
    "key account managers",
    "client manager",
    "client managers",
    "relationship manager",
    "relationship managers",
    "account executive",
    "sales",
    "business development",
    "accounting",
    "accountant",
    "accountants",
    "audit",
    "auditor",
    "auditors",
    "human resources",
    "recruiting",
    "recruiter",
    "recruiters",
    "procurement",
    "purchasing",
    "purchaser",
    "purchasers",
    "buyer",
    "buyers",
    "merchandiser",
    "merchandisers",
    "specialist",
    "temp",
    "temporary",
    "contract",
]

# Senior whitelist: 保留給 narrow ambiguity rules (assistant / specialist) 使用
# 2026-08-29 v8.4 補上中文 senior 詞, v8.5 繼續沿用 (但不再全域救回 skip hit)
# 中文詞是 substring match, 不會誤觸英文 title (英文不會含中文字)
SENIOR_MARKERS_ANYWHERE = [
    # English
    "avp",
    "vp",
    "vice president",
    "director",
    "head",
    "chief",
    "senior",
    "staff",
    "principal",
    "lead",
    "managing director",
    "general manager",
    "president",
    "ceo",
    "cfo",
    "cto",
    "cmo",
    "coo",
    "chairman",
    # 中文 (台灣職缺常用 senior 頭銜)
    "高級",
    "資深",
    "主任",
    "副理",
    "協理",
    "襄理",
    "處長",
    "經理",
    "總監",
    "副總",
    "副店長",
    "店長",
]
# 給 assistant narrow rule 用的 senior 緊鄰詞集合
SENIOR_FOLLOWERS = [
    "vice president",
    "director",
    "general manager",
    "managing director",
    "president",
    "ceo",
    "cfo",
    "cto",
    "cmo",
    "coo",
    "chairman",
    "head",
    "secretary-general",
]

# v8.5 新增: TARGET_ROLE_PATTERNS — KEEP (overrides everything below)
# 命中就 return None, 不管 title 內含任何 skip 詞
# 例: "Product Manager, Sales Platform" 內含 "Sales" 但被這個 guard 救回
#
# v8.5 Repair2 (P1-02): VP / Vice President / Chief Product Officer 之前沒有 negative
# lookahead 排除 hard non-target Product-* suffix (marketing/design/analyst/validation/
# certification/support), 導致 "VP of Product Marketing" 被誤判 KEEP。
# 用 _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD 集中定義, 5 個 leadership pattern 一致套用。
#
# v8.5 Repair3 (P1-01): Product-* family separator 改用共享 fragment
#   _V85_PRODUCT_FAMILY_SEP, 同時支援 whitespace + ASCII hyphen + en-dash (U+2013) +
#   non-breaking hyphen (U+2011)。"Product-Marketing" / "Product–Marketing" 等
#   typography 變體都會被視為同 family, 不再只認 whitespace。
_V85_PRODUCT_FAMILY_SEP = r"[\s\u2011\u2013\-]+"
_V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD = (
    r"(?!" + _V85_PRODUCT_FAMILY_SEP + r"(?:marketing|design|analyst|validation|certification|support))"
)
TARGET_ROLE_PATTERNS = [
    # === English ===
    # 標準 Product Manager 變體
    r"product\s+manager",
    r"product\s+lead",
    r"product\s+owner",
    r"product\s+director",
    # Head of Product / Director of Product (negative lookahead 排除 marketing/design/analyst
    # 等 "Director of Product Marketing" 這種 lookalike 漏到 hard non-target)
    r"head\s+of\s+product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
    r"director\s+of\s+product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
    # v8.5 Repair2: VP / Vice President / Chief Product Officer 補上同樣的 negative lookahead
    r"vp[,]?\s*(of\s+)?product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
    r"vice\s+president[,]?\s*(of\s+)?product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
    r"chief\s+product\s+officer" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
    # 修飾前綴的 PM
    r"technical\s+product\s+manager",
    r"ai\s+product\s+manager",
    r"senior\s+product\s+manager",
    r"principal\s+product\s+manager",
    r"lead\s+product\s+manager",
    r"group\s+product\s+manager",
    r"head\s+of\s+ai",
    r"director\s+of\s+ai",
    # === 中文 (substring match) ===
    r"產品經理",
    r"產品主管",
    r"產品總監",
    r"產品負責人",
    r"產品長",
]


# v8.5 編譯 helper: 英文用 word-boundary, 中文用 substring
def _v85_compile_mixed(patterns: list[str]) -> re.Pattern:
    """v8.5: 對 pattern list 編譯單一 regex, 自動分流英文/中文。
    英文 (ASCII): 用 (?<![a-z])(?![a-z]) word-boundary 防 substring 誤判
    中文 (CJK): substring match 即可 (中文字無 word boundary 概念)

    注意: 不呼叫 re.escape() — 我們要保留 regex syntax (e.g. \s+, \b, |, ?)
    這些是 patterns 本身寫的 regex, 不是 literal strings。

    v8.5 Repair7 (P1-06 P0 fix): CJK detection 改成檢查實際 CJK ideograph range
    (U+3400-U+4DBF, U+4E00-U+9FFF, U+3000-U+303F, U+FF00-U+FFEF), 不是單純 ord(c) >= 128。
    否則像 \u2012 (FIGURE DASH) 或 \u2011 (NON-BREAKING HYPHEN) 這種非 CJK 的非 ASCII
    字元, 會把整個 pattern list 誤判成 zh, 導致 word-boundary wrap 沒套用,
    "Quality Engineer" 在 "Quality Engineering" 內 substring 誤觸。
    """
    import re as _re_cjk

    # CJK ideograph range: U+4E00-U+9FFF (basic), U+3400-U+4DBF (ext A), U+3000-U+303F (punctuation),
    # U+FF00-U+FFEF (fullwidth). 排除 \u2000-\u206F (general punctuation) 和 \u2010-\u2027 (hyphens/dashes).
    _CJK_RE = _re_cjk.compile(r"[\u3000-\u303f\u3400-\u4dbf\u4e00-\u9fff\uff00-\uffef]")

    def _has_cjk(s: str) -> bool:
        return _CJK_RE.search(s) is not None

    en_patterns, zh_patterns = [], []
    for p in patterns:
        if _has_cjk(p):
            zh_patterns.append(p)
        else:
            en_patterns.append(p)
    if en_patterns and zh_patterns:
        en_pat = r"(?<![a-z])(?:" + "|".join(en_patterns) + r")(?![a-z])"
        zh_pat = "(?:" + "|".join(zh_patterns) + ")"
        full = en_pat + "|" + zh_pat
    elif en_patterns:
        full = r"(?<![a-z])(?:" + "|".join(en_patterns) + r")(?![a-z])"
    else:
        full = "(?:" + "|".join(zh_patterns) + ")"
    return re.compile(full, re.IGNORECASE)


TARGET_ROLE_REGEX = _v85_compile_mixed(TARGET_ROLE_PATTERNS)


# v8.5 新增: ENTRY_LEVEL_PATTERNS — SKIP, no senior rescue
# 命中 → "entry_level" reason, 不檢查 target role
# 例: "Junior Product Manager" → 跳 (entry gate 在 target guard 之前)
ENTRY_LEVEL_PATTERNS = [
    r"intern",
    r"internship",
    r"trainee",
    r"graduate",
    r"\bgrad\b",
    r"\bentry[\s\-]?level\b",
    r"\bentry\b",
    r"junior",
    r"\bjr\b",
    # 中文 (substring)
    r"實習",
    r"工讀",
    r"培訓",
    r"訓練生",
    r"應屆",
    r"畢業",
    r"助理",
    r"初階",
]
ENTRY_LEVEL_REGEX = _v85_compile_mixed(ENTRY_LEVEL_PATTERNS)


# v8.5 新增: HARD_NON_TARGET_ROLE_PATTERNS — SKIP, no senior rescue
# 命中 → "hard_non_target" reason, 不檢查 senior
# 重點: "Director of Sales" / "Senior Product Designer" 命中就跳
#
# v8.5 Repair3 (P1-01): Product-* family 的 separator 改用共享 _V85_PRODUCT_FAMILY_SEP
# (whitespace + ASCII hyphen + en-dash + non-breaking hyphen)。whitespace 形式
# (e.g. "Product Marketing") 仍命中, hyphen 形式 (e.g. "Product-Marketing") 也命中。
HARD_NON_TARGET_ROLE_PATTERNS = [
    # === English: product family (non-PM) ===
    # v8.5 Repair3: 全部 product-* family 改用 _V85_PRODUCT_FAMILY_SEP, 不再只看 whitespace
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"designer",
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"designers",
    # v8.5 Repair2: 補 product design (R2-05 optional, "Assistant Director, Product Design" → SKIP)
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"design",
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"validation",
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"certification",
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"analyst",
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"marketing",
    # v8.5 Repair2: 補 product support (R2-14 "VP of Product Support" → SKIP)
    r"product" + _V85_PRODUCT_FAMILY_SEP + r"support",
    # === English: account family ===
    r"account\s+manager",
    r"account\s+managers",
    r"account\s+management",  # A08 "Director, Key Account Management"
    r"key\s+account\s+manager",
    r"key\s+account\s+managers",
    r"key\s+account\s+management",  # A08
    r"client\s+manager",
    r"client\s+managers",
    r"client\s+management",
    r"relationship\s+manager",
    r"relationship\s+managers",
    r"relationship\s+management",
    r"account\s+executive",
    r"accountant",
    r"accountants",
    r"accounting",
    r"audit",
    r"auditor",
    r"auditors",
    # === English: HR / Recruiting ===
    r"human\s+resources",
    r"recruiter",
    r"recruiters",
    r"recruiting",
    r"recruitment",  # A12 "Head of Recruitment"
    r"head\s+of\s+recruitment",  # A12 explicit
    r"head\s+of\s+human\s+resources",  # A11 "VP Human Resources" - covered by vp + hr
    # === English: Procurement ===
    r"procurement",
    r"purchasing",
    r"purchaser",
    r"purchasers",
    r"buyer",
    r"buyers",
    r"merchandiser",
    r"merchandisers",
    # === English: Sales/BD ===
    # 註: 裸 "sales" 不在 L2 (避免 "Program Manager, Sales Platform" 誤殺)
    #     L3 (CONTEXTUAL_ROLE_PATTERNS) 用 role-shape 才跳 (e.g. "Sales Manager", "Director of Sales")
    # "business development" 仍是 hard non-target (BD 整個 family 是 sales track)
    r"business\s+development",
    # === English: Quality/Test inspector 角色 ===
    # "Quality Inspector" / "Test Inspector" 內 "quality"/"test" 是 bare word, 但 "inspector"
    # 是明確 non-PM role, 加 inspector/tester 進 L2 確保這些跳過
    r"\binspector\b",
    r"\btester\b",
    r"inspection\s+(engineer|manager|lead|specialist)",
    # === English: Generic support ===
    r"coordinator",
    r"administrator",
    r"clerk",
    r"secretary",
    # === Chinese ===
    r"會計",
    r"財會",
    r"出納",
    r"稽核",
    r"稅務",
    r"人資",
    r"人力資源",
    r"招募",
    r"薪酬",
    r"總務",
    r"採購",
    r"協調",
    r"統籌",
    r"秘書",
    r"行政",
    r"工讀生",
    r"書記",
    r"行銷",
    r"市場專員",
]
HARD_NON_TARGET_REGEX = _v85_compile_mixed(HARD_NON_TARGET_ROLE_PATTERNS)


# v8.5 新增: CONTEXTUAL_ROLE_PATTERNS — role-shaped exclusion
# 只在「domain word + role suffix」時才跳, 不會誤殺 "Product Manager, Sales Platform"
# 命中 → "contextual_role" reason
#
# v8.5 Repair5 (P1-01, P1-02, P1-03): Sales role-shape 進一步完成
#   - 加 _V85_SALES_SEP 共用 separator fragment (whitespace + comma + hyphen + en-dash + non-breaking hyphen + slash)
#   - 加 Sales Development / Operations / Enablement / Strategy / Marketing sub-function family
#   - 加中文 銷售 / 業務開發 / 銷售開發 role-shaped coverage
#   - 業務 role suffix 補 副總
# v8.5 Repair6 (P1-01..P1-03):
#   - reverse-order Sales sub-function (^anchored)
#   - forward-order leadership closure (head/vp)
#   - Taiwan 中文 部門粒度 部 (optional)
# v8.5 Repair7 (P1-01..P1-04): cross-family contextual grammar closure
#   - 抽 _V85_CTX_ROLE_NOUN 共用 role-noun fragment (manager|director|head|vp|vice\s+president|lead|
#     specialist|engineer|executive|consultant|analyst|coordinator|officer|associate|rep|representative|
#     technician|automation|architect|...)
#   - Sales sub-function 5 個 pattern 統一用 _V85_CTX_ROLE_NOUN
#   - Quality 雙向 leadership (forward: Quality <role>; reverse: Director/Head/VP/AVP of Quality)
#   - QA / Test 雙向 (Director/Head/VP of QA/Testing, Test Engineering)
#   - Support 雙向 (Customer/Technical/Generic Support leadership)
#   - 中文 cross-family 部 (品質/品質保證/品質管理/品管/品保/測試/客服/技術支援/技術服務 全部加 _V85_CN_ORG_PARTICLE)
# 仍維持 role-shape 原則, 沒加裸 "sales/quality/support/test" universal hard skip
# v8.5 Repair7 (P1-06): 把 literal U+2012 FIGURE DASH 改成 \u2012 escape,
# 確保 SEP source 為純 ASCII, 避免 _v85_compile_mixed 的 CJK detection 誤判。
_V85_SALES_SEP = r"[\s,\-/\u2012\u2011\u2013]+"  # Sales role identity 分隔符 (6 種: whitespace, comma, ASCII hyphen, slash, figure dash, non-breaking hyphen, en-dash)

# v8.5 Repair7 (P1-01..P1-04): shared contextual role-noun fragment
# Used across all 5 contextual families (Sales / Quality / QA / Test / Support) to ensure
# consistent closure. Includes both leadership (manager/director/head/vp) and functional
# (specialist/engineer/executive/consultant/analyst/coordinator/officer/associate/rep/...)
# role nouns. Leadership abbreviations (AVP/SVP/EVP) are separate because they
# typically precede the domain word (forward-form).
_V85_CTX_ROLE_NOUN = (
    r"(manager|director|head|vp|vice\s+president|lead|"
    r"chief|officer|"
    r"specialist|engineer|executive|consultant|analyst|coordinator|"
    r"associate|rep|representative|technician|architect|"
    r"supervisor|administrator|advisor|operator)"
)
# 排除 "automation" / "control" / "assurance" 這類容易跟 domain name 混淆的詞
# (e.g. "Sales Development Automation" 是 platform 名, "Quality Control" 是 domain)

# v8.5 Repair5 (P1-01): Sales forward-order role suffix (backward compat alias)
_V85_SALES_ROLE_SUFFIX_EN = (
    r"(manager|director|executive|specialist|engineer|rep|representative|"
    r"associate|consultant|lead|head|vp|vice\s+president)"
)

# v8.5 Repair6 (P1-01): reverse-order Sales sub-function roles
# e.g. "Manager, Sales Development" / "Senior Manager - Sales Operations" / "Lead, Sales Strategy"
_V85_SALES_REVERSE_ROLE = r"(senior\s+manager|manager|lead)"
_V85_SALES_SUBFUNCTION = r"(development|operations|enablement|strategy)"

# v8.5 Repair7 (P1-02..P1-04): shared reverse-order role for Quality/QA/Test/Support
# Anchored to ^ (start of string) to avoid matching "Program Manager, Quality Platform" /
# "AI Platform Lead, Test Engineering" / "Product Operations Lead, Customer Support" / etc.
_V85_CTX_REVERSE_ROLE = r"(senior\s+manager|manager|lead|director|head|vp|vice\s+president)"

# v8.5 Repair6 (P1-03) Chinese suffix for Sales family
_V85_CN_SALES_SUFFIX = r"(主管|經理|總監|副理|協理|襄理|處長|副總|代表|顧問|專員|工程師)"

# v8.5 Repair7 (P1-05): unified Chinese contextual role suffix
# Used across 品質/品質保證/品質管理/品管/品保/測試/客服/技術支援/技術服務
# Includes 副總 (per R7-68 客服副總) + 工程師 (per R7-63 品質工程師)
_V85_CN_CTX_SUFFIX = r"(主管|經理|總監|副理|協理|襄理|處長|副總|代表|顧問|專員|工程師)"

# v8.5 Repair6 (P1-03) Taiwan 104-style organizational particle 部 (optional)
_V85_CN_ORG_PARTICLE = r"(部\s*)?"

CONTEXTUAL_ROLE_PATTERNS = [
    # === Sales role shapes ===
    # v8.5 Repair4 (P1-01): 補 AVP/SVP/EVP 前綴 + Sales Lead/Head/VP/Vice President + Chief Sales Officer
    # v8.5 Repair5 (P1-01): 全部 Sales pattern 改用 _V85_SALES_SEP, 認 separator (whitespace + comma
    #   + hyphen + en-dash + non-breaking hyphen + slash)。
    # v8.5 Repair6 (P1-02): forward-order Sales sub-function suffix 補 head/vp 給 Development /
    #   Enablement / Strategy / & Marketing 完整 leadership。
    # v8.5 Repair7 (P1-01): 改用 _V85_CTX_ROLE_NOUN 統一 role-noun suffix (含 Executive/Analyst/
    #   Consultant/Engineer/Associate/Coordinator/Officer 等明確 Sales-track role)
    r"sales" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"(head|director|vp|vice\s+president)" + _V85_SALES_SEP + r"(of" + _V85_SALES_SEP + r")?sales",
    r"(avp|svp|evp)" + _V85_SALES_SEP + r"(of" + _V85_SALES_SEP + r")?sales",
    # === Sales sub-function family (forward-order) — Repair7 P1-01 ===
    # 用共享的 _V85_CTX_ROLE_NOUN 取代 4 個 sub-function 各自 suffix list
    # 解掉 Executive/Analyst/Consultant/Engineer/Associate/Coordinator/Officer 全部漏
    r"sales" + _V85_SALES_SEP + r"(development|operations|enablement|strategy)" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    # Sales & Marketing / Sales and Marketing (separate pattern because of `&|and` between)
    r"sales" + _V85_SALES_SEP + r"(&|and)" + _V85_SALES_SEP + r"marketing" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"chief" + _V85_SALES_SEP + r"sales" + _V85_SALES_SEP + r"officer",
    r"sales" + _V85_SALES_SEP + r"engineer",
    # === Sales sub-function family (reverse-order) — Repair6 P1-01 + Repair7 P1-01 ===
    # Anchored to ^ (start of string) to avoid matching "Program Manager" / "AI Platform Lead"
    # 等 forward-order 的 Manager/Lead
    r"^" + _V85_SALES_REVERSE_ROLE + _V85_SALES_SEP + r"sales" + _V85_SALES_SEP + _V85_SALES_SUBFUNCTION,
    # === Quality role shapes — Repair7 P1-02 ===
    # Forward: `quality <role>` / `quality assurance <role>` / `quality engineering <role>`
    r"quality" + _V85_SALES_SEP + r"engineering" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"quality" + _V85_SALES_SEP + r"assurance" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"quality" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    # Reverse (leadership first): Director/Head/VP/AVP of Quality
    # Trailing assurance/engineering + role 整段 optional, 涵蓋 "Director of Quality" (品質在尾)
    r"^"
    + _V85_CTX_REVERSE_ROLE
    + _V85_SALES_SEP
    + r"(of"
    + _V85_SALES_SEP
    + r")?quality("
    + _V85_SALES_SEP
    + r"(assurance|engineering)("
    + _V85_SALES_SEP
    + _V85_CTX_ROLE_NOUN
    + r")?)?",
    r"^" + r"(avp|svp|evp)" + _V85_SALES_SEP + r"(of" + _V85_SALES_SEP + r")?quality",
    # Reverse (generic): Manager/Lead, Quality
    r"^" + r"(senior\s+manager|manager|lead)" + _V85_SALES_SEP + r"quality",
    # === QA / Test role shapes — Repair7 P1-03 ===
    # Forward: `qa <role>` / `test|testing <role>` / `test engineering <role>`
    r"qa" + _V85_SALES_SEP + r"engineering" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"qa" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"(test|testing)" + _V85_SALES_SEP + r"engineering" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"(test|testing)" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    # Reverse: Director/Head/VP of QA/Testing
    r"^" + _V85_CTX_REVERSE_ROLE + _V85_SALES_SEP + r"(of" + _V85_SALES_SEP + r")?(qa|testing|test\s+engineering)",
    r"^" + r"(avp|svp|evp)" + _V85_SALES_SEP + r"(of" + _V85_SALES_SEP + r")?(qa|testing)",
    # Reverse (generic): Manager/Lead, QA/Testing
    r"^" + r"(senior\s+manager|manager|lead)" + _V85_SALES_SEP + r"(qa|testing|test\s+engineering)",
    # === Support role shapes — Repair7 P1-04 ===
    # Forward: `<support-domain> support <role>` / `support <role>` / `support operations <role>`
    r"(customer|technical|it|desktop|tier|application|product)"
    + _V85_SALES_SEP
    + r"support"
    + _V85_SALES_SEP
    + r"operations?"
    + _V85_SALES_SEP
    + _V85_CTX_ROLE_NOUN,
    r"(customer|technical|it|desktop|tier|application|product)"
    + _V85_SALES_SEP
    + r"support"
    + _V85_SALES_SEP
    + _V85_CTX_ROLE_NOUN,
    r"support" + _V85_SALES_SEP + r"operations?" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    r"support" + _V85_SALES_SEP + _V85_CTX_ROLE_NOUN,
    # Reverse: Director/Head/VP of Customer/Technical/Generic Support
    r"^"
    + _V85_CTX_REVERSE_ROLE
    + _V85_SALES_SEP
    + r"(of"
    + _V85_SALES_SEP
    + r")?(customer|technical|it|application|product)?\s*support",
    r"^" + r"(avp|svp|evp)" + _V85_SALES_SEP + r"(of" + _V85_SALES_SEP + r")?(customer|technical|it)?\s*support",
    # === Chinese role shapes — Repair7 P1-05 ===
    # 全部 9 個中文 family 都加 _V85_CN_ORG_PARTICLE (部 optional)
    # Sales family (4 個, 之前 Repair5/6 已加)
    r"業務" + _V85_CN_ORG_PARTICLE + _V85_CN_SALES_SUFFIX,
    r"銷售" + _V85_CN_ORG_PARTICLE + _V85_CN_SALES_SUFFIX,
    r"業務開發" + _V85_CN_ORG_PARTICLE + _V85_CN_SALES_SUFFIX,
    r"銷售開發" + _V85_CN_ORG_PARTICLE + _V85_CN_SALES_SUFFIX,
    # Quality / QA / Test / Support family — Repair7 P1-05 cross-family 部
    r"品質" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"品質保證" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"品質管理" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"品管" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"品保" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"測試" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"客服" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"技術支援" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
    r"技術服務" + _V85_CN_ORG_PARTICLE + _V85_CN_CTX_SUFFIX,
]
CONTEXTUAL_ROLE_REGEX = _v85_compile_mixed(CONTEXTUAL_ROLE_PATTERNS)


# v8.5 新增: specialist 收窄 ambiguity rule
# specialist 預設跳; 只有 senior marker + target/product/AI context 才 KEEP
# v8.5 Repair1: 改用 word-boundary regex patterns, 避免 "ai" / "ux" 這種 short token
# 在 "retail" / "training" / "paid" / "email" / "luxury" 等詞內 substring 誤觸。
# 每個 context 是一個 compiled regex pattern, 自動分流 EN (word-boundary) 跟 CN (substring)。
def _v85_compile_contexts_as_regex(contexts: list[str]) -> re.Pattern:
    """v8.5 Repair1: 將 context list 編譯為單一 regex, EN 用 word-boundary, CN 用 substring.

    修 P1-01: 'ai' 在 'retail' / 'training' / 'paid' / 'email' 內 substring 誤觸的問題.
    修法: 把每個 EN literal context 經 re.escape() 處理特殊 regex 字元, 再包進 \\b...\\b。
    例如 "ai" 編為 "\\bai\\b", "product" 編為 "\\bproduct\\b", 中文維持 substring match。

    實作細節 (與文件一致, 對應 P2-02 修正):
      - EN context: 呼叫 re.escape(c) 處理 regex meta (避免 "ai.product" 這種 token 出現時
        "." 被當 regex), 然後 wrap 在 \\b...\\b 邊界
      - CN context: 直接 substring match, 不呼叫 re.escape
    """
    en_pats, cn_pats = [], []
    for c in contexts:
        if any(ord(ch) >= 128 for ch in c):
            cn_pats.append(c)
        else:
            en_pats.append(rf"\b{re.escape(c)}\b")
    if en_pats and cn_pats:
        full = r"(?:" + "|".join(en_pats) + ")|(?:" + "|".join(cn_pats) + ")"
    elif en_pats:
        full = r"(?:" + "|".join(en_pats) + ")"
    else:
        full = r"(?:" + "|".join(cn_pats) + ")"
    return re.compile(full, re.IGNORECASE)


# English word-boundary, Chinese substring (mixed)
SPECIALIST_KEEP_CONTEXTS = [
    # English (word-boundary)
    "product",
    "ai",
    "platform",
    "data",
    "growth",
    "ux",
    "operations",
    # Chinese (substring)
    "產品",
    "平台",
    "數據",
    "用戶增長",
]
SPECIALIST_KEEP_CONTEXT_REGEX = _v85_compile_contexts_as_regex(SPECIALIST_KEEP_CONTEXTS)

# v8.5 新增: assistant 收窄 ambiguity rule
# assistant 預設跳; 只有 (AVP/VP/director 緊接) + (target/product/AI context) 才 KEEP
# 不再被 "Senior X" 救回 (dispatch P1-02 narrow rule)
# v8.5 Repair1: 同樣改用 word-boundary regex
ASSISTANT_KEEP_CONTEXTS = [
    # English (word-boundary)
    "product",
    "ai",
    "platform",
    "growth",
    "data",
    # Chinese (substring)
    "產品",
    "平台",
    "數據",
]
ASSISTANT_KEEP_CONTEXT_REGEX = _v85_compile_contexts_as_regex(ASSISTANT_KEEP_CONTEXTS)
ASSISTANT_SENIOR_TRIGGERS = [
    "vice president",
    "vp",
    "director",
    "avp",
]


def _v85_is_assistant_target_senior(title: str) -> bool:
    """assistant narrow rule (P1-02, Repair1 word-boundary):
    KEEP only if BOTH:
      1) assistant/asst 直接接 senior trigger (e.g. "Assistant Vice President,", "Assistant Director,")
      2) title 含 target context (e.g. product, ai, platform) -- 經 word-boundary regex match

    v8.5 Repair1: 'ai' / 'product' 等用 \\b 邊界, 避免 'retail' (含 'ai') 誤觸.
    否則 → SKIP (return "assistant")
    """
    t = title.lower()
    # Step 1: assistant 緊接 senior trigger (允許逗號)
    has_adjacent_senior = False
    for trig in ASSISTANT_SENIOR_TRIGGERS:
        if f"assistant {trig}" in t or f"assistant, {trig}" in t or f"asst {trig}" in t or f"asst. {trig}" in t:
            has_adjacent_senior = True
            break
    if not has_adjacent_senior:
        return False
    # Step 2: title 含 target context (word-boundary)
    return ASSISTANT_KEEP_CONTEXT_REGEX.search(t) is not None


def _v85_is_specialist_senior_with_target(title: str) -> bool:
    """specialist narrow rule (P1-03, Repair1 word-boundary):
    KEEP only if BOTH:
      1) title 含 senior marker (e.g. Senior, Principal, AVP, Director)
      2) title 含 target/product context -- 經 word-boundary regex match

    v8.5 Repair1: 'ai' / 'ux' 等用 \\b 邊界, 避免 'retail' / 'luxury' 內 substring 誤觸.
    否則 → SKIP (return "specialist")
    """
    t = title.lower()
    if not _v85_has_senior_marker(t):
        return False
    return SPECIALIST_KEEP_CONTEXT_REGEX.search(t) is not None


def _v85_has_senior_marker(t_lower: str) -> bool:
    """v8.5: 跟既有 _has_senior_marker_anywhere 一致 (word-boundary EN, substring CN).
    內部使用, 不重複 compile."""
    return _get_senior_markers_pattern().search(t_lower) is not None


# 保留 WHITELIST_RULES 給舊的 _is_senior_assistant_title 與 v8.5 narrow rules 共用
# (assistant narrow rule 從這裡的 "adjacent" 概念繼承, 但更嚴格 — 還要 target context)
WHITELIST_RULES = {
    "assistant": "adjacent",  # 保留給 v8.4 backward compat
    "specialist": "anywhere",  # 保留給 v8.4 backward compat
}


# ─────────────────────────────────────────────────────────────
# 關鍵字比對工具
# ─────────────────────────────────────────────────────────────
def _make_skip_pattern(skip_words: list[str]) -> re.Pattern:
    """編一個 case-insensitive、word-boundary 的 regex。

    空清單回傳一個「永遠不匹配」的模式, 不是零寬度模式。
    零寬度模式 (如 ``(?<![a-z])()(?![a-z])``) 會匹配任何位置, 等於把所有標題
    都標成 skip —— 例如 ``--skip-keywords`` 不帶參數時 (nargs="*") 就是空清單。
    """
    if not skip_words:
        return re.compile(r"(?!)", re.IGNORECASE)
    escaped = [re.escape(w) for w in skip_words]
    # \b 在 "entry-level" 這種 hyphen 字串會失效，改成 (?<![a-z])
    pat = r"(?<![a-z])(" + "|".join(escaped) + r")(?![a-z])"
    return re.compile(pat, re.IGNORECASE)


def _is_senior_assistant_title(title: str) -> bool:
    """adjacent 模式: 'assistant' 直接接 senior 詞才算 senior (避免 'Assistant to CEO' 誤判)"""
    if not title:
        return False
    t = title.lower()
    for sw in SENIOR_FOLLOWERS:
        if f"assistant {sw}" in t or f"assistant, {sw}" in t:
            return True
    return False


# 2026-08-29 Bug fix: senior marker 改用 word-boundary regex match, 避免 substring 誤判
# e.g. "cto" 之前會誤殺 "quality inspector" / "director" 會誤殺 "subdirector" 等
_SENIOR_MARKERS_PATTERN = None


def _get_senior_markers_pattern() -> re.Pattern:
    """lazy compile: 英文 senior marker 用 word-boundary, 中文 senior marker 用 substring。
    因為英文 \b 跟中文邊界處理不同, 分兩個 regex。
    """
    global _SENIOR_MARKERS_PATTERN
    if _SENIOR_MARKERS_PATTERN is not None:
        return _SENIOR_MARKERS_PATTERN
    # 英文 senior marker (要 word-boundary, 避免 cto in inspector 誤判)
    en_markers = [m for m in SENIOR_MARKERS_ANYWHERE if all(ord(c) < 128 for c in m)]
    zh_markers = [m for m in SENIOR_MARKERS_ANYWHERE if any(ord(c) >= 128 for c in m)]
    en_escaped = [re.escape(m) for m in en_markers]
    # \b 在 "vice president" 這種 multi-word 會失效, 用 (?<![a-z]) + (?![a-z])
    en_pat = r"(?<![a-z])(" + "|".join(en_escaped) + r")(?![a-z])"
    # 中文 senior marker (substring match 即可, 中文字沒 word boundary 概念)
    zh_escaped = [re.escape(m) for m in zh_markers]
    zh_pat = "|".join(zh_escaped)
    full = en_pat if not zh_pat else (en_pat[:-1] + "|" + zh_pat + ")" if en_escaped else zh_pat)
    if en_escaped and zh_escaped:
        # 兩個 group 都需要, 構造 (en_group)|(zh_group)
        full = r"(?<![a-z])(" + "|".join(en_escaped) + r")(?![a-z])|(" + "|".join(zh_escaped) + r")"
    elif en_escaped:
        full = en_pat
    else:
        full = r"(" + zh_pat + r")"
    _SENIOR_MARKERS_PATTERN = re.compile(full, re.IGNORECASE)
    return _SENIOR_MARKERS_PATTERN


def _has_senior_marker_anywhere(title: str) -> bool:
    """anywhere 模式: title 任一位置有 senior 標記就算。
    2026-08-29 改用 word-boundary regex (英文) + substring (中文), 避免 'cto' 誤殺 'inspector' 等。"""
    if not title:
        return False
    return _get_senior_markers_pattern().search(title) is not None


def match_skip_reason(title: str, skip_pat: re.Pattern = None, *, source: str | None = None) -> str | None:
    """v8.5 Bounded Repair — crawler pre-filter.

    Executable precedence (matches runtime order below exactly):
      1. empty title -> KEEP (None)
      2. ENTRY_LEVEL_REGEX hit -> SKIP "entry_level" (junior PM, intern, etc.)
      3. assistant narrow rule: SKIP unless AVP/VP/director + target context;
         with hard_non_target veto in front (added in Repair2 P1-01) — if the title
         matches HARD_NON_TARGET_ROLE_PATTERNS, return "hard_non_target" instead of
         letting the assistant narrow rule rescue the title.
      4. TARGET_ROLE_REGEX hit -> KEEP (overrides everything below, only AFTER
         entry-level so "Junior Product Manager" / "Assistant Product Manager" SKIPs).
      5. HARD_NON_TARGET_REGEX hit -> SKIP "hard_non_target" (no senior rescue).
      6. CONTEXTUAL_ROLE_REGEX hit -> SKIP "contextual_role" (role-shaped sales/
         quality/test/support; v8.5 Repair4 P1-01 expanded Sales to cover AVP/SVP/EVP
         prefixes, Sales Lead/Head/VP/Vice President, Chief Sales Officer, and
         Sales Operations/Enablement manager/lead).
      7. specialist narrow rule: SKIP unless senior + target context.
      8. CHINESE_SKIP_REGEX hit -> SKIP "chinese_skip".
      9. ONEZEROFOUR_EXTRA_SKIP_REGEX hit (only source=onezerofour) -> SKIP "tw_extra_skip".
     10. no rule matched -> KEEP (None).

    CRITICAL CHANGES from v8.4:
      - Removed global "senior marker rescues any skip hit" fallback.
      - Hard non-target role identity (e.g. account manager, accountant, recruiter) is NOT
        rescued by seniority. "Senior Accountant" → SKIP. "Director of Sales" → SKIP.
      - Contextual words (sales, quality, support, test) alone don't kill. Only role-shaped
        (e.g. "sales manager", "quality engineer") kills. "Product Manager, Sales Platform" → KEEP.
      - Bare "contract", "temp", "temporary" no longer in skip list. "AI Product Manager - 12 Month
        Contract" → KEEP. "Contract Recruiter" still SKIP via recruiter hard non-target.
      - Assistant narrow: only AVP/VP/director + product/AI context KEEP. "Assistant to CEO" → SKIP.
      - Specialist narrow: senior + product/AI context KEEP. "Senior Marketing Specialist" → SKIP.

    Args:
        title: Job title to evaluate.
        skip_pat: DEPRECATED in v8.5. v8.5 made this argument optional (default None)
                  for backward compat with the `enrich_with_jd` calling pattern, but
                  v8.5 internally uses semantic groups and ignores skip_pat.
                  Public signature is NOT byte-identical to v8.4 (v8.4 had
                  `skip_pat: re.Pattern` as a required positional argument; v8.5
                  has `skip_pat: re.Pattern = None`). Callers passing skip_pat
                  positionally still work, but new code should pass it by keyword
                  or omit it entirely.
        source: "linkedin" / "jora" / "jobstreet" / "onezerofour" / None.
    """
    if not title:
        return None
    # 1. Entry-level gate (SKIP, no senior rescue, BEFORE target guard per §02)
    # 例: "Junior Product Manager" / "Product Manager Intern" / "Assistant Product Manager"
    #     → SKIP (雖然內含 target role 詞, 但 entry-level 排除)
    if ENTRY_LEVEL_REGEX.search(title):
        return "entry_level"
    # 1b. Assistant narrow rule — Repair2 P1-01 加 hard-non-target veto 在前
    # 例: "Assistant Vice President, Product" → KEEP (assistant + VP + product)
    #     "Assistant Director, Human Resources" → SKIP (assistant + director 但 no product context)
    #     "Assistant Product Manager" → SKIP (assistant 在前, 不符合 narrow rule)
    #     "Administrative Assistant" → SKIP (no senior trigger)
    # Repair2 P1-01: assistant branch 不能 rescue explicit hard non-target Product-* family
    #     "Assistant VP, Product Marketing" → SKIP (hard_non_target 優於 assistant narrow)
    #     "Assistant Director, Product Validation" → SKIP (同上)
    if re.search(r"\bassistant\b|\basst\.?\b", title, re.IGNORECASE):
        # 先檢查 hard non-target: Product Marketing / Validation / Certification /
        # Design / Support / Analyst / Designer / Accountants / Recruiter / Buyer 等
        # 一旦命中, 直接以 hard_non_target 為 reason 跳過, 不讓 narrow rule 救回。
        if HARD_NON_TARGET_REGEX.search(title):
            return "hard_non_target"
        if _v85_is_assistant_target_senior(title):
            return None
        return "assistant"
    # 2. Target-role guard (KEEP, only AFTER entry-level)
    # 例: "Product Manager, Sales Platform" 命中 product manager pattern → KEEP
    #     "Senior Product Designer" 不命中 (designer 不在 target) → 進 L3
    if TARGET_ROLE_REGEX.search(title):
        return None
    # 3. Hard non-target role (SKIP, no senior rescue)
    # 例: "Senior Product Designer" → 命中 product designer → SKIP
    #     "Senior Accountant" → 命中 accountant → SKIP
    #     "會計經理" → 命中 會計 → SKIP
    if HARD_NON_TARGET_REGEX.search(title):
        return "hard_non_target"
    # 4. Contextual role-shape (SKIP, no senior rescue)
    # 例: "Sales Manager" → 命中 sales + manager → SKIP
    #     "Quality Director" → 命中 quality + director → SKIP
    #     "QA Engineer" → 命中 qa + engineer → SKIP
    #     "Program Manager, Sales Platform" → 不命中 (sales 後面不是 role suffix)
    if CONTEXTUAL_ROLE_REGEX.search(title):
        return "contextual_role"
    # 5. Specialist narrow rule
    # 例: "Senior Product Specialist" → 命中 specialist, senior + product → KEEP
    #     "Senior Marketing Specialist" → 命中 specialist, senior 但 no product → SKIP
    #     "Product Specialist" → 命中 specialist, no senior → SKIP
    if re.search(r"\bspecialist\b", title, re.IGNORECASE):
        if _v85_is_specialist_senior_with_target(title):
            return None
        return "specialist"
    # 6. Chinese general skip (source-agnostic, only Chinese chars)
    if CHINESE_SKIP_REGEX.search(title):
        return "chinese_skip"
    # 7. Source-specific skip (e.g. Taiwan 104-specific, Cake Taiwan-context)
    # _L6_SOURCES 為 set，未來加台灣其他平台只要 set.add("xxx")
    if source in _L6_SOURCES and ONEZEROFOUR_EXTRA_SKIP_REGEX.search(title):
        return "tw_extra_skip"
    return None


# 104 中文 skip patterns (RULES §15.9, 跟 24 個英文詞對應)
# 註: 跟 _make_skip_pattern 不同, 這裡直接寫 regex 不用 word-boundary
# 因為中文字本身就沒 word boundary 概念, 全部用 substring match
# v8.5: 移除 "約聘|短期|兼職|派遣" (P0-04, employment type 不再 unconditional hard skip)
CHINESE_SKIP_PATTERNS = [
    r"實習|工讀",  # intern
    r"培訓|訓練生",  # trainee
    r"應屆|畢業",  # graduate
    r"助理|初階",  # junior
    r"助理|秘書|行政",  # assistant
    r"協調|統籌",  # coordinator
    r"工讀生|書記",  # clerk
    r"行銷|市場專員",  # product marketing
    # 註: "技術支援|客服" / "測試|品質" / "業務|業務開發|銷售" / "專員"
    #     在 v8.5 改為 CONTEXTUAL_ROLE_PATTERNS (L3) 跟 HARD_NON_TARGET_ROLE_PATTERNS (L2) 處理
    #     移除從這層, 因為這些詞需要 role-shape 判定
]
CHINESE_SKIP_REGEX = re.compile("|".join(CHINESE_SKIP_PATTERNS))


# L6 source set: 哪些 source 會跑 ONEZEROFOUR_EXTRA_SKIP_PATTERNS
# 2026-08-30 從 {"onezerofour"} 擴展到 {"onezerofour", "cake"}
# - 設計意圖: 變數名保留 ONEZEROFOUR_* (避免 audit chain 重新 freeze 命名)
# - 實質: 13 組 64 詞台灣特有非 PM 職類同樣套用到 cake (台灣+海外 PM 平台)
# - 未來加 mit / other 台灣平台: set.add("mit") 即可, 不動其他 code
_L6_SOURCES = {"onezerofour", "cake"}


# 104 專用 extra skip patterns (RULES §15.19, 2026-08-29 第一批)
# source-specific (only _L6_SOURCES 才跑，不會影響 LinkedIn/Jora/JobStreet SG)
# 用途: 過濾台灣 source (104/cake/未來 mit) 上的「非 PM 職類」, 避免拉一堆作業員/倉管/門市店員等
#
# 可被 ONEZEROFOUR_EXTRA_SKIP env var 覆寫 (用 "||" 分隔多個 regex pattern, 加新 batch 直接用 .env 改)
# 例: ONEZEROFOUR_EXTRA_SKIP="作業員|操作員||會計|財會||門市|店員"
ONEZEROFOUR_EXTRA_SKIP_PATTERNS = [
    # factory / manual
    r"作業員|操作員|技術員|產線|生產線|包裝作業|組裝作業",
    # quality / inspection
    r"品檢|品管|品保|目檢|檢驗員",
    # warehouse / material
    r"倉管|倉儲|庫房|理貨|物料|物控|生管|廠務",
    # accounting
    r"會計|財會|出納|稅務|稽核",
    # HR / admin
    r"人資|人力資源|招募|薪酬|總務",
    # construction / property
    r"工地|工務|營建|土建|監造",
    # 幹事/總幹事 都跳 (台灣社區/行政 都有, e.g. 行政幹事/業務幹事/採購幹事/總幹事)
    r"保全|勤務|幹事|物業",
    # retail / service
    r"門市|店員|店長|專櫃",
    r"司機|駕駛|隨扈",
    r"外場|內場|主廚|廚師|咖啡師|房務|客務|禮賓",
    # education
    r"老師|教師|講師|安親|幼兒園",
    # purchasing
    r"採購",
    # professional tracks
    r"法務|護理師|護士|美容師",
]
# env var 覆寫支援 (跟 JOBSTREET_KEYWORDS_OVERRIDE 同 pattern)
ONEZEROFOUR_EXTRA_SKIP_OVERRIDE = os.getenv("ONEZEROFOUR_EXTRA_SKIP", "")
if ONEZEROFOUR_EXTRA_SKIP_OVERRIDE:
    # 用 "||" 分隔多個 regex, "|" 內部是 single regex 的 OR
    ONEZEROFOUR_EXTRA_SKIP_PATTERNS = [p for p in ONEZEROFOUR_EXTRA_SKIP_OVERRIDE.split("||") if p.strip()]
ONEZEROFOUR_EXTRA_SKIP_REGEX = re.compile("|".join(ONEZEROFOUR_EXTRA_SKIP_PATTERNS))


# ─────────────────────────────────────────────────────────────
# 跨 run 已抓 JD 記錄 (JSONL, append-only)
# ─────────────────────────────────────────────────────────────
def jd_hash(jd_text: str) -> str:
    return hashlib.sha256((jd_text or "").encode("utf-8")).hexdigest()[:16]


def _infer_source_from_job_id(job_id: str) -> str:
    """從 job_id 推斷 source。

    - 32-char hex → jora (DEPRECATED 2026-09-09: Jora SG 關站, 保留給舊 seen_jds.jsonl entries)
    - 純數字 → linkedin (舊資料兼容；jobstreet 會在 record 內帶 source)
    - Cake path 常是長 hyphenated slug + hex tail
    """
    # DEPRECATED 2026-09-09: jora 推斷保留給舊 seen_jds.jsonl / *_jd.json 內的歷史 entries,
    # 確保 ~885 筆歷史 jora jobs 仍能被 dedup 識別 (active crawling 不再產 jora)
    if re.fullmatch(r"[a-f0-9]{32}", job_id or ""):
        return "jora"
    if re.fullmatch(r"\d+", job_id or ""):
        return "linkedin"
    if job_id and job_id.count("-") >= 2 and re.search(r"-[a-f0-9]{16,}$", job_id):
        return "cake"
    return "unknown"


def load_seen_ids(path: Path = Path(SEEN_FILE)) -> set[tuple[str, str]]:
    """讀 seen_jds.jsonl，回傳 set of (source, job_id)。壞行跳過不炸。

    ⚠️ 跨 source 區分: LinkedIn / JobStreet 都是純數字, 會撞; Jora 是 32-char hex 不撞;
       Cake 的 job_id 是長 hyphenated path, 可用來區分。
    舊記錄沒 source 欄位 → 從 job_id 推斷:
      - 32-char hex → "jora"  (DEPRECATED 2026-09-09: Jora SG 關站, 保留給舊 seen_jds.jsonl
                                  內的 ~885 筆 jora entries, 確保 dedup round-trip)
      - 純數字 → "linkedin" (預設, 因 2026-08-22 之前都是 LinkedIn + Jora)
    """
    if not path.exists():
        return set()
    seen = set()
    with open(path, "r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                jid = row.get("job_id")
                if not jid:
                    continue
                # 優先用記錄裡的 source, 沒有就從 job_id 推斷
                src = row.get("source")
                if not src:
                    src = _infer_source_from_job_id(jid)
                seen.add((src, jid))
            except json.JSONDecodeError:
                print(f"            (warn) seen file line {ln} 壞掉，跳過")
    return seen


def append_seen(
    job_id: str, jd_hash_val: str, title: str, company: str, path: Path = Path(SEEN_FILE), source: str = "linkedin"
) -> None:
    record = {
        "job_id": job_id,
        "source": source,  # 2026-08-22 新增, 之後區分 LinkedIn / JobStreet (jora DEPRECATED 2026-09-09)
        "jd_hash": jd_hash_val,
        "fetched_at": datetime.now(TZ_LOCAL).isoformat(timespec="seconds"),
        "title": (title or "")[:200],
        "company": (company or "")[:100],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jd_cache_from_jsons(pattern: str = "*_product_jobs_*_jd.json", skip_files: set[str] | None = None) -> dict:
    """
    從所有 *_jd.json 檔案載入 JD cache: {(source, job_id): {jd_text, jd_lines, jd_hash, ...}}。
    用作 enrich_with_jd 的跨 run cache 來源（避免已抓過的 JD 重抓）。

    2026-08-22 改: 從 {job_id: ...} 改為 {(source, job_id): ...}, 避免 LinkedIn / JobStreet 數字 ID 撞
    Cake 也同樣用 (source, job_id) tuple 來避免跟其他來源混淆。

    Args:
        pattern: glob pattern, 預設掃所有 *_jd.json
        skip_files: 要跳過的檔名 set（例: 當前 run 將要輸出的檔案）
    """
    cache = {}
    skip_files = skip_files or set()
    for fp in sorted(Path(".").glob(pattern)):
        if fp.name in skip_files:
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  (warn) {fp.name} 讀失敗: {e}")
            continue
        n = 0
        for j in data:
            jid = j.get("job_id")
            if not jid or not j.get("jd_text"):
                continue
            src = j.get("source")
            if not src:
                # DEPRECATED 2026-09-09: _infer_source_from_job_id 內的 jora 推斷保留給舊
                # *_jd.json 內的歷史 jora entries (active crawling 不再產 jora, 但 cache
                # 仍要讓舊 jobs round-trip)
                src = _infer_source_from_job_id(jid)
            key = (src, jid)
            if key not in cache:  # 第一個檔案優先
                cache[key] = {
                    "jd_text": j["jd_text"],
                    "jd_lines": j.get("jd_lines"),
                    "jd_hash": j.get("jd_hash"),
                }
                n += 1
        if n:
            print(f"  cache {fp.name}: +{n} JDs (累計 {len(cache)})")
    return cache


def reset_seen(path: Path = Path(SEEN_FILE)) -> int:
    """刪掉 seen file，回傳被刪除的筆數（如果有備份）。"""
    if not path.exists():
        return 0
    n = sum(1 for _ in open(path, "r", encoding="utf-8") if _.strip())
    path.unlink()
    return n


# ─────────────────────────────────────────────────────────────
# Visa / Sponsorship 偵測 (K 欄, 三層級)
# ─────────────────────────────────────────────────────────────
_VISA_RES = {level: re.compile("|".join(pats), re.IGNORECASE) for level, pats in VISA_PATTERNS.items()}


def detect_visa_signal(jd_text: str) -> str:
    """掃 JD 找 visa/sponsorship 信號。
    回傳: "" 沒訊號 | "⚠️ HARD: <text>" (明確拒絕) | "<text>" (SOFT/POSITIVE, 只貼原文)
    """
    if not jd_text:
        return ""
    for level in ("HARD", "SOFT", "POSITIVE"):
        m = _VISA_RES[level].search(jd_text)
        if m:
            if level == "HARD":
                return f"⚠️ HARD: {m.group(0)}"
            # SOFT / POSITIVE 直接回原文, 不加標籤
            return m.group(0)
    return ""


def extract_work_mode(jd_text: str, title: str = "") -> str:
    """從 JD 跟 title 抓 work mode (Remote / Hybrid / Onsite / 空)。
    純 regex, 不消耗 LLM token。
    2026-08-23 改: 統一用 "Onsite" (沒 hyphen); 重構成 list-of-patterns 結構, 邏輯跟原本一致
    優先序:
      1) Title 開頭 "Remote - ...", "Hybrid - ...", "Onsite - ..."
      2) JD 開頭 "Location: ... (hybrid)" / "on a hybrid basis" / "WORK OPTION: In Office"
      3) 中文常見 "远程办公" / "混合办公" / "现场办公" / "驻场"
      4) 全文 fallback "fully remote" / "hybrid working" / "onsite role"
    """

    # helper: 把 match 結果標準化 ("on-site" / "onsite" / "in office" → "Onsite"; 其他 capitalize)
    def _norm(v: str) -> str:
        v = v.lower().strip()
        if v.startswith("on"):
            return "Onsite"
        return v.capitalize()  # Remote / Hybrid

    if not jd_text and not title:
        return ""

    # 1) Title 開頭
    if title:
        m = re.match(r"^\s*(remote|hybrid|on-site|onsite)\s*[-—–/]", title.lower().strip())
        if m:
            return _norm(m.group(1))

    if not jd_text:
        return ""

    head = jd_text[:500]
    full = jd_text

    # 2) JD 開頭 500 chars — 3 個特殊 regex
    head_patterns = [
        (r"\(\s*(remote|hybrid|on-site|onsite)\s*\)", "norm", re.IGNORECASE),  # "(hybrid)"
        (r"\bon\s+a\s+(remote|hybrid|on-site|onsite)\s+basis\b", "norm", re.IGNORECASE),  # "on a hybrid basis"
        (r"\bwork\s+option[s]?\s*[:\-]?\s*(in\s+office|remote|hybrid|on-?site)\b", "work_option", re.IGNORECASE),
    ]
    for pat, mode, flags in head_patterns:
        m = re.search(pat, head, flags)
        if m:
            if mode == "norm":
                return _norm(m.group(1))
            else:  # "work_option": "in office" / "on-site" 都算 Onsite
                v = m.group(1).lower().replace(" ", " ")
                if "office" in v or v.startswith("on"):
                    return "Onsite"
                return v.capitalize()

    # 3) 中文常見 (JD 開頭 500 chars) + 4) 全文 fallback — 統一 list
    all_patterns = [
        # 中文 (只在 head 查)
        (r"远程(?:办公|工作|岗位)?|在家办公|线上办公", "Remote", "head"),
        (r"混合(?:办公|工作)|线上\s*[/＋+]\s*线下|弹性(?:办公|工作)", "Hybrid", "head"),
        (r"现场(?:办公)?|驻场|到岗|坐班|线下办公|全职坐班", "Onsite", "head"),
        # 英文 fallback (全文)
        (r"\b(fully\s+remote|100%\s+remote|work\s+from\s+home|wfh)\b", "Remote", "full"),
        (r"\b(hybrid\s+(working|role|arrangement)|hybrid\s+work)\b", "Hybrid", "full"),
        (r"\b(on-?site\s+(role|work|position)|on-?site\s+basis)\b", "Onsite", "full"),
    ]
    for pat, label, scope in all_patterns:
        text = head if scope == "head" else full
        if re.search(pat, text, re.IGNORECASE):
            return label

    return ""


# 向下相容 (舊名)
def detect_hard_blocker(jd_text: str) -> str:
    """保留舊名, 實作上同 detect_visa_signal"""
    return detect_visa_signal(jd_text)


# ─────────────────────────────────────────────────────────────
# Google Sheet 寫入
# ─────────────────────────────────────────────────────────────
def extract_sheet_id(url_or_id: str) -> str:
    """從完整 URL 或 raw ID 抓 sheet ID。"""
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{20,}", url_or_id):
        return url_or_id
    raise ValueError(f"看不出 sheet ID: {url_or_id!r}")


def extract_gid(url_or_id: str) -> str | None:
    m = re.search(r"[?&#]gid=(\d+)", url_or_id)
    return m.group(1) if m else None


# ─────────────────────────────────────────────────────────────
# Sheet 寫入輔助函數 (2026-08-23 重構抽出, 行為與原本一致)
# ─────────────────────────────────────────────────────────────
def build_e_formula(source: str, job_id: str, url: str = "") -> str:
    """構造 sheet E 欄的 =HYPERLINK() formula, 依 source 不同:
    - linkedin:    =HYPERLINK(".../jobPosting/{id}", "{id}")
    - jora:        =HYPERLINK("{full_jora_url}", "{full_jora_url}")  (DEPRECATED 2026-09-09: back-compat)
    - jobstreet:   =HYPERLINK(".../job/{id}", ".../job/{id}")  (2026-08-23 從 slug-id 改純 id)
    - onezerofour: =HYPERLINK(".../job/{slug}", ".../job/{slug}")  (2026-08-29 整合)
    - cake:        =HYPERLINK(".../companies/{page}/jobs/{path}", "same URL")
    """
    if source == "jora":
        # DEPRECATED 2026-09-09: Jora SG 關站, 保留這個 branch 讓既有 ~885 筆 sheet rows 的 E 欄
        # formula 仍能被 round-trip 解析 (雖然不會再有新 jora jobs)
        full_url = url or f"{JORA_BASE}/job/Product-Manager-{job_id}"
    elif source == "jobstreet":
        full_url = f"{JOBSTREET_BASE}/job/{job_id}"
    elif source == "onezerofour":
        full_url = url or f"{ONEZEROFOUR_BASE_URL}/job/{job_id}"
    elif source == "cake":
        full_url = url or f"{CAKE_WEB_BASE}/jobs/{job_id}"
    else:  # linkedin (default)
        full_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    return f'=HYPERLINK("{full_url}","{full_url}")'


def parse_sheet_row_to_key(row: list[str]) -> tuple[str, str] | None:
    """從 sheet 的某 row 解出 (source, job_id), 用於 dedup。

    輸入 row 格式: [A=New, B='', C=date, D=source_label, E=URL, F=company, G=title, H=JD, I=loc, J=wm, K=visa]
    D 欄解 source: "LinkedIn / Minimax" → linkedin, "Jora / Minimax" → jora  (DEPRECATED back-compat),
                   "JobStreet / Minimax" → jobstreet, "Cake / Minimax" → cake
    E 欄解 job_id: 依 source 不同用不同 regex (LinkedIn digit / jobPosting/digit / Jora 32-hex / JobStreet /job/digit / Cake companies/.../jobs/...)

    DEPRECATED 2026-09-09: jora 解析邏輯保留給既有 ~885 筆 sheet rows, 確保 dedup 仍能 round-trip
    (active crawling 不再產 jora jobs)。

    Returns None 如果 row 沒 E 欄或解不出 job_id (e.g. J 欄空 + 沒 K 欄的 header row).
    """
    if len(row) < 5 or not row[4].strip():
        return None
    d_cell = row[3].strip() if len(row) > 3 else ""
    if "JobStreet" in d_cell:
        src = "jobstreet"
    # DEPRECATED 2026-09-09: Jora SG 關站, 保留 "Jora" D 欄解析給舊 sheet rows dedup
    elif "Jora" in d_cell:
        src = "jora"
    elif "Cake" in d_cell:
        src = "cake"
    elif "104" in d_cell:
        src = "onezerofour"
    else:
        src = "linkedin"
    cell = row[4].strip()
    # 從 E 欄解 job_id
    if cell.isdigit():
        return (src, cell)
    # LinkedIn formula: =HYPERLINK(".../jobPosting/123","123")
    m = re.search(r"jobPosting/(\d+)", cell)
    if m:
        return (src, m.group(1))
    # Cake: /companies/{page}/jobs/{job_path}
    m = re.search(r"/companies/[^/]+/jobs/([^/?#]+)", cell)
    if m:
        return ("cake", m.group(1))
    # Cake: generic /jobs/{job_path}
    m = re.search(r"/jobs/([^/?#]+)", cell)
    if m and "cake.me" in cell.lower():
        return ("cake", m.group(1))
    # DEPRECATED 2026-09-09: Jora SG 關站, 保留 32-char hex 解析給舊 sheet rows dedup
    # (active crawling 不再產 jora, 但舊 ~885 筆仍要在 dedup 邏輯裡 round-trip)
    m = re.search(r"([a-f0-9]{32})/?(?:\?|$)", cell)
    if m:
        return ("jora", m.group(1))  # 強制 jora
    # JobStreet: /job/{digit} 純 id (2026-08-23 改後格式)
    m = re.search(r"/job/(\d+)/?(?:\?|$)", cell)
    if m and "jobstreet" in cell.lower():
        return ("jobstreet", m.group(1))
    # 104: /job/{4-6 char alphanumeric slug} (2026-08-28 整合, 主要是 5 char 但 4/6 也可能)
    # trailing slash 容忍: list parser 會 strip, sheet key parser 也要一致
    m = re.search(r"/job/([a-z0-9]{4,6})/?(?:\?|$)", cell, re.IGNORECASE)
    if m:
        return (src, m.group(1))
    return None


def push_to_sheet(
    jobs: list[dict],
    sheet_url: str,
    sa_key_path: str = SHEET_SA_KEY,
    source: str = DEFAULT_SHEET_SOURCE,
    dry_run: bool = False,
    timeout_s: int = 120,
    gid: str | int | None = None,
    location: str = LOCATION,
) -> dict:
    """
    把 jobs 寫到 Google Sheet。
    欄位對應: A=New, C=今天, D=source, E=API URL hyperlink, F=公司, G=職稱,
              H=JD, I=地點, K=hard blocker marker; B/J 留空。
    去重: 跳過已存在的 E (Job URL)。

    Visa detection 只對 Singapore 跑 (TW/CN 不檢查, 工作簽限制不常見)

    gid 解析順序: explicit `gid` arg > URL 內 `#gid=` / `?gid=` > SG_RAW_GID (default)。
    URL 沒帶 gid 也不傳 arg → 直接 raise（避免默默寫到第一個 tab = jobs_raw）。

    2026-08-23 重構: 拆 3 個 helper 函數 (`_load_sheet_keys` / `_build_sheet_row` / `_write_rows_to_sheet`),
    原本 186 行的單一函數, 拆成 60+30+30 行的 3 個函數 + 60 行的 orchestrator

    timeout_s (2026-08-29): 預設 120s, 用 subprocess 包起來避免 gspread hang 整個 run。
    跟 pre_dedup_jobs_against_sheet 一樣的問題: urllib3 socket I/O 不吃 timeout 設定,
    只有 subprocess.terminate() 真的能 kill。timeout_s=0 時 in-process (給 test mock 用)。
    """

    # 2026-08-29: 生產模式 wrap 在 subprocess, 真的能 kill
    if timeout_s > 0 and not dry_run:
        result = _push_to_sheet_with_subprocess(jobs, sheet_url, sa_key_path, source, gid, location, timeout_s)
        if result is not None:
            return result
        # subprocess 失敗 → 走 in-process fallback (會 hang 但至少 try 一次)
        print("  [PUSH SUBPROCESS WARN] fallback 到 in-process (可能 hang)", flush=True)

    import gspread
    from google.oauth2.service_account import Credentials

    sheet_id = extract_sheet_id(sheet_url)
    resolved_gid = gid if gid is not None else extract_gid(sheet_url)
    if resolved_gid is None:
        raise ValueError(
            "❌ 沒帶 gid 會撞到 jobs_raw (第一個 tab)\n"
            "   修法: URL 帶 #gid=<SG_RAW_GID>  或  --gid <SG_RAW_GID>  或  --to-sheet 用 SG_RAW_URL"
        )
    gid = str(resolved_gid)

    if dry_run:
        print("  [DRY RUN] 不會真的寫入")
        print(f"  sheet_id: {sheet_id[:20]}...")
        print(f"  gid: {gid}")
        print(f"  source label = {source!r}")
        print(f"  共 {len(jobs)} 筆準備寫入 (after skip/dedup/visa)")
        for j in jobs[:3]:
            e_preview = build_e_formula(j.get("source", "linkedin"), j.get("job_id", ""), j.get("url", ""))
            print(f"    [preview] title={j.get('title', '')[:35]:35}  E={e_preview}")
        return {"written": 0, "skipped_dup": 0, "dry_run": True}

    # 1) 認證 + 開 sheet
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(sa_key_path), scopes=scopes)
    # 2026-09-01 fix: 原本 `_make_gspread_session()` 回 custom requests.Session 會讓 gspread 6.x
    # 丟失 OAuth Authorization header → Google Sheets API 回 403 unregistered callers。
    # 改成 return None 用 gspread default client (auth 正常), timeout 由 _apply_http_timeout 控。
    gc = gspread.authorize(creds, session=_make_gspread_session())
    _apply_http_timeout(gc, timeout=30)
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet_by_id(int(gid))
    print(f"  工作表: {ws.title!r}, 目前 row_count: {ws.row_count}")

    # 2) 讀現有 (source, job_id) keys + 找下一個空白 row
    existing = ws.get_all_values()
    existing_keys, next_row = _load_sheet_keys(existing)
    print(f"  既有 (source, job_id) 數: {len(existing_keys)}")
    print(f"  下一個空白 row: {next_row}")

    # 3) 組 rows (dedup, visa, work mode, formula) — 用 _build_sheet_row helper
    new_rows = []
    skipped_dup = 0
    skipped_no_jd = 0
    for j in jobs:
        row = _build_sheet_row(j, source, location, existing_keys)
        if row is None:
            # 判斷是 dedup 還是 no_jd
            job_id = j.get("job_id", "")
            if job_id and (j.get("source", "linkedin"), job_id) in existing_keys:
                skipped_dup += 1
            else:
                skipped_no_jd += 1
            continue
        new_rows.append(row)
        existing_keys.add((j.get("source", "linkedin"), j.get("job_id", "")))  # 同 run 內 dedup

    # 4) 寫入 (或無 rows 就直接 return)
    if not new_rows:
        return {
            "written": 0,
            "skipped_dup": skipped_dup,
            "skipped_no_jd": skipped_no_jd,
            "next_row": next_row,
        }
    return _write_rows_to_sheet(ws, next_row, new_rows, skipped_dup, skipped_no_jd)


def _load_sheet_keys(existing: list[list[str]]) -> tuple[set[tuple[str, str]], int]:
    """從 sheet 現有 rows 解出 (source, job_id) set + 下一個空白 row 編號。
    Returns: (existing_keys, next_row)
    """
    existing_keys: set[tuple[str, str]] = set()
    for row in existing[1:]:
        key = parse_sheet_row_to_key(row)
        if key:
            existing_keys.add(key)
    # 找下一個空白 row
    next_row = None
    for i, row in enumerate(existing, 1):
        if i == 1:
            continue
        if not any(c.strip() for c in row):
            next_row = i
            break
    if next_row is None:
        next_row = len(existing) + 1
    return existing_keys, next_row


def _load_sheet_keys_for_source(
    sheet_source_label: str, sa_key_path: str = SHEET_SA_KEY, sheet_id: str = ""
) -> tuple[set[tuple[str, str]], int]:
    """讀指定 sheet tab 的 (source, job_id) keys + 下一個空白 row (B 階段 2026-08-29 加,
    A 整合版 2026-08-29 抽出來共用給 pre-dedup 跟 push_to_sheet)。

    Args:
        sheet_source_label: "LinkedIn / Minimax" / ~~"Jora / Minimax"~~ (DEPRECATED 2026-09-09, back-compat only) /
                            "JobStreet / Minimax" / "104 / Minimax" / "Cake / Minimax"
        sa_key_path: SA key 路徑 (預設 SHEET_SA_KEY)
        sheet_id: Sheet ID (留空用 SG_RAW_SHEET_ID 預設；104/Cake 與 SG sources 使用同一 Spreadsheet 的 TW/SG 不同 tab)

    Returns: (existing_keys, next_row)
    Raises: gspread 任何錯誤往上拋 (caller 決定 fail-safe 或 fail-closed)
    """
    import gspread
    from google.oauth2.service_account import Credentials

    LABEL_TO_GID = {
        "LinkedIn / Minimax": SG_RAW_GID,
        # DEPRECATED 2026-09-09: Jora SG 關站, 保留 entry 給既有 ~885 筆 sheet rows migration
        # (不會再有新 jora jobs, 但 audit/migration 工具可能仍要解析 "Jora / Minimax" label)
        "Jora / Minimax": SG_RAW_GID,
        "JobStreet / Minimax": SG_RAW_GID,
        "Cake / Minimax": CAKE_TW_RAW_GID,
        "104 / Minimax": ONEZEROFOUR_TW_RAW_GID,
    }
    gid = LABEL_TO_GID.get(sheet_source_label)
    if gid is None:
        raise ValueError(f"未知 sheet_source_label {sheet_source_label!r}, 預期 {list(LABEL_TO_GID.keys())}")

    if not sheet_id:
        sheet_id = SG_RAW_SHEET_ID
    if not sheet_id:
        raise ValueError("SHEET_ID 沒設, 沒辦法讀 sheet")

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(str(sa_key_path), scopes=scopes)
    # 2026-09-01 fix: 原本 `_make_gspread_session()` 回 custom requests.Session 會讓 gspread 6.x
    # 丟失 OAuth Authorization header → Google Sheets API 回 403 unregistered callers。
    # 改成 return None 用 gspread default client (auth 正常), timeout 由 _apply_http_timeout 控。
    gc = gspread.authorize(creds, session=_make_gspread_session())
    _apply_http_timeout(gc, timeout=30)
    sh = gc.open_by_key(sheet_id)
    ws = sh.get_worksheet_by_id(int(gid))
    existing = ws.get_all_values()
    return _load_sheet_keys(existing)


def _make_gspread_session():
    """2026-09-01 fix: 原本 return 一個自訂 requests.Session 帶 retry adapter,
    但會讓 gspread 6.x 的 HTTP call 丟失 OAuth Authorization header,
    Google Sheets API 收到「沒帶身分證」的 request 就回 403 (unregistered callers)。

    修法: 直接 return None, 讓 gspread 用它自己的 default client (會正確帶 auth header)。
    HTTP timeout 仍由 `_apply_http_timeout` 透過 `gc.http_client.set_timeout(30)` 設, 跟這個 helper 無關。
    retry 行為本來就只在 status 5xx 才觸發, 但 403 是 4xx → 沒 retry 過就 fail, 沒差。
    """
    return None


def _apply_http_timeout(gc, timeout: int = 30) -> None:
    """2026-08-29 加: 在 gspread client 上設 HTTP timeout (call .http_client.set_timeout())。
    沒設這個 → gspread 預設 timeout=None → 網路不穩會無限 hang。
    """
    if hasattr(gc, "http_client") and hasattr(gc.http_client, "set_timeout"):
        gc.http_client.set_timeout(timeout)


def pre_dedup_jobs_against_sheet(
    jobs: list[dict],
    sheet_source_label: str,
    *,
    sa_key_path: str = SHEET_SA_KEY,
    dry_run: bool = False,
    timeout_s: int = 60,
) -> list[dict]:
    """Pre-detail sheet dedup (B 階段 2026-08-29 優化, A 整合版 2026-08-29 補上 main() 流程):

    進 detail fetch 之前, 先讀 sheet 既有 (source, job_id) keys, 跳過已存在的 jobs。
    適用於「重跑同 range」(sheet 已有大量 jobs), 第一次跑 sheet 是空的就跳 0 個。

    Returns: 過濾後的 jobs list (保留既有順序)
    Fail-safe: 讀 sheet 失敗 (網路 / 認證 / 找不到 / timeout) → 不擋, 全部 jobs 通過

    timeout_s (2026-08-29): 預設 60s 外層 timeout, 透過 multiprocessing 跑 gspread 在獨立
    subprocess 裡, timeout 真的能 kill 整個 subprocess (signal.SIGALRM 在 urllib3 C-level
    socket 跟 thread.interrupt_main() 在 gspread 全無效, 只能靠 subprocess.terminate())。
    timeout_s=0 時 in-process 呼叫 (給 test mock 用)。
    """
    if dry_run or not jobs:
        return jobs

    existing_keys: set = set()
    load_ok = True
    if timeout_s > 0:
        # 生產模式: 用 subprocess 包 gspread, 真的能 kill
        existing_keys, load_ok = _pre_dedup_load_with_subprocess(sheet_source_label, sa_key_path, timeout_s)
        if not load_ok:
            return jobs
    else:
        # 測試模式: in-process 呼叫, 可被 mock
        try:
            existing_keys, _ = _load_sheet_keys_for_source(sheet_source_label, sa_key_path=sa_key_path)
        except Exception as e:
            print(f"  [PRE-DEDUP WARN] 讀 sheet 失敗 ({type(e).__name__}: {e}), 跳過這層 dedup", flush=True)
            return jobs

    before = len(jobs)
    filtered = [j for j in jobs if (j.get("source", ""), str(j.get("job_id", ""))) not in existing_keys]
    skipped = before - len(filtered)
    print(
        f"  [PRE-DEDUP] {skipped}/{before} 跳過 (已在 sheet {sheet_source_label}), {len(filtered)} 進 detail",
        flush=True,
    )
    return filtered


def _pre_dedup_load_with_subprocess(sheet_source_label: str, sa_key_path: str, timeout_s: int) -> tuple[set, bool]:
    """2026-08-29 加: 跑 _load_sheet_keys_for_source 在獨立 subprocess, timeout 真的能 kill。
    返回 (existing_keys, success_flag)。失敗時 success_flag=False, existing_keys 為空 set。
    """
    import json as _json
    import os as _os
    import subprocess as _sp
    import sys as _sys
    import tempfile as _tf

    # 寫 worker script (獨立 process, 不繼承 main process 的 mock)
    worker_code = f"""
import sys, json
sys.path.insert(0, {_json.dumps(_os.getcwd())})
import sg_product_jobs as M
out_path = {_json.dumps("{TMP_OUT_PATH_PLACEHOLDER}")}
try:
    existing, next_row = M._load_sheet_keys_for_source(
        {_json.dumps(sheet_source_label)},
        sa_key_path={_json.dumps(str(sa_key_path))},
    )
    with open(out_path, "w") as f:
        json.dump({{"ok": True, "keys": [list(k) for k in existing]}}, f, ensure_ascii=False)
except Exception as e:
    with open(out_path, "w") as f:
        json.dump({{"ok": False, "error": f"{{type(e).__name__}}: {{e}}"}}, f, ensure_ascii=False)
"""
    with _tf.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        worker_path = f.name
    out_path = worker_path + ".out"
    # 替換 placeholder
    final_code = worker_code.replace("{TMP_OUT_PATH_PLACEHOLDER}", out_path)
    with open(worker_path, "w") as f:
        f.write(final_code)

    try:
        proc = _sp.run(
            [_sys.executable, worker_path],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            print(f"  [PRE-DEDUP WARN] worker exit {proc.returncode}: {proc.stderr[:200]}", flush=True)
            return set(), False
        with open(out_path) as f:
            result = _json.load(f)
        if not result.get("ok"):
            print(f"  [PRE-DEDUP WARN] worker fail: {result.get('error', 'unknown')}", flush=True)
            return set(), False
        return {tuple(k) for k in result["keys"]}, True
    except _sp.TimeoutExpired:
        print(
            f"  [PRE-DEDUP WARN] 讀 sheet 超過 {timeout_s}s timeout (subprocess 真的被 kill), 跳過這層 dedup",
            flush=True,
        )
        return set(), False
    except Exception as e:
        print(f"  [PRE-DEDUP WARN] 讀 sheet 失敗 ({type(e).__name__}: {e}), 跳過這層 dedup", flush=True)
        return set(), False
    finally:
        for p in [worker_path, out_path]:
            try:
                _os.unlink(p)
            except OSError:
                pass


def _push_to_sheet_with_subprocess(jobs, sheet_url, sa_key_path, source, gid, location, timeout_s):
    """2026-08-29 加: 跑 push_to_sheet 在獨立 subprocess, timeout 真的能 kill。
    跟 _pre_dedup_load_with_subprocess 一樣的 pattern。
    返回 push_to_sheet 的 result dict, 或 None 表示失敗。
    """
    import json as _json
    import os as _os
    import subprocess as _sp
    import sys as _sys
    import tempfile as _tf

    # 序列化 jobs (要傳給 subprocess)
    jobs_json = _json.dumps(jobs, ensure_ascii=False, default=str)
    worker_code = f"""
import sys, json
sys.path.insert(0, {_json.dumps(_os.getcwd())})
import sg_product_jobs as M
out_path = {_json.dumps("{PUSH_OUT_PATH_PLACEHOLDER}")}
try:
    jobs = json.loads({_json.dumps(jobs_json)})
    result = M.push_to_sheet(
        jobs,
        {_json.dumps(sheet_url)},
        sa_key_path={_json.dumps(str(sa_key_path))},
        source={_json.dumps(source)},
        gid={_json.dumps(gid)},
        location={_json.dumps(location)},
        timeout_s=0,  # 內層走 in-process 避免 recursive subprocess
    )
    with open(out_path, "w") as f:
        json.dump({{"ok": True, "result": result}}, f, ensure_ascii=False, default=str)
except Exception as e:
    import traceback
    with open(out_path, "w") as f:
        json.dump({{"ok": False, "error": f"{{type(e).__name__}}: {{e}}", "tb": traceback.format_exc()}}, f, ensure_ascii=False)
"""
    with _tf.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        worker_path = f.name
    out_path = worker_path + ".out"
    final_code = worker_code.replace("{PUSH_OUT_PATH_PLACEHOLDER}", out_path)
    with open(worker_path, "w") as f:
        f.write(final_code)

    try:
        proc = _sp.run(
            [_sys.executable, worker_path],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            print(f"  [PUSH SUBPROCESS WARN] worker exit {proc.returncode}: {proc.stderr[:200]}", flush=True)
            return None
        with open(out_path) as f:
            result = _json.load(f)
        if not result.get("ok"):
            print(f"  [PUSH SUBPROCESS WARN] worker fail: {result.get('error', 'unknown')}", flush=True)
            return None
        return result.get("result", {})
    except _sp.TimeoutExpired:
        print(f"  [PUSH SUBPROCESS WARN] 寫 sheet 超過 {timeout_s}s timeout (subprocess 真的被 kill)", flush=True)
        return None
    except Exception as e:
        print(f"  [PUSH SUBPROCESS WARN] 寫 sheet 失敗 ({type(e).__name__}: {e})", flush=True)
        return None
    finally:
        for p in [worker_path, out_path]:
            try:
                _os.unlink(p)
            except OSError:
                pass


def _is_singapore_location(value: str | None) -> bool:
    """Return True when a row-level location clearly names Singapore."""
    if not value:
        return False
    return re.search(r"\bsingapore\b", str(value), re.IGNORECASE) is not None


def _build_sheet_row(job: dict, source_label: str, location: str, existing_keys: set[tuple[str, str]]) -> list | None:
    """把一個 job dict 構造為 11 欄 sheet row。

    Returns None 表示要跳過 (dedup 命中 或 沒 JD); 否則回傳 11 欄 list。
    跳過原因要從呼叫端用 existing_keys 跟 jd_text 判斷 (這裡只負責構造 row)。
    """
    from datetime import date

    job_id = job.get("job_id", "")
    if not job_id:
        return None
    job_source = job.get("source", "linkedin")
    if (job_source, job_id) in existing_keys:
        return None
    jd_text = job.get("jd_text") or ""
    if not jd_text:
        return None
    # Repair11: prefer the job's actual row Location; source scope is fallback only.
    effective_location = (job.get("location") or location or "").strip()
    if _is_singapore_location(effective_location):
        visa = detect_visa_signal(jd_text)
    else:
        visa = ""
    jd_oneline = re.sub(r"\s+", " ", jd_text).strip()
    work_mode = job.get("work_mode", "") or extract_work_mode(jd_text, job.get("title", ""))
    e_formula = build_e_formula(job_source, job_id, job.get("url", ""))
    return [
        "New",  # A
        "",  # B (留空)
        date.today().isoformat(),  # C
        source_label,  # D
        e_formula,  # E (含超連結)
        job.get("company", ""),  # F
        job.get("title", ""),  # G
        jd_oneline,  # H (單行, 自動裁切)
        job.get("location", ""),  # I
        work_mode,  # J (Remote/Hybrid/Onsite)
        visa,  # K
    ]


def _write_rows_to_sheet(ws, next_row: int, new_rows: list[list], skipped_dup: int = 0, skipped_no_jd: int = 0) -> dict:
    """把 new_rows 寫到 sheet, 回傳 stats dict (跟原本 push_to_sheet 一樣格式)。

    三段式寫入 (防 F10 公式注入，且 intentional formula 最後才啟用):
      - Phase 1: A:D 用 RAW
      - Phase 2: F:K 用 RAW
      - Phase 3: E 欄 hyperlink formula 用 USER_ENTERED
    只有我們自己生成的 E 欄 HYPERLINK 會被當公式, 其他所有外部 scraped text
    (title / company / JD / location / source label / visa) 都不能被當公式執行。
    """
    end_row = next_row + len(new_rows) - 1
    print(f"  準備寫入 row {next_row}-{end_row} ({len(new_rows)} 筆, 三段式寫入防公式注入)...")
    # 防呆: 自動擴展 sheet rows (避免 end_row > row_count 報 400)
    if end_row > ws.row_count:
        extra = end_row - ws.row_count + 100
        print(f"  ⚠️  sheet 只有 {ws.row_count} rows, 加 {extra} rows 避免 overflow")
        ws.add_rows(extra)
    # External scraped text is written first as RAW. If a later data phase fails,
    # the E-column live formula is never activated.
    a_d_rows = [[r[i] for i in (0, 1, 2, 3)] for r in new_rows]  # A,B,C,D
    f_k_rows = [[r[i] for i in (5, 6, 7, 8, 9, 10)] for r in new_rows]  # F,G,H,I,J,K
    e_only_rows = [[r[4]] for r in new_rows]  # E
    ws.update(
        range_name=f"A{next_row}:D{end_row}",
        values=a_d_rows,
        value_input_option="RAW",
    )
    ws.update(
        range_name=f"F{next_row}:K{end_row}",
        values=f_k_rows,
        value_input_option="RAW",
    )
    # Intentional formula is the final phase.
    ws.update(
        range_name=f"E{next_row}:E{end_row}",
        values=e_only_rows,
        value_input_option="USER_ENTERED",
    )
    return {
        "written": len(new_rows),
        "skipped_dup": skipped_dup,
        "skipped_no_jd": skipped_no_jd,
        "next_row": next_row,
        "end_row": end_row,
    }


# ─────────────────────────────────────────────────────────────
# 列表頁
# ─────────────────────────────────────────────────────────────
JOB_CARD_SEL = "div.base-card"
TITLE_SEL = ".base-search-card__title"
COMPANY_SEL = "a.hidden-nested-link"
LOC_SEL = ".job-search-card__location"
TIME_SEL = "time"
LINK_SEL = "a.base-card__full-link"


def _clean(text_list) -> str:
    return " ".join(t.strip() for t in text_list if t and t.strip()).strip()


def build_list_url(tpr: str, start: int, location: str = LOCATION, geo_id: str = GEO_ID) -> str:
    params = {
        "keywords": KEYWORDS,
        "location": location,
        "geoId": geo_id,
        "f_TPR": tpr,
        "sortBy": "DD",
        "start": str(start),
    }
    return "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)


def parse_list_page(html: str) -> list[dict]:
    page = Adaptor(html)
    jobs = []
    for card in page.css(JOB_CARD_SEL):
        urn = (card.attrib.get("data-entity-urn") or "").strip()
        job_id = urn.rsplit(":", 1)[-1] if urn else ""

        title = _clean(card.css(TITLE_SEL + "::text").getall())
        company = _clean(card.css(COMPANY_SEL + "::text").getall())
        loc = _clean(card.css(LOC_SEL + "::text").getall())

        time_node = card.css(TIME_SEL)
        posted_at = ""
        posted_ago = ""
        if time_node:
            t = time_node[0]
            posted_at = (t.attrib.get("datetime") or "").strip()
            posted_ago = _clean(t.css("::text").getall())

        link_nodes = card.css(LINK_SEL)
        href = (link_nodes[0].attrib.get("href") if link_nodes else "") or ""

        if not job_id and not title:
            continue
        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "company": company,
                "location": loc,
                "posted_at": posted_at,
                "posted_ago": posted_ago,
                "url": href or f"https://www.linkedin.com/jobs/view/{job_id}",
                "source": "linkedin",  # 讓 push_to_sheet / enrich_with_jd 知道
            }
        )
    return jobs


def fetch_list_page(tpr: str, start: int, location: str = LOCATION, geo_id: str = GEO_ID) -> str:
    """LinkedIn list page 帶 30/60/90s retry (對齊 cake/104 pattern, RULES §15.13 #11)。

    2026-10-07 fix: 原本沒 retry, list page 撞 429 → r.raise_for_status() → HTTPError
    → crawl_list line 2053 return all_jobs → 整個 list crawl hard abort。
    Sep 30 14d run 撞 page 13 abort, Oct 07 14d 撞 page 7 abort, 兩次都只跑 6-12 頁 (~57 jobs),
    coverage 嚴重不完整。Retry 後單頁最多撐 3.5 分鐘 (30+60+90 backoff)。

    429 / 5xx / connection error → sleep 30/60/90s → retry (共 4 次 attempt)。
    4xx (非 429) 直接 raise, 視為 caller bug。
    Raises: RuntimeError if all retries exhausted.
    """
    backoff = [30, 60, 90]
    last_err = None
    url = build_list_url(tpr, start, location, geo_id)
    for attempt in range(4):
        try:
            r = _cc_session.get(
                url,
                impersonate="chrome",
                timeout=20,
                headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            if r.status_code == 200:
                return r.text
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                r.raise_for_status()
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < 3:
            print(
                f"    [LINKEDIN LIST RETRY {attempt + 1}/3] start={start} 失敗 ({last_err}), sleep {backoff[attempt]}s",
                flush=True,
            )
            time.sleep(backoff[attempt])
    raise RuntimeError(f"linkedin list fetch failed after 4 attempts: {last_err}")


# ─────────────────────────────────────────────────────────────
# JD 抓取 (可選)
# ─────────────────────────────────────────────────────────────
JD_DESC_SEL = "div.description__text"
JD_BLOCK_SEL = (
    "div.description__text p, div.description__text li, "
    "div.description__text h1, div.description__text h2, "
    "div.description__text h3, div.description__text h4, "
    "div.description__text strong, div.description__text span"
)


def build_jd_url(job_id: str) -> str:
    return f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"


def fetch_jd(job_id: str) -> dict:
    """抓單一職缺的 JD 純文字。"""
    try:
        r = _cc_session.get(
            build_jd_url(job_id),
            impersonate="chrome",
            timeout=20,
            headers={"Accept-Language": "en-US,en;q=0.9"},
        )
    except Exception as e:
        return {"jd_text": None, "jd_html": None, "error": f"{type(e).__name__}: {e}"}

    if r.status_code == 429:
        return {"jd_text": None, "jd_html": None, "error": "429 rate limited"}
    if r.status_code != 200:
        return {"jd_text": None, "jd_html": None, "error": f"HTTP {r.status_code}"}

    ap = Adaptor(r.text)
    desc_nodes = ap.css(JD_DESC_SEL)
    if not desc_nodes:
        return {"jd_text": None, "jd_html": None, "error": "no description node found"}

    desc = desc_nodes[0]
    # ★ 抓全部 ::text (包含裸文字節點，不只 p/li/h*/strong)
    all_text = desc.css("::text").getall()
    lines = []
    for t in all_text:
        t = t.strip()
        if t and len(t) > 1:
            lines.append(t)
    # 結構化版本 (給想看分段的)
    structured_lines = []
    for p in desc.css(JD_BLOCK_SEL):
        t = (p.css("::text").get() or "").strip()
        if t and len(t) > 1:
            structured_lines.append(t)

    return {
        "jd_text": "\n".join(lines) if lines else None,
        "jd_lines": structured_lines if structured_lines else lines,
        "jd_html": None,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────
def human_sleep(label: str = ""):
    s = random.uniform(SLEEP_MIN, SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    time.sleep(s)


# Cake 專用 sleep (2026-08-30 加): 跟全域同 3.0-10.0s, 2-5s 測試發現 14 page 就 429
# 跟全域 SLEEP_MIN/SLEEP_MAX 隔開, 之後如要調 sleep 改這裡就好
CAKE_SLEEP_MIN = 3.0
CAKE_SLEEP_MAX = 10.0


def cake_human_sleep(label: str = ""):
    s = random.uniform(CAKE_SLEEP_MIN, CAKE_SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    time.sleep(s)


def crawl_list(tpr: str, max_pages: int, location: str = LOCATION, geo_id: str = GEO_ID) -> list[dict]:
    seen: set[str] = set()
    all_jobs: list[dict] = []
    # FIX 2026-09-23: LinkedIn 偶爾 page 只回 9 card (relevance ranking, 不是 EOF).
    # 舊邏輯 `len(jobs) < PAGE_SIZE` 會誤判截斷, 改成連續 2 頁 0 new jobs 才視為 EOF.
    empty_streak = 0

    for p in range(max_pages):
        start = p * PAGE_SIZE
        print(f"\n  [list page {p + 1}] start={start}")
        try:
            html = fetch_list_page(tpr, start, location, geo_id)
        except Exception as e:
            print(f"            FAIL: {type(e).__name__}: {e}")
            return all_jobs
        Path(f"raw_list_{p + 1}.html").write_text(html)
        jobs = parse_list_page(html)
        new_jobs = [j for j in jobs if j["job_id"] not in seen]
        for j in new_jobs:
            seen.add(j["job_id"])
            all_jobs.append(j)
        print(
            f"            收 {len(jobs)}, 新增 {len(new_jobs)}, 重複 {len(jobs) - len(new_jobs)}, 累計 {len(all_jobs)}"
        )
        if not new_jobs:
            empty_streak += 1
            if empty_streak >= 2:
                print(f"            到底了 (連續 {empty_streak} 頁 0 new jobs)")
                break
        else:
            empty_streak = 0
        if p < max_pages - 1:
            human_sleep("list")

    return all_jobs


# ─────────────────────────────────────────────────────────────
# Jora (sg.jora.com) — DEPRECATED 2026-09-09: Jora SG 關站
# build_jora_list_url / parse_jora_list_page / fetch_jora_jd / crawl_jora_list 全部移除
# (sg.jora.com 已永久 410, 不再有 active crawling)
# 保留: JORA_BASE 常數 + build_e_formula("jora", ...) 分支 + parse_sheet_row_to_key 內的
# "Jora / Minimax" + 32-hex URL 解析 + LABEL_TO_GID["Jora / Minimax"], 確保既有 ~885 筆
# sheet rows 跟 seen_jds.jsonl 仍能 dedup round-trip (見上方函數的 DEPRECATED 註解)
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# JobStreet SG 來源 (sg.jobstreet.com) — 2026-08-22 整合
# 公開 List API + GraphQL, 不需 Cloudflare solve; HTML 頁 100% 擋, 走 GraphQL 拿 content
# ─────────────────────────────────────────────────────────────
JOBSTREET_DETAIL_QUERY = """
query getJobDetails($jobId: ID!) {
  jobDetails(id: $jobId) {
    job {
      id
      title
      abstract
      content
      status
      isExpired
      createdAt { dateTimeUtc }
      updatedAt { dateTimeUtc }
      expiresAt { dateTimeUtc }
      advertiser { id name }
      location { label }
      workTypes { label }
    }
  }
}
"""


def build_jobstreet_list_url(
    keyword: str,
    page: int,
    daterange: str,
    worktype: str = JOBSTREET_WORKTYPE_FT,
    where: str = JOBSTREET_LOCATION,
    page_size: int = 20,
) -> str:
    """組 JobStreet list API URL。"""
    import urllib.parse

    params = {
        "siteKey": "SG-Main",
        "keywords": keyword,
        "where": where,
        "worktype": worktype,
        "daterange": str(daterange),
        "page": str(page),
        "pageSize": str(page_size),
    }
    return f"{JOBSTREET_LIST_API}?{urllib.parse.urlencode(params)}"


def parse_jobstreet_list_page(data: dict, keyword: str) -> list[dict]:
    """從 JobStreet list API JSON 抓 jobs。"""
    jobs_raw = data.get("data") or []
    out = []
    for j in jobs_raw:
        jid = j.get("id")
        if not jid:
            continue
        # 公司優先用 employer.name, 退到 advertiser.description
        emp = j.get("employer") or {}
        adv = j.get("advertiser") or {}
        company = emp.get("name") or adv.get("description") or j.get("companyName") or ""
        # locations → 用第一個 label
        locs = j.get("locations") or []
        loc_label = locs[0].get("label", "") if locs else ""
        # workArrangements (Remote / Hybrid / Onsite) — 2026-08-23 統一 "Onsite" 沒 hyphen
        wm = ""
        wa = (j.get("workArrangements") or {}).get("data") or []
        if wa and isinstance(wa, list) and wa[0].get("label"):
            wm = wa[0]["label"].get("text", "")
            wm = wm.replace("On-site", "Onsite")  # JobStreet API 給 "On-site" 統一轉 "Onsite"
        out.append(
            {
                "job_id": str(jid),
                "title": j.get("title", ""),
                "company": company,
                "location": loc_label,
                "posted_at": j.get("listingDate", ""),
                "posted_ago": j.get("listingDateDisplay", ""),
                "work_mode": wm,
                "teaser": j.get("teaser", ""),
                "url": "",  # 不在 list 階段組, enrich 階段補 (要用 title slug)
                "keyword_used": keyword,  # debug 用, 哪個 keyword 撈到的
                "source": "jobstreet",
            }
        )
    return out


def fetch_jobstreet_jd(job_id: str) -> dict:
    """打 GraphQL 拿單一職缺完整 content (HTML JD), BS4 轉純文字。"""
    try:
        r = _cc_session.post(
            JOBSTREET_GRAPHQL,
            json={"query": JOBSTREET_DETAIL_QUERY, "variables": {"jobId": str(job_id)}},
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"},
            timeout=30,
            impersonate="chrome",
        )
    except Exception as e:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": str(e),
        }
    if r.status_code != 200:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"HTTP {r.status_code}",
        }
    try:
        data = r.json()
    except Exception as e:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": f"JSON fail: {e}",
        }
    if "errors" in data:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": str(data["errors"][:1]),
        }
    job = (data.get("data") or {}).get("jobDetails", {}).get("job")
    if not job:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": "no job in response",
        }
    # content (HTML) → plain text
    content_html = job.get("content") or ""
    if content_html:
        soup = BeautifulSoup(content_html, "html.parser")
        jd_text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()
        jd_lines = [t.strip() for t in soup.stripped_strings if len(t.strip()) > 1]
    else:
        jd_text = None
        jd_lines = None
    # 公司/位置 fallback (從 GraphQL 補)
    adv = job.get("advertiser") or {}
    loc = job.get("location") or {}
    return {
        "jd_text": jd_text,
        "jd_lines": jd_lines,
        "jd_html": content_html or None,
        "company": adv.get("name", ""),
        "location": (loc.get("label") if isinstance(loc, dict) else "") or "",
        "title": job.get("title", ""),
        "error": None if jd_text else "empty JD",
    }


def crawl_jobstreet_list(
    daterange: str, max_pages: int, keywords: list[str] | None = None, worktype: str = JOBSTREET_WORKTYPE_FT
) -> list[dict]:
    """跑多個 keyword 的 JobStreet list, 跨 keyword dedup。回傳 unique jobs。

    50% 軟停: 某頁 unique new jobs < pageSize * 0.5 就視為到尾。
    """
    if keywords is None:
        keywords = JOBSTREET_KEYWORDS
    seen: set[str] = set()
    all_jobs: list[dict] = []
    for kw in keywords:
        kw_seen: set[str] = set()
        for p in range(1, max_pages + 1):
            url = build_jobstreet_list_url(kw, p, daterange, worktype=worktype)
            try:
                r = _cc_session.get(url, timeout=20, impersonate="chrome")
            except Exception as e:
                print(f"  [jobstreet {kw} p{p}] FAIL: {type(e).__name__}: {e}")
                return all_jobs
            if r.status_code != 200:
                print(f"  [jobstreet {kw} p{p}] FAIL: HTTP {r.status_code}")
                return all_jobs
            try:
                data = r.json()
            except Exception as e:
                print(f"  [jobstreet {kw} p{p}] FAIL JSON: {e}")
                return all_jobs
            jobs = parse_jobstreet_list_page(data, kw)
            new_jobs = [j for j in jobs if j["job_id"] not in seen and j["job_id"] not in kw_seen]
            for j in new_jobs:
                kw_seen.add(j["job_id"])
                seen.add(j["job_id"])
                all_jobs.append(j)
            total_count = data.get("totalCount", "?")
            print(
                f"  [jobstreet {kw} p{p}] 收 {len(jobs):3} | 新增 {len(new_jobs):3} | kw 累計 {len(kw_seen):3} | 跨 kw 累計 {len(all_jobs):3} | totalCount={total_count}"
            )
            # 50% 軟停
            if not new_jobs or len(new_jobs) < 10 or len(jobs) == 0:
                print("            50% 軟停 (新增 < 10 或 jobs 空)")
                break
            if p < max_pages:
                human_sleep("list")
    return all_jobs


# ─────────────────────────────────────────────────────────────
# Cake (www.cake.me) — 2026-08-30 整合
# Search API 走 POST JSON; list response 內就帶完整 JD description
# detail page route: /companies/{page.path}/jobs/{path}
# ─────────────────────────────────────────────────────────────
def _cake_proxies() -> dict[str, str] | None:
    """從 env 讀 proxy。

    優先順序:
      1) CAKE_HTTP_PROXY
      2) HTTPS_PROXY / HTTP_PROXY / ALL_PROXY

    空字串或都沒設 → None
    """
    proxy = (
        os.getenv("CAKE_HTTP_PROXY", "").strip()
        or os.getenv("HTTPS_PROXY", "").strip()
        or os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("ALL_PROXY", "").strip()
    )
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return {"http": proxy, "https": proxy}


def _cake_headers(*, accept: str = "application/json", referer: str = "https://www.cake.me/") -> dict:
    """Cake API / HTML 共用 browser-like headers。"""
    headers = {
        "Accept": accept,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Content-Type": "application/json",
        "Origin": "https://www.cake.me",
        "Pragma": "no-cache",
        "Referer": referer,
        "Sec-Ch-Ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "User-Agent": "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36",
    }
    auth = os.getenv("CAKE_AUTHORIZATION", "").strip() or os.getenv("CAKE_BEARER_TOKEN", "").strip()
    if auth:
        headers["Authorization"] = auth if auth.lower().startswith("bearer ") else f"Bearer {auth}"
    session_id = os.getenv("CAKE_SEARCH_SESSION_ID", "").strip() or os.getenv("CAKE_X_SEARCH_SESSION_ID", "").strip()
    if session_id:
        headers["X-Search-Session-Id"] = session_id
    return headers


def _effective_cake_sort_by(sort_by: str | None, cutoff: "datetime | None") -> str:
    """Return the auditable Cake ordering for this crawl.

    Repair11 invariant: any crawl that uses a time cutoff MUST be newest-to-oldest.
    A stale/debug CAKE_SORT_BY value may still be used only when there is no cutoff.
    """
    requested = (sort_by or CAKE_SORT_BY or "latest").strip().lower()
    if cutoff is not None:
        return "latest"
    return requested or "latest"


def build_cake_search_payload(
    keyword: str,
    page: int,
    per_page: int = CAKE_PAGE_SIZE,
    sort_by: str = CAKE_SORT_BY,
    locations: list[str] | None = None,
    job_types: list[str] | None = None,
    seniority_levels: list[str] | None = None,
    job_source: list[str] | None = None,
) -> dict:
    """組 Cake search API POST payload。

    注意:
      - 這是 POST JSON，不是 query string
      - page 是 1-indexed
      - 現階段沒看到穩定的 date filter，所以 range 只拿來決定 max_pages
    """
    return {
        "query": keyword,
        "filters": {
            "job_source": job_source or CAKE_JOB_SOURCE,
            "job_types": job_types or CAKE_JOB_TYPES,
            "locations": locations or CAKE_LOCATIONS,
            "seniority_levels": seniority_levels or CAKE_SENIORITY_LEVELS,
        },
        "sort_by": sort_by,
        "page": page,
        "per_page": per_page,
    }


def build_cake_detail_url(page_path: str, job_path: str) -> str:
    """組 Cake public detail URL。"""
    return CAKE_DETAIL_PAGE_URL.format(page_path=page_path, job_path=job_path)


def _cake_text_from_html(html: str) -> str:
    """盡量從 Cake detail HTML 抽純文字。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def parse_cake_search_page(data: dict, keyword: str) -> list[dict]:
    """從 Cake search API JSON 轉成內部 job dict。"""
    jobs_raw = data.get("data") or []
    out = []
    for j in jobs_raw:
        job_path = j.get("path") or ""
        page = j.get("page") or {}
        page_path = page.get("path") or ""
        if not job_path or not page_path:
            continue
        description = j.get("description") or ""
        locs = j.get("locations") or []
        if isinstance(locs, list) and locs:
            loc = locs[0]
        else:
            loc = (page.get("geo") or {}).get("state_name", "") or ""
        out.append(
            {
                "job_id": job_path,  # Cake 的穩定 identifier: public detail URL path
                "path": job_path,
                "title": (j.get("title") or "").strip(),
                "company": page.get("name", "") or "",
                "location": loc,
                "posted_at": j.get("content_updated_at", ""),
                "url": build_cake_detail_url(page_path, job_path),
                "work_mode": extract_work_mode(description, j.get("title", "")),
                "source": "cake",
                "keyword_used": keyword,
                "page_path": page_path,
                "page_name": page.get("name", ""),
                "job_source": j.get("job_source", ""),
                "job_type": j.get("job_type", ""),
                "seniority_level": j.get("seniority_level", ""),
                "content_updated_at": j.get("content_updated_at", ""),
                "description": description,  # 先保留原文，fetch_cake_jd 會優先用它做 fallback
                "highlighted_title": j.get("highlighted_title", ""),
                "highlighted_description": j.get("highlighted_description", ""),
            }
        )
    return out


def fetch_cake_jd(job: dict | str, page_path: str | None = None) -> dict:
    """抓 Cake JD。

    優先順序:
      1) 先試 public detail HTML
      2) 失敗就 fallback 到 search list 的 description

    Returns:
      {jd_text, jd_lines, jd_html, company, location, title, error, jd_source}
    """
    if isinstance(job, dict):
        job_path = job.get("path") or job.get("job_id") or ""
        page_path = page_path or job.get("page_path") or (job.get("page") or {}).get("path") or ""
        title = job.get("title", "")
        company = job.get("company", "") or (job.get("page") or {}).get("name", "")
        location = job.get("location", "")
        description = job.get("description") or job.get("highlighted_description") or ""
    else:
        job_path = str(job)
        title = ""
        company = ""
        location = ""
        description = ""
    detail_url = build_cake_detail_url(page_path, job_path) if page_path and job_path else ""

    # 1) 先試 public HTML
    if detail_url:
        try:
            r = _cc_session.get(
                detail_url,
                headers=_cake_headers(
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=f"{CAKE_WEB_BASE}/",
                ),
                proxies=_cake_proxies(),
                timeout=30,
                impersonate="chrome",
            )
            if r.status_code == 200:
                html_text = _cake_text_from_html(r.text)
                if html_text and "Just a moment..." not in html_text and len(html_text) >= 60:
                    jd_lines = [t.strip() for t in html_text.split("\n") if t.strip()]
                    return {
                        "jd_text": html_text,
                        "jd_lines": jd_lines,
                        "jd_html": r.text,
                        "company": company,
                        "location": location,
                        "title": title,
                        "error": None,
                        "jd_source": "detail_html",
                    }
        except Exception as e:
            detail_err = f"{type(e).__name__}: {e}"
        else:
            detail_err = f"HTTP {r.status_code}" if detail_url else "no detail url"
    else:
        detail_err = "no detail url"

    # 2) fallback: list description already 很長，通常就是完整 JD
    if description:
        jd_text = re.sub(r"\s+", " ", description).strip()
        jd_lines = [t.strip() for t in description.splitlines() if t.strip()]
        return {
            "jd_text": jd_text,
            "jd_lines": jd_lines,
            "jd_html": None,
            "company": company,
            "location": location,
            "title": title,
            "error": None,
            "jd_source": f"list_description ({detail_err})",
        }
    return {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": company,
        "location": location,
        "title": title,
        "error": detail_err,
        "jd_source": "none",
    }


def _cake_list_with_retry(kw: str, page: int, payload: dict, max_retries: int = 3) -> dict:
    """Cake list API 帶 30/60/90s retry (對齊 104 / Jora §15.13 #11)。

    429 / 5xx / connection error → sleep 30/60/90s → retry。
    4xx (非 429) 直接 raise, 視為 caller bug (例如 400 bad request)。
    Returns: response.json() dict
    Raises: RuntimeError if all retries fail
    """
    backoff = [30, 60, 90]
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = _cc_session.post(
                CAKE_LIST_API,
                headers=_cake_headers(),
                json=payload,
                proxies=_cake_proxies(),
                timeout=30,
                impersonate="chrome",
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429 or r.status_code >= 500:
                last_err = f"http {r.status_code}"
            else:
                raise RuntimeError(f"  [cake {kw!r} p{page}] non-retryable HTTP {r.status_code}: {r.text[:200]}")
        except RuntimeError:
            raise
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < max_retries:
            print(
                f"  [cake {kw!r} p{page} RETRY {attempt + 1}/{max_retries}] {last_err}, sleep {backoff[attempt]}s",
                flush=True,
            )
            time.sleep(backoff[attempt])
    raise RuntimeError(f"cake list API fail after {max_retries + 1} attempts: {last_err}")


def _cake_parse_job_timestamp(job: dict) -> tuple["datetime | None", bool]:
    """Parse Cake ``content_updated_at``.

    Returns ``(parsed_datetime, unknown)``. Missing or malformed timestamps are
    retained as jobs, counted in diagnostics, and never prove that a time
    boundary was reached. This is deliberately conservative: unknown time
    cannot turn an incomplete crawl into COMPLETE.
    """
    ts = job.get("content_updated_at", "")
    if not ts:
        return None, True
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc), False
    except Exception:
        return None, True


def _aggregate_cake_coverage(keyword_results: list[dict], cutoff: "datetime | None", total_jobs: int) -> str:
    """Aggregate Cake coverage across *every* keyword worker.

    Precedence intentionally keeps failures visible. COMPLETE requires every
    worker to have independently reached the cutoff boundary or server end.
    """
    states = [r.get("coverage_state", "ERROR") for r in keyword_results]
    if any(state == "ERROR" for state in states):
        return "PARTIAL_ERROR"
    if cutoff is None:
        return "UNKNOWN_NO_CUTOFF"
    if any(state == "TRUNCATED" for state in states):
        return "TRUNCATED"
    if keyword_results and all(state == "COMPLETE" for state in states):
        return "EMPTY" if total_jobs == 0 else "COMPLETE"
    if not keyword_results:
        return "EMPTY"
    # Fail closed if a future keyword state is introduced without aggregation.
    return "PARTIAL_ERROR"


def crawl_cake_list(
    daterange: str | None = None,
    max_pages: int | None = None,
    keywords: list[str] | None = None,
    sort_by: str = CAKE_SORT_BY,
    per_page: int = CAKE_PAGE_SIZE,
    locations: list[str] | None = None,
    job_types: list[str] | None = None,
    seniority_levels: list[str] | None = None,
    job_source: list[str] | None = None,
) -> dict:
    """Run independent Cake keyword searches and aggregate auditable coverage.

    Repair10 coverage contract:
    - worker owns cutoff/boundary proof; old boundary jobs are never returned;
    - each keyword reports COMPLETE / TRUNCATED / ERROR plus diagnostics;
    - global COMPLETE requires every keyword COMPLETE and no worker error;
    - server exhaustion is complete even when all observed jobs are fresh;
    - max-pages with no boundary/end is TRUNCATED;
    - missing/malformed timestamps are retained, counted, and never prove end;
    - no requested time cutoff yields UNKNOWN_NO_CUTOFF (unless a worker failed).

    The crawler stays bounded at ThreadPoolExecutor(max_workers=3) and dedups
    cross-keyword results by Cake path/job_id.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if keywords is None:
        keywords = CAKE_KEYWORDS
    if max_pages is None:
        if daterange is not None:
            max_pages = CAKE_MAX_PAGES.get(daterange, 15)
        else:
            max_pages = 15

    cutoff = None
    if daterange is not None and daterange in CAKE_TIME_FILTER:
        unit, n = CAKE_TIME_FILTER[daterange]
        if unit == "hours":
            cutoff = datetime.now(timezone.utc) - timedelta(hours=n)
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=n)

    requested_sort_by = (sort_by or CAKE_SORT_BY or "latest").strip().lower()
    effective_sort_by = _effective_cake_sort_by(requested_sort_by, cutoff)
    if cutoff is not None and effective_sort_by != requested_sort_by:
        print(
            f"  [cake coverage invariant] ranged crawl forces sort_by=latest (requested={requested_sort_by!r})",
            flush=True,
        )

    seen: set[str] = set()
    all_jobs: list[dict] = []
    keyword_results_by_kw: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(
                _crawl_cake_single_kw,
                kw,
                max_pages,
                cutoff,
                effective_sort_by,
                per_page,
                locations,
                job_types,
                seniority_levels,
                job_source,
            ): kw
            for kw in keywords
        }
        for future in as_completed(futures):
            kw = futures[future]
            try:
                result = future.result()
                if not isinstance(result, dict):
                    raise TypeError(f"worker returned {type(result).__name__}, expected dict")
            except Exception as e:
                result = {
                    "keyword": kw,
                    "jobs": [],
                    "coverage_state": "ERROR",
                    "boundary_reached": False,
                    "server_exhausted": False,
                    "pages_scanned": 0,
                    "max_pages": max_pages,
                    "unknown_timestamp_count": 0,
                    "error": f"{type(e).__name__}: {e}",
                }
            keyword_results_by_kw[kw] = result
            jobs = result.get("jobs", [])
            new_jobs = [j for j in jobs if j["job_id"] not in seen]
            for j in new_jobs:
                seen.add(j["job_id"])
                all_jobs.append(j)
            print(
                f"  [cake {kw}] state={result.get('coverage_state')} pages={result.get('pages_scanned')} "
                f"boundary={result.get('boundary_reached')} exhausted={result.get('server_exhausted')} "
                f"unknown_ts={result.get('unknown_timestamp_count')} | 收 {len(jobs):3} | "
                f"新增 {len(new_jobs):3} | 跨 kw 累計 {len(all_jobs):3}"
            )

    # Preserve caller keyword order so raw diagnostics are deterministic.
    keyword_results = [keyword_results_by_kw[kw] for kw in keywords if kw in keyword_results_by_kw]
    coverage_state = _aggregate_cake_coverage(keyword_results, cutoff, len(all_jobs))
    return {
        "jobs": all_jobs,
        "coverage_state": coverage_state,
        "max_pages_used": max_pages,
        "cutoff": cutoff.isoformat() if cutoff else None,
        "requested_sort_by": requested_sort_by,
        "effective_sort_by": effective_sort_by,
        "keyword_results": keyword_results,
    }


def _crawl_cake_single_kw(
    kw: str,
    max_pages: int,
    cutoff: "datetime | None" = None,
    sort_by: str = CAKE_SORT_BY,
    per_page: int = CAKE_PAGE_SIZE,
    locations: list[str] | None = None,
    job_types: list[str] | None = None,
    seniority_levels: list[str] | None = None,
    job_source: list[str] | None = None,
) -> dict:
    """Run one ordered Cake keyword crawl and return jobs plus coverage proof.

    With ``sort_by=latest`` and a cutoff, the first parseable job older than the
    cutoff proves the keyword boundary. The old job is filtered, the rest of
    that already-fetched page is still examined, and no later page is requested.
    Missing/malformed timestamps are retained and counted but cannot prove a
    boundary. Server exhaustion is also COMPLETE. Reaching max_pages while the
    server still advertises more pages is TRUNCATED. Request failure is ERROR.
    """
    requested_sort_by = (sort_by or CAKE_SORT_BY or "latest").strip().lower()
    effective_sort_by = _effective_cake_sort_by(requested_sort_by, cutoff)
    if cutoff is not None and effective_sort_by != requested_sort_by:
        print(
            f"  [cake {kw!r}] ranged cutoff forces sort_by=latest (requested={requested_sort_by!r})",
            flush=True,
        )

    seen: set[str] = set()
    out: list[dict] = []
    page = 1
    total_pages = None
    boundary_reached = False
    server_exhausted = False
    unknown_timestamp_count = 0
    pages_scanned = 0
    error = None

    while page <= max_pages:
        payload = build_cake_search_payload(
            kw,
            page,
            per_page=per_page,
            sort_by=effective_sort_by,
            locations=locations,
            job_types=job_types,
            seniority_levels=seniority_levels,
            job_source=job_source,
        )
        try:
            data = _cake_list_with_retry(kw, page, payload)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            print(f"  [cake {kw!r} p{page}] ERROR: {error}")
            break

        pages_scanned += 1
        jobs = parse_cake_search_page(data, kw)
        for j in jobs:
            jid = j["job_id"]
            if jid in seen:
                continue
            if cutoff is not None:
                job_dt, unknown = _cake_parse_job_timestamp(j)
                if unknown:
                    unknown_timestamp_count += 1
                elif job_dt < cutoff:
                    boundary_reached = True
                    # Boundary proof is metadata only. Never return the old job.
                    continue
            seen.add(jid)
            out.append(j)

        total_pages = data.get("total_pages") or total_pages
        total_entries = data.get("total_entries", "?")
        if not jobs or (total_pages is not None and page >= int(total_pages)):
            server_exhausted = True
        print(
            f"  [cake {kw!r} p{page}] 收 {len(jobs):3} | kw 累計 {len(out):3} | "
            f"total_entries={total_entries} total_pages={total_pages} "
            f"boundary={boundary_reached} unknown_ts={unknown_timestamp_count}"
        )

        if boundary_reached or server_exhausted:
            break
        if page < max_pages:
            cake_human_sleep("list")
        page += 1

    if error is not None:
        state = "ERROR"
    elif cutoff is None:
        # Keyword-level diagnostic; global result uses UNKNOWN_NO_CUTOFF too.
        state = "TRUNCATED" if not server_exhausted else "COMPLETE"
    elif boundary_reached or server_exhausted:
        state = "COMPLETE"
    else:
        state = "TRUNCATED"

    return {
        "keyword": kw,
        "jobs": out,
        "coverage_state": state,
        "boundary_reached": boundary_reached,
        "server_exhausted": server_exhausted,
        "pages_scanned": pages_scanned,
        "max_pages": max_pages,
        "unknown_timestamp_count": unknown_timestamp_count,
        "requested_sort_by": requested_sort_by,
        "effective_sort_by": effective_sort_by,
        "error": error,
    }


# ─────────────────────────────────────────────────────────────
# 104 (www.104.com.tw) — 2026-08-29 整合 (A 階段)
# 對稱 §12 JobStreet 設計: build_url / parse_list_page / fetch_jd / crawl_list
# RULES §15 完整設計文檔
# ─────────────────────────────────────────────────────────────
def _onezerofour_headers(referer: str = "https://www.104.com.tw/jobs/search/") -> dict:
    """104 共用 header, referer 預設 list page (detail API 要換成 /job/{slug})。"""
    return {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }


def build_onezerofour_list_url(keyword: str, page: int, isnew: int, areas: str = ONEZEROFOUR_AREAS) -> str:
    """組 104 list API URL。RULES §15.2 完整 query spec。

    Args:
        keyword: 搜尋字串 (傳原字中文, Python 自動 URL encode)
        page: 1-indexed (page=1 開始, server 給 22 個, page 6+ 給 20 個)
        isnew: 0/3/7/14/30 (其他 400, 含 21)
        areas: 地區代碼, 預設台北+新北
    """
    import urllib.parse

    params = {
        "area": areas,
        "keyword": keyword,
        "isnew": str(isnew),
        "page": str(page),
        "pagesize": "20",
        "order": "15",
        "mode": "s",  # s = 搜尋模式 (不是 l=列表模式)
        "jobsource": "m_joblist_search",
        "searchJobs": "1",
    }
    return f"{ONEZEROFOUR_LIST_API}?{urllib.parse.urlencode(params)}"


def hit_onezerofour_list(keyword: str, page: int, isnew: int, max_retries: int = 3) -> list[dict]:
    """List API 帶 30/60/90s retry (跟 Jora 403 retry pattern 同, RULES §15.13 #11)。

    Returns: list of raw job dicts (從 response.data 解出)
    Raises: RuntimeError if all retries fail
    """
    backoff = [30, 60, 90]
    url = build_onezerofour_list_url(keyword, page, isnew)
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = _cc_session.get(url, headers=_onezerofour_headers(), timeout=30, impersonate="chrome")
            if r.status_code == 200:
                return r.json().get("data", [])
            last_err = f"http {r.status_code}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < max_retries:
            print(
                f"    [104 LIST RETRY {attempt + 1}/{max_retries}] kw={keyword!r} p{page} 失敗 ({last_err}), sleep {backoff[attempt]}s",
                flush=True,
            )
            time.sleep(backoff[attempt])
    raise RuntimeError(f"104 list API fail after {max_retries + 1} attempts: {last_err}")


def hit_onezerofour_detail(slug: str, max_retries: int = 3) -> str:
    """Detail API (5-char slug)。Fail-closed: 404 直接 raise (RULES §15.13 #5)。

    Returns: jobDescription 文字 (str), 空字串 if API 沒給
    Raises: RuntimeError on 404 (job 已下架) or retry exhausted
    """
    backoff = [30, 60, 90]
    url = ONEZEROFOUR_DETAIL_API.format(slug=slug)
    headers = _onezerofour_headers(referer=f"https://www.104.com.tw/job/{slug}")
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            r = _cc_session.get(url, headers=headers, timeout=30, impersonate="chrome")
            if r.status_code == 200:
                d = r.json().get("data", {}).get("jobDetail", {})
                return d.get("jobDescription", "") or ""
            if r.status_code == 404:
                # 404 fail-closed: job 已下架, 直接 raise, 不要 silent skip
                raise RuntimeError(f"104 detail 404 for slug={slug} (job 已下架)")
            last_err = f"http {r.status_code}"
        except RuntimeError:
            raise  # 404 propagate
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:50]}"
        if attempt < max_retries:
            print(
                f"    [104 DETAIL RETRY {attempt + 1}/{max_retries}] slug={slug} 失敗 ({last_err}), sleep {backoff[attempt]}s",
                flush=True,
            )
            time.sleep(backoff[attempt])
    raise RuntimeError(f"104 detail API fail after {max_retries + 1} attempts: {last_err}")


def parse_onezerofour_list_page(raw_jobs: list[dict], keyword: str = "") -> list[dict]:
    """從 104 list API 的 data 陣列解 jobs。RULES §15.3 完整欄位對照。

    回傳 dict 格式跟其他 source 對齊 (統一 job_id / source / title / company / location / url 等 key)。
    job_id 用 slug (5-char) 不是 jobNo (8 digit), 因為 sheet E 欄跟 parse_sheet_row_to_key 都用 slug 推斷 source。
    """
    out = []
    for j in raw_jobs:
        job_no = j.get("jobNo")
        slug = (j.get("link") or {}).get("job", "")
        # 拿最後一段 (URL 格式: https://www.104.com.tw/job/xxx → xxx, 注意 trailing slash)
        if "/" in slug:
            slug = slug.rstrip("/").rsplit("/", 1)[-1]
        if not (job_no and slug):
            continue
        # remoteWorkType 對應 work_mode: 0=Onsite / 1=Remote / 2=Hybrid (RULES §15.3)
        rw = j.get("remoteWorkType", 0)
        if rw == 1:
            wm = "Remote"
        elif rw == 2:
            wm = "Hybrid"
        else:
            wm = "Onsite"
        out.append(
            {
                "job_id": slug,  # 用 slug 當 job_id (跟 E 欄 URL 一致, 跟 parse_sheet_row_to_key 對齊)
                "job_no": job_no,  # 8 digit, 留著 debug/audit 用
                "title": j.get("jobName", ""),
                "company": j.get("custName", ""),
                "location": j.get("jobAddrNoDesc", ""),
                "posted_at": j.get("appearDate", ""),
                "url": f"{ONEZEROFOUR_BASE_URL}/job/{slug}",
                "work_mode": wm,
                "source": "onezerofour",
                "keyword_used": keyword,  # debug 用
            }
        )
    return out


def fetch_onezerofour_jd(slug: str) -> dict:
    """抓單一 job 的完整 JD。回傳跟其他 source 對齊的 dict。

    Returns: {jd_text, jd_lines, jd_html, company, location, title, error}
    """
    try:
        jd_text = hit_onezerofour_detail(slug)
    except RuntimeError as e:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": str(e),
        }
    if not jd_text:
        return {
            "jd_text": None,
            "jd_lines": None,
            "jd_html": None,
            "company": "",
            "location": "",
            "title": "",
            "error": "empty JD",
        }
    # 跟其他 source 一樣: jd_lines 給 optional 用, 主要還是 jd_text
    jd_lines = [t.strip() for t in jd_text.split("\n") if t.strip()]
    return {
        "jd_text": jd_text,
        "jd_lines": jd_lines,
        "jd_html": None,
        "company": "",  # 104 list 階段已有, 不再覆寫
        "location": "",
        "title": "",
        "error": None,
    }


def crawl_onezerofour_list(daterange: str, max_pages: int, keywords: list[str] | None = None) -> list[dict]:
    """8 keyword × max_pages list API, ThreadPoolExecutor 8 workers 平行抓 (RULES §15.8, §15.11)。

    跨 kw dedup by slug (slug 跨 kw 不會撞, 但保險起見去重)。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if keywords is None:
        keywords = ONEZEROFOUR_KEYWORDS
    isnew = ONEZEROFOUR_TPR[daterange]
    seen: set[str] = set()
    collected: list[tuple[str, dict]] = []  # (keyword, raw_job)

    def _fetch_one_kw(kw: str) -> list[tuple[str, str, dict]]:
        """單 keyword × max_pages (sequential, 一個 worker 跑固定一個 kw)。
        Returns: list of (kw, slug, raw_job) for dedup tracking。
        """
        results = []
        for p in range(1, max_pages + 1):
            try:
                raw = hit_onezerofour_list(kw, p, isnew)
            except RuntimeError as e:
                print(f"  [104 KW FAIL] {kw!r} p{p}: {e}", flush=True)
                continue
            for j in raw:
                slug = (j.get("link") or {}).get("job", "")
                if "/" in slug:
                    slug = slug.rstrip("/").rsplit("/", 1)[-1]
                if slug:
                    results.append((kw, slug, j))
        return results

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_fetch_one_kw, kw): kw for kw in keywords}
        for fut in as_completed(futs):
            kw = futs[fut]
            try:
                kw_results = fut.result()
            except Exception as e:
                print(f"  [104 KW EXCEPTION] {kw!r}: {type(e).__name__}: {e}", flush=True)
                continue
            for _kw, slug, raw in kw_results:
                if slug in seen:
                    continue
                seen.add(slug)
                collected.append((_kw, raw))
    # parse 階段 (拿到原始 jobs 統一轉 dict, keyword 跟著帶進去)
    out = []
    for kw, raw in collected:
        out.extend(parse_onezerofour_list_page([raw], keyword=kw))
    return out


def enrich_with_jd(
    jobs: list[dict],
    skip_pat: re.Pattern | None = None,
    seen_ids: set[tuple[str, str]] | None = None,
    refetch: bool = False,
    json_cache: dict | None = None,
    *,
    no_skip: bool = False,
) -> tuple[list[dict], dict]:
    """
    抓 JD。命中 skip 關鍵字的不抓；已抓過的也不抓。

    Cache 來源 (依序檢查):
      1. in-memory jd_text: 同一個 run 內已 enrich 過
      2. json_cache: 從磁碟 *_jd.json 載入的跨 run cache (load_jd_cache_from_jsons)
      3. seen_ids (僅用於日誌): seen_jds.jsonl 內見過的 (但可能 cache 已被刪)

    --refetch 時跳過所有 cache，強制重抓。

    2026-08-22: json_cache / seen_ids 都改成 (source, job_id) tuple, 避免 LinkedIn / JobStreet 數字 ID 撞

    Title-skip 決策 (2026-10-26 v1.4.0 修正):
      - v8.5 的語意群組 (`match_skip_reason`) 永遠是主要規則, 除非 `no_skip=True`。
      - `skip_pat` 恢復 v8.4 語意: 額外的關鍵詞比對, 命中也算 skip。
        v8.5 之前這個參數被 `match_skip_reason` 直接忽略, 導致 `--skip-keywords`
        與 `--no-skip` 兩個 CLI flag 對過濾結果毫無影響 (help 文字與實作不符)。
      - `no_skip=True` 時完全不套用任何 title filter。
    """
    seen_ids = seen_ids or set()
    json_cache = json_cache or {}
    n_total = len(jobs)

    def _skip_reason(job: dict) -> str | None:
        """v8.5 語意群組 + (選用) 額外關鍵詞比對。"""
        if no_skip:
            return None
        title = job.get("title", "")
        reason = match_skip_reason(title, source=job.get("source"))
        if reason:
            return reason
        if skip_pat is not None and skip_pat.search(title):
            return "custom_skip_keywords"
        return None

    # 統計 n_skip / n_cached / n_to_fetch
    n_skip = 0
    n_cached = 0
    for j in jobs:
        if _skip_reason(j):
            n_skip += 1
            continue
        if refetch:
            continue
        jid = j.get("job_id")
        src = j.get("source", "linkedin")
        if j.get("jd_text"):
            n_cached += 1
        elif (src, jid) in json_cache:
            n_cached += 1
    n_to_fetch = n_total - n_skip - n_cached
    print(f"\n=== 抓 JD ({n_total} 筆) — skip {n_skip}, cached {n_cached}, fetch {n_to_fetch} ===")
    if skip_pat is not None and n_skip:
        print(f"  額外 skip 規則: {skip_pat.pattern}")
    print(f"  json_cache: {len(json_cache)} 筆 / seen file: {len(seen_ids)} 筆 / refetch={refetch}")

    out = []
    stats = {"total": n_total, "skipped": 0, "cached": 0, "fetched": 0, "failed": 0}
    for i, j in enumerate(jobs, 1):
        reason = _skip_reason(j)
        j2 = dict(j)
        if reason:
            j2["jd_text"] = None
            j2["jd_skipped"] = reason
            stats["skipped"] += 1
            print(f"  [{i}/{n_total}] ⏭  skip ({reason})  {j['title'][:55]}")
            out.append(j2)
            continue
        jid = j.get("job_id")
        src = j.get("source", "linkedin")
        if not refetch:
            # 1) in-memory jd_text (同 run 內)
            if j.get("jd_text"):
                j2["jd_text"] = j["jd_text"]
                j2["jd_lines"] = j.get("jd_lines")
                j2["jd_hash"] = j.get("jd_hash")
                j2["jd_cached"] = "memory"
                stats["cached"] += 1
                print(f"  [{i}/{n_total}] 💾 cached (mem)  {j['title'][:55]}")
                out.append(j2)
                continue
            # 2) json_cache (跨 run)
            if (src, jid) in json_cache:
                c = json_cache[(src, jid)]
                j2["jd_text"] = c["jd_text"]
                j2["jd_lines"] = c.get("jd_lines")
                j2["jd_hash"] = c.get("jd_hash")
                j2["jd_cached"] = "json"
                stats["cached"] += 1
                print(f"  [{i}/{n_total}] 💾 cached (json) {j['title'][:55]}")
                out.append(j2)
                continue
        # 3) 抓 JD (依 source 決定 fetcher)
        # DEPRECATED 2026-09-09: jora dispatch 已移除 (sg.jora.com 關站), active sources 剩 linkedin / jobstreet / cake / onezerofour
        print(f"  [{i}/{n_total}] {j['job_id']} {j['title'][:50]}")
        if src == "jobstreet":
            result = fetch_jobstreet_jd(jid)
        elif src == "cake":
            result = fetch_cake_jd(j)
        elif src == "onezerofour":
            result = fetch_onezerofour_jd(jid)
        else:
            # 預設 LinkedIn (unknown source 也 fallback 到這)
            result = fetch_jd(jid)
        if result.get("jd_text"):
            j2["jd_text"] = result["jd_text"]
            j2["jd_lines"] = result["jd_lines"]
            j2["jd_hash"] = jd_hash(result["jd_text"])
            # 從 JD result 補公司/位置 (list 頁沒公司時用 JD 補, 例如 JobStreet list 有時缺公司)
            if result.get("company"):
                j2["company"] = result["company"]
            if result.get("location"):
                j2["location"] = result["location"]
            stats["fetched"] += 1
            print(
                f"            ✓ {len(result['jd_text'])} chars / {len(result['jd_lines'])} lines / co={j2.get('company', '')[:30]}"
            )
            # 記到 seen file (只在 seen 沒記錄時 append, 避免重複行)
            # refetch=True 時 seen_ids 會是空 set → 全部都會 append (更新 hash/timestamp)
            seen_key = (src, jid)
            if seen_key not in seen_ids:
                try:
                    append_seen(jid, j2["jd_hash"], j.get("title", ""), j2.get("company", ""), source=src)
                except Exception as e:
                    print(f"            (warn) 寫 seen file 失敗: {e}")
        else:
            j2["jd_text"] = None
            j2["jd_error"] = result.get("error")
            stats["failed"] += 1
            print(f"            ✗ {result.get('error')}")
        out.append(j2)
        if i < n_total:
            human_sleep("jd")
    return out, stats


def build_arg_parser() -> argparse.ArgumentParser:
    """抽出 main() 內的 argparse 設定, 讓 R9-10 可以獨立測 CLI parsing."""
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "range",
        nargs="?",
        default=DEFAULT_TPR,
        choices=list(TIME_RANGES.keys()),
        help=f"time range (default {DEFAULT_TPR})",
    )
    ap.add_argument(
        "--source",
        default="linkedin",
        choices=["linkedin", "jobstreet", "cake", "104", "onezerofour"],
        help="資料來源 (default: linkedin). jobstreet=sg.jobstreet.com (API+GraphQL), cake=www.cake.me (API+detail URL), 104=www.104.com.tw (TW). 104 跟 onezerofour 是 alias。jora 已於 2026-09-09 關站移除。",
    )
    ap.add_argument(
        "--location",
        default=None,
        help=f"目標城市/國家 (default: {LOCATION}); 已知 preset: {', '.join(KNOWN_GEO_IDS.keys())}",
    )
    ap.add_argument("--geo-id", default=None, help=f"LinkedIn geoId (default: {GEO_ID}); 跟 --location 一起給")
    ap.add_argument("--with-jd", action="store_true", help="抓取每個職缺的 JD 全文 (會增加不少時間)")
    ap.add_argument("--max-pages", type=int, default=None, help="override 預設頁數上限")
    ap.add_argument(
        "--skip-keywords",
        nargs="*",
        default=None,
        help="額外的標題關鍵詞比對（與 v8.5 語意群組並存，任一命中就 skip）。"
        "不給此旗標時只套用 v8.5 語意群組。"
        "注意: 這不是取代 v8.5 預設過濾, 是額外加上。",
    )
    ap.add_argument(
        "--no-skip", action="store_true", help="完全跳過所有標題過濾（連 v8.5 語意群組也不套用），全部都抓 JD"
    )
    ap.add_argument("--refetch", action="store_true", help="忽略 seen_jds.jsonl，重新抓所有 JD")
    ap.add_argument("--reset-seen", action="store_true", help="刪掉 seen_jds.jsonl 後結束（清空紀錄）")
    ap.add_argument("--seen-file", default=SEEN_FILE, help=f"已抓 JD 記錄檔路徑 (default: {SEEN_FILE})")
    ap.add_argument(
        "--to-sheet",
        default=None,
        metavar="URL_OR_ID",
        help=f"抓完後把結果 append 到 Google Sheet (URL 或 ID; 不帶 gid 會報錯, 請用 '{SG_RAW_URL}')",
    )
    ap.add_argument(
        "--gid", default=None, type=int, help=f"指定要寫的 worksheet gid (e.g. {SG_RAW_GID}); 不指定時用 URL 內 #gid="
    )
    ap.add_argument(
        "--sheet-source",
        default=DEFAULT_SHEET_SOURCE,
        help=f"寫入 Sheet 的 Source 欄位值 (default: {DEFAULT_SHEET_SOURCE})",
    )
    ap.add_argument("--dry-run-sheet", action="store_true", help="跟 --to-sheet 一起用，只印將寫入什麼、不真的寫")
    return ap


def main():
    ap = build_arg_parser()
    args = ap.parse_args()

    # 104 / onezerofour alias 正規化 (CLI 給 --source 104 跟 --source onezerofour 等義)
    if args.source == "104":
        args.source = "onezerofour"

    seen_path = Path(args.seen_file)

    if args.reset_seen:
        n = reset_seen(seen_path)
        print(f"已刪除 {seen_path} ({n} 筆紀錄)")
        return

    tpr, default_max = TIME_RANGES[args.range]
    if args.source == "jobstreet":
        default_max = JOBSTREET_MAX_PAGES[args.range]
    elif args.source == "cake":
        default_max = CAKE_MAX_PAGES[args.range]
    elif args.source == "onezerofour":
        default_max = ONEZEROFOUR_MAX_PAGES[args.range]
    max_pages = args.max_pages or default_max

    # Title-skip 的三種語意 (2026-10-26 v1.4.0 修正):
    #   預設          → 只用 v8.5 語意群組 (skip_pat=None)
    #   --skip-keywords → v8.5 語意群組 + 自訂關鍵詞額外比對
    #   --no-skip      → 完全不套用任何 title filter
    # v8.5 之前這三者的過濾結果完全相同 (skip_pat 被 match_skip_reason 忽略),
    # 等於兩個 CLI flag 形同虛設。
    skip_pat = None
    if args.skip_keywords:
        skip_pat = _make_skip_pattern(args.skip_keywords)

    # 解析 location/geo-id (preset 優先: --location 從 KNOWN_GEO_IDS 取 geo-id, 或自己給)
    location = args.location
    geo_id = args.geo_id
    if location and not geo_id and location in KNOWN_GEO_IDS:
        geo_id, location = KNOWN_GEO_IDS[location]
    if not location:
        location = LOCATION
    if not geo_id:
        geo_id = GEO_ID

    # 解析 location/geo-id (preset 優先: --location 從 KNOWN_GEO_IDS 取 geo-id, 或自己給)
    location = args.location
    geo_id = args.geo_id
    if args.source == "linkedin":
        if location and not geo_id and location in KNOWN_GEO_IDS:
            geo_id, location = KNOWN_GEO_IDS[location]
        if not location:
            location = LOCATION
        if not geo_id:
            geo_id = GEO_ID
        # LinkedIn 預設 source label
        if args.sheet_source == DEFAULT_SHEET_SOURCE:
            args.sheet_source = "LinkedIn / Minimax"
    # DEPRECATED 2026-09-09: jora dispatch 已移除 (sg.jora.com 關站)
    elif args.source == "cake":
        # P1-04 (Repair9 v2): Cake 是 Taiwan-intake, 一律寫到 TW-Raw
        # location = CAKE_LOCATION_SCOPE 只是 search-scope metadata (例如 "Global"),
        # 不用來當 row 寫入的 Location 欄位 (row Location 從 Cake API 個別 job 的 locations[0] 拿)
        # CLI --location 對 cake 不生效 (要過濾用 CAKE_LOCATIONS env var 或改 code)
        location = CAKE_LOCATION_SCOPE  # search-scope only
        geo_id = None
        if args.sheet_source == DEFAULT_SHEET_SOURCE:
            args.sheet_source = CAKE_SHEET_SOURCE_LABEL
        # Cake 自動 dispatch 到 TW-Raw (除非 user 明確帶 --gid 覆寫)
        if args.gid is None:
            args.gid = CAKE_TW_RAW_GID
    elif args.source == "onezerofour":
        # 104 永遠寫 TW-Raw, 不需要 --location/--geo-id (硬寫 AREAS=台北+新北)
        location = ONEZEROFOUR_LOCATION
        geo_id = None
        if args.sheet_source == DEFAULT_SHEET_SOURCE:
            args.sheet_source = ONEZEROFOUR_SHEET_SOURCE_LABEL
        # 104 自動 dispatch 到 TW-Raw (除非 user 明確帶 --gid 覆寫)
        if args.gid is None:
            args.gid = ONEZEROFOUR_TW_RAW_GID
    else:  # jobstreet
        if not location:
            location = JOBSTREET_LOCATION
        # JobStreet 不需要 geo_id
        geo_id = None
        if args.sheet_source == DEFAULT_SHEET_SOURCE:
            args.sheet_source = "JobStreet / Minimax"

    if args.source == "linkedin":
        print(f"==== LinkedIn Jobs / {location} (geoId={geo_id}) / {args.range} / f_TPR={tpr} ====")
    elif args.source == "cake":
        effective_cake_sort = _effective_cake_sort_by(CAKE_SORT_BY, datetime.now(timezone.utc))
        print(
            f"==== Cake Jobs / {location} / {args.range} / page_size={CAKE_PAGE_SIZE} / sort_by={effective_cake_sort} (ranged-forced) / kw={len(CAKE_KEYWORDS)} ===="
        )
    elif args.source == "onezerofour":
        oof_tpr = ONEZEROFOUR_TPR[args.range]
        print(
            f"==== 104 Jobs / {location} (area={ONEZEROFOUR_AREAS}) / {args.range} / isnew={oof_tpr} (multi-keyword={len(ONEZEROFOUR_KEYWORDS)}) ===="
        )
    else:
        js_tpr = JOBSTREET_TPR[args.range]
        print(
            f"==== JobStreet Jobs / {location} / {args.range} / daterange={js_tpr} (multi-keyword={len(JOBSTREET_KEYWORDS)}) ===="
        )
    print(f"==== MAX_PAGES = {max_pages}  (隨機 sleep {SLEEP_MIN}-{SLEEP_MAX}s) ====\n")
    if args.with_jd and skip_pat:
        print(f"==== JD skip 規則: {skip_pat.pattern} ====")
        if args.skip_keywords is not None:
            print(f"     (使用者覆寫: {args.skip_keywords})")
    elif args.with_jd and args.no_skip:
        print("==== JD skip 規則: <disabled> ====")

    # 0) 載入 seen_ids (跨 run dedup)
    seen_ids = load_seen_ids(seen_path) if args.with_jd and not args.refetch else set()
    if seen_ids:
        print(f"==== 載入 {len(seen_ids)} 筆 seen job_ids (refetch={args.refetch}) ====")

    # 1) 抓列表
    # DEPRECATED 2026-09-09: jora dispatch 已移除 (sg.jora.com 關站)
    if args.source == "jobstreet":
        js_tpr = JOBSTREET_TPR[args.range]
        jobs = crawl_jobstreet_list(js_tpr, max_pages, keywords=JOBSTREET_KEYWORDS)
    elif args.source == "cake":
        # P1-01: max_pages 接到 crawl_cake_list (跟其他 source 對齊, 沒傳 fallback CAKE_MAX_PAGES[range])
        cake_result = crawl_cake_list(args.range, max_pages=max_pages, keywords=CAKE_KEYWORDS)
        jobs = cake_result["jobs"]
        # P1-03: 印 coverage diagnostic
        print(
            f"\n=== Cake coverage: {cake_result['coverage_state']} "
            f"(max_pages={cake_result['max_pages_used']}, cutoff={cake_result['cutoff']}) ===",
            flush=True,
        )
    elif args.source == "onezerofour":
        jobs = crawl_onezerofour_list(args.range, max_pages, keywords=ONEZEROFOUR_KEYWORDS)
    else:
        jobs = crawl_list(tpr, max_pages, location=location, geo_id=geo_id)
    if not jobs:
        print("\n無資料，結束。")
        return

    # 1.5) 載入 JD cache (跨 run 從 *_jd.json 抓)，跳過當前將輸出的檔
    suffix = f"_{args.range}{'_jd' if args.with_jd else ''}"
    # 檔名以 source + location 為 prefix (sg_product_jobs, tw_, jobstreet_sg_, onezerofour_), 避免跨源/跨國 cache 污染
    # DEPRECATED 2026-09-09: jora_sg_ prefix 已移除 (sg.jora.com 關站)
    location_short = location.lower().replace(" ", "")
    short_names = {
        "singapore": "sg",
        "taiwan": "tw",
        "hongkong": "hk",
        "japan": "jp",
    }
    loc_prefix = short_names.get(location_short, location_short)
    # 各 source cache 獨立 prefix (sg_, jobstreet_sg_, onezerofour_tw_), 避免跨源/跨國 cache 污染
    if args.source == "jobstreet":
        prefix = f"jobstreet_{loc_prefix}"
    elif args.source == "cake":
        prefix = f"cake_{loc_prefix}"
    elif args.source == "onezerofour":
        prefix = f"onezerofour_{loc_prefix}"
    else:
        prefix = loc_prefix
    out = Path(f"{prefix}_product_jobs{suffix}.json")
    json_cache = {}
    if args.with_jd and not args.refetch:
        print(f"\n==== 載入 JD cache (排除 {out.name}) ====")
        json_cache = load_jd_cache_from_jsons(skip_files={out.name})

    # 1.7) Pre-detail sheet dedup (B 階段 2026-08-29 優化, A 整合版 2026-08-29 補上):
    #        進 detail 之前先讀 sheet 跳過已存在 jobs, 重跑時可省 70-99% detail calls
    if args.with_jd and not args.refetch:
        jobs = pre_dedup_jobs_against_sheet(jobs, args.sheet_source, dry_run=False)

    # 2) 抓 JD (可選)
    stats = None
    if args.with_jd:
        jobs, stats = enrich_with_jd(
            jobs,
            skip_pat=skip_pat,
            seen_ids=seen_ids,
            refetch=args.refetch,
            json_cache=json_cache,
            no_skip=args.no_skip,
        )

    # 3) 存檔
    out.write_text(json.dumps(jobs, ensure_ascii=False, indent=2))
    print(f"\n==== 寫到 {out.resolve()} ({len(jobs)} 筆) ====")
    if stats:
        print(
            f"     JD: skip={stats['skipped']}  cached={stats['cached']}  "
            f"fetched={stats['fetched']}  failed={stats['failed']}"
        )
    if seen_path.exists() and args.with_jd:
        total = sum(1 for _ in open(seen_path, "r", encoding="utf-8") if _.strip())
        print(f"     seen file: {seen_path} ({total} 筆累計)")

    # 4) 寫到 Google Sheet (可選)
    if args.to_sheet:
        if not args.with_jd:
            print("\n⚠️  --to-sheet 需要 --with-jd 才能填 JD 內容 (column H)")
            print("    跳過 sheet 寫入")
        else:
            print(f"\n==== 寫到 Google Sheet: {args.to_sheet[:50]}... ====")
            sheet_stats = push_to_sheet(
                jobs,
                args.to_sheet,
                sa_key_path=SHEET_SA_KEY,
                source=args.sheet_source,
                dry_run=args.dry_run_sheet,
                gid=args.gid,
                location=location,
            )
            print(f"\n  結果: {sheet_stats}")


if __name__ == "__main__":
    main()
