"""
sg_product_jobs — 多源職缺爬蟲 + Google Sheet 同步

支援的 source:
  - linkedin:  /jobs-guest/jobs/api/...  (Guest API, 不需 cookie)
  - jora:      sg.jora.com  (HTML parse, 9/9/2026 關站前)
  - jobstreet: sg.jobstreet.com  (公開 API + GraphQL)

Single source of truth: RULES.md (4 種 URL, MAX_PAGES, skip list, sheet 11 欄, dedup, visa)
"""
__version__ = "1.0.0"  # 2026-08-23 重構: 抽 helpers + 拆函數, 行為不變

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
import random
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlencode

from curl_cffi import requests as cc_requests
from scrapling.parser import Adaptor
from bs4 import BeautifulSoup
from jobs_scraper.sources import jora as jora_source
from jobs_scraper.sources import jobstreet as jobstreet_source
from jobs_scraper.sources import linkedin as linkedin_source

# 全域 session: 維持 cookies 跟 connection pool, 降低被 LinkedIn rate limit 觸發 429 的機率
_cc_session = cc_requests.Session(impersonate="chrome")


# ─────────────────────────────────────────────────────────────
# 環境變數讀取 (2026-08-23 新增, 讓別人 fork repo 自己客製化)
# 設定方式: 從 .env.example 複製成 .env, 填值; 或直接 export 環境變數
# 沒設會 fallback 到下面 hardcoded 預設值 (原開發者自己的設定)
# ─────────────────────────────────────────────────────────────
import os

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


# ─────────────────────────────────────────────────────────────
# 篩選條件
# ─────────────────────────────────────────────────────────────
KEYWORDS = (
    '"product manager" OR "product director" OR "director of product" '
    'OR "head of product" OR "product lead" OR "chief of staff"'
)
GEO_ID = "102454443"          # Singapore (default; 跑其他國家用 --location/--geo-id 覆寫)
LOCATION = "Singapore"         # 對應 GEO_ID 的顯示文字
# 常用其他 geoId (驗證過)
KNOWN_GEO_IDS = {
    "Singapore": ("102454443", "Singapore"),
    "Taiwan":    ("104187078", "Taiwan"),
    "Hong Kong": ("105015875", "Hong Kong"),  # 待驗證
    "Japan":     ("105080838", "Japan"),      # 待驗證
    "Shanghai":  ("107388191", "Shanghai"),   # 中國城市, 30,000+ jobs
}
# 不放 f_WT → onsite/remote/hybrid 全收
PAGE_SIZE = 10                # Guest API 實際 page size (不是 25)

# time range 預設值 + 各 range 的 MAX_PAGES 建議
TIME_RANGES = {
    "1h":  ("r3600",     1),
    "24h": ("r86400",    4),
    "3d":  ("r259200",   7),
    "7d":  ("r604800",   15),
    "14d": ("r1209600",  30),
    "21d": ("r1814400",  30),  # 3 週
    "30d": ("r2592000",  25),
}
# Jora (sg.jora.com) — 2026-08-22 設定, Jora SG 9/9 關閉前抓完
JORA_TPR = {
    "1h":  "1h",
    "24h": "24h",
    "3d":  "3d",
    "7d":  "7d",
    "14d": "14d",
    "21d": "21d",
    "30d": "30d",
}
# MAX_PAGES 2026-08-22 確認: 每頁 15 unique jobs (HTML render 兩次), double 但 rebalance
# Coverage: 1d=47%→71% / 3d=36%→55% / 7d=19%→29% / 14d=14%→23% / 21d=11%→18% / 30d=8.6%→14%
JORA_MAX_PAGES = {
    "1h":  5,
    "24h": 10,
    "3d":  30,
    "7d":  30,
    "14d": 40,
    "21d": 40,
    "30d": 40,
}
JORA_KEYWORD = "product manager"
JORA_LOCATION = "Singapore"
JORA_BASE = "https://sg.jora.com"

# JobStreet (sg.jobstreet.com) — 2026-08-22 整合
# 用 /api/jobsearch/v5/search 抓 list + /graphql 抓 JD content
# HTML 頁 100% Cloudflare blocked, 走 GraphQL 完全 OK (詳見 RULES.md §12.5)
JOBSTREET_TPR = jobstreet_source.TPR
JOBSTREET_MAX_PAGES = jobstreet_source.MAX_PAGES
# 可被 JOBSTREET_KEYWORDS env var 覆寫 (見上面 env 讀取區塊)
# 例: JOBSTREET_KEYWORDS="product manager,product director,head of product"
if JOBSTREET_KEYWORDS_OVERRIDE:
    JOBSTREET_KEYWORDS = [k.strip() for k in JOBSTREET_KEYWORDS_OVERRIDE.split(",") if k.strip()]
else:
    JOBSTREET_KEYWORDS = list(jobstreet_source.DEFAULT_KEYWORDS)
JOBSTREET_LOCATION = jobstreet_source.DEFAULT_LOCATION
JOBSTREET_LIST_API = jobstreet_source.LIST_API
JOBSTREET_GRAPHQL = jobstreet_source.GRAPHQL
JOBSTREET_BASE = jobstreet_source.BASE_URL
JOBSTREET_WORKTYPE_FT = jobstreet_source.WORKTYPE_FT

DEFAULT_TPR = "24h"

# 隨機 sleep 區間 (人類節奏)
SLEEP_MIN = 3.0
SLEEP_MAX = 10.0

# 跨 run 的「已抓過 JD」記錄檔
SEEN_FILE = "seen_jds.jsonl"
TZ_LOCAL = timezone(timedelta(hours=7))   # GMT+7

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
SG_RAW_URL = (
    f"https://docs.google.com/spreadsheets/d/{SG_RAW_SHEET_ID}"
    f"/edit?gid={SG_RAW_GID}#gid={SG_RAW_GID}"
)
# China-Raw (Shanghai 用的, user 2026-08-21 建)
CHINA_RAW_GID = 488353479
CHINA_RAW_URL = (
    f"https://docs.google.com/spreadsheets/d/{SG_RAW_SHEET_ID}"
    f"/edit?gid={CHINA_RAW_GID}#gid={CHINA_RAW_GID}"
)

# JD 抓取前的標題關鍵字過濾 (省配額)
# 看到這些詞就跳過不抓 JD；比對用 word-boundary + case-insensitive
DEFAULT_SKIP_KEYWORDS = [
    # 明確太菜
    "intern", "internship", "trainee", "graduate", "grad",
    "entry", "entry level", "entry-level", "junior", "jr",
    # 助理/支援 — 但 "assistant" 有 senior 情境 (AVP/Asst Director), 用 whitelist 蓋過
    "assistant", "support", "coordinator", "administrator", "clerk", "secretary",
    # analyst / marketing track (有 "product" 但其實不是 PM)
    "product marketing", "product analyst",
    # 測試 / QA
    "qa", "test", "quality assurance",
    # Sales / BD / AE
    "sales", "business development", "account executive",
    # specialist 偏 IC
    "specialist",
    # 短/臨時
    "temp", "temporary", "contract",
]

# Senior whitelist: 某些詞雖然在 skip list, 但若後面接這些 senior 詞就不該被擋
SENIOR_FOLLOWERS = [
    "vice president", "director", "general manager", "managing director",
    "president", "ceo", "cfo", "cto", "cmo", "coo", "chairman", "head",
    "secretary-general",
]

# Senior 標記 (anywhere in title)：當 "specialist" 之類 skip 詞出現時,
# 若 title 任一位置有這些 senior 詞, 就視為高階不擋
SENIOR_MARKERS_ANYWHERE = [
    "avp", "vp", "vice president", "director", "head", "chief",
    "senior", "staff", "principal", "lead", "managing director",
    "general manager", "president", "ceo", "cfo", "cto", "cmo", "coo",
    "chairman",
]

# Whitelist 策略: 不同 skip 詞用不同判定方式
# - "adjacent": skip 詞後要**直接接** senior 詞才算 (e.g., "Assistant VP")
# - "anywhere": title 任一位置有 senior 詞就算 (e.g., "AVP, Specialist")
WHITELIST_RULES = {
    "assistant": "adjacent",
    "specialist": "anywhere",
}


# ─────────────────────────────────────────────────────────────
# 關鍵字比對工具
# ─────────────────────────────────────────────────────────────
def _make_skip_pattern(skip_words: list[str]) -> re.Pattern:
    """編一個 case-insensitive、word-boundary 的 regex。"""
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


def _has_senior_marker_anywhere(title: str) -> bool:
    """anywhere 模式: title 任一位置有 senior 標記就算"""
    if not title:
        return False
    t = title.lower()
    return any(m in t for m in SENIOR_MARKERS_ANYWHERE)


def match_skip_reason(title: str, skip_pat: re.Pattern) -> str | None:
    """標題命中 skip list 就回傳命中的詞，否則 None。
    智慧例外: assistant + senior 詞 (adjacent) 或 specialist + senior 詞 (anywhere) 視為高階。"""
    if not title:
        return None
    m = skip_pat.search(title)
    if not m:
        return None
    hit = m.group(1).lower()
    rule = WHITELIST_RULES.get(hit)
    if rule == "adjacent" and _is_senior_assistant_title(title):
        return None
    if rule == "anywhere" and _has_senior_marker_anywhere(title):
        return None
    return hit


# ─────────────────────────────────────────────────────────────
# 跨 run 已抓 JD 記錄 (JSONL, append-only)
# ─────────────────────────────────────────────────────────────
def jd_hash(jd_text: str) -> str:
    return hashlib.sha256((jd_text or "").encode("utf-8")).hexdigest()[:16]


def load_seen_ids(path: Path = Path(SEEN_FILE)) -> set[tuple[str, str]]:
    """讀 seen_jds.jsonl，回傳 set of (source, job_id)。壞行跳過不炸。

    ⚠️ 跨 source 區分: LinkedIn / JobStreet 都是純數字, 會撞; Jora 是 32-char hex 不撞
    舊記錄沒 source 欄位 → 從 job_id 推斷:
      - 32-char hex → "jora"
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
                    if re.fullmatch(r"[a-f0-9]{32}", jid):
                        src = "jora"
                    elif re.fullmatch(r"\d+", jid):
                        src = "linkedin"
                    else:
                        src = "unknown"
                seen.add((src, jid))
            except json.JSONDecodeError:
                print(f"            (warn) seen file line {ln} 壞掉，跳過")
    return seen


def append_seen(job_id: str, jd_hash_val: str, title: str, company: str,
                path: Path = Path(SEEN_FILE), source: str = "linkedin") -> None:
    record = {
        "job_id": job_id,
        "source": source,  # 2026-08-22 新增, 之後區分 LinkedIn / Jora / JobStreet
        "jd_hash": jd_hash_val,
        "fetched_at": datetime.now(TZ_LOCAL).isoformat(timespec="seconds"),
        "title": (title or "")[:200],
        "company": (company or "")[:100],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_jd_cache_from_jsons(pattern: str = "*_product_jobs_*_jd.json",
                               skip_files: set[str] | None = None) -> dict:
    """
    從所有 *_jd.json 檔案載入 JD cache: {(source, job_id): {jd_text, jd_lines, jd_hash, ...}}。
    用作 enrich_with_jd 的跨 run cache 來源（避免已抓過的 JD 重抓）。

    2026-08-22 改: 從 {job_id: ...} 改為 {(source, job_id): ...}, 避免 LinkedIn / JobStreet 數字 ID 撞

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
                if re.fullmatch(r"[a-f0-9]{32}", jid):
                    src = "jora"
                elif re.fullmatch(r"\d+", jid):
                    src = "linkedin"
                else:
                    src = "unknown"
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
_VISA_RES = {
    level: re.compile("|".join(pats), re.IGNORECASE)
    for level, pats in VISA_PATTERNS.items()
}


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
    - linkedin:  =HYPERLINK(".../jobPosting/{id}", "{id}")
    - jora:      =HYPERLINK("{full_jora_url}", "{full_jora_url}")
    - jobstreet: =HYPERLINK(".../job/{id}", ".../job/{id}")  (2026-08-23 從 slug-id 改純 id)
    """
    if source == "jora":
        full_url = url or f"{JORA_BASE}/job/Product-Manager-{job_id}"
    elif source == "jobstreet":
        full_url = f"{JOBSTREET_BASE}/job/{job_id}"
    else:  # linkedin (default)
        full_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    return f'=HYPERLINK("{full_url}","{full_url}")'


def parse_sheet_row_to_key(row: list[str]) -> tuple[str, str] | None:
    """從 sheet 的某 row 解出 (source, job_id), 用於 dedup。

    輸入 row 格式: [A=New, B='', C=date, D=source_label, E=URL, F=company, G=title, H=JD, I=loc, J=wm, K=visa]
    D 欄解 source: "LinkedIn / Minimax" → linkedin, "Jora / Minimax" → jora, "JobStreet / Minimax" → jobstreet
    E 欄解 job_id: 依 source 不同用不同 regex (LinkedIn digit / jobPosting/digit / Jora 32-hex / JobStreet /job/digit)

    Returns None 如果 row 沒 E 欄或解不出 job_id (e.g. J 欄空 + 沒 K 欄的 header row).
    """
    if len(row) < 5 or not row[4].strip():
        return None
    d_cell = row[3].strip() if len(row) > 3 else ""
    if "JobStreet" in d_cell:
        src = "jobstreet"
    elif "Jora" in d_cell:
        src = "jora"
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
    # Jora: 32-char hex hash 在 URL 尾
    m = re.search(r"([a-f0-9]{32})(?:\?|$)", cell)
    if m:
        return ("jora", m.group(1))  # 強制 jora
    # JobStreet: /job/{digit} 純 id (2026-08-23 改後格式)
    m = re.search(r"/job/(\d+)(?:\?|$)", cell)
    if m and "jobstreet" in cell.lower():
        return ("jobstreet", m.group(1))
    return None


def push_to_sheet(jobs: list[dict], sheet_url: str,
                  sa_key_path: str = SHEET_SA_KEY,
                  source: str = DEFAULT_SHEET_SOURCE,
                  dry_run: bool = False,
                  gid: str | int | None = None,
                  location: str = LOCATION) -> dict:
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
    """
    from datetime import date
    import gspread
    from google.oauth2.service_account import Credentials

    sheet_id = extract_sheet_id(sheet_url)
    resolved_gid = gid if gid is not None else extract_gid(sheet_url)
    if resolved_gid is None:
        raise ValueError(
            "❌ 沒帶 gid 會撞到 jobs_raw (第一個 tab)\n"
            "   修法: URL 帶 #gid=<worksheet-gid>  或  --gid <worksheet-gid>  或  --to-sheet 用 SG_RAW_URL"
        )
    gid = str(resolved_gid)

    if dry_run:
        print(f"  [DRY RUN] 不會真的寫入")
        print(f"  sheet_id: {sheet_id[:20]}...")
        print(f"  gid: {gid}")
        print(f"  source label = {source!r}")
        print(f"  共 {len(jobs)} 筆準備寫入 (after skip/dedup/visa)")
        for j in jobs[:3]:
            e_preview = build_e_formula(j.get("source", "linkedin"), j.get("job_id", ""), j.get("url", ""))
            print(f"    [preview] title={j.get('title','')[:35]:35}  E={e_preview}")
        return {"written": 0, "skipped_dup": 0, "dry_run": True}

    # 1) 認證 + 開 sheet
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(str(sa_key_path), scopes=scopes)
    gc = gspread.authorize(creds)
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


def _build_sheet_row(job: dict, source_label: str, location: str,
                      existing_keys: set[tuple[str, str]]) -> list | None:
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
    # Visa detection 只對 Singapore 跑 (TW/CN 不檢查, 工作簽限制不常見)
    if location.lower() == "singapore":
        visa = detect_visa_signal(jd_text)
    else:
        visa = ""
    jd_oneline = re.sub(r"\s+", " ", jd_text).strip()
    work_mode = job.get("work_mode", "") or extract_work_mode(jd_text, job.get("title", ""))
    e_formula = build_e_formula(job_source, job_id, job.get("url", ""))
    return [
        "New",                                              # A
        "",                                                 # B (留空)
        date.today().isoformat(),                           # C
        source_label,                                       # D
        e_formula,                                          # E (含超連結)
        job.get("company", ""),                            # F
        job.get("title", ""),                              # G
        jd_oneline,                                         # H (單行, 自動裁切)
        job.get("location", ""),                           # I
        work_mode,                                          # J (Remote/Hybrid/Onsite)
        visa,                                               # K
    ]


def _write_rows_to_sheet(ws, next_row: int, new_rows: list[list],
                          skipped_dup: int = 0, skipped_no_jd: int = 0) -> dict:
    """把 new_rows 寫到 sheet, 回傳 stats dict (跟原本 push_to_sheet 一樣格式)。

    三段式寫入 (防 F10 公式注入，且 intentional formula 最後才啟用):
      - Phase 1: A:D 用 RAW
      - Phase 2: F:K 用 RAW
      - Phase 3: E 欄 hyperlink formula 用 USER_ENTERED
    只有我們自己生成的 E 欄 HYPERLINK 會被當公式, 其他所有外部 scraped text
    (title / company / JD / location / source label / visa) 都不能被當公式執行。
    """
    end_row = next_row + len(new_rows) - 1
    print(f"  準備寫入 row {next_row}-{end_row} ({len(new_rows)} 筆, 兩段式寫入防公式注入)...")
    # 防呆: 自動擴展 sheet rows (避免 end_row > row_count 報 400)
    if end_row > ws.row_count:
        extra = end_row - ws.row_count + 100
        print(f"  ⚠️  sheet 只有 {ws.row_count} rows, 加 {extra} rows 避免 overflow")
        ws.add_rows(extra)
    # External scraped text is written first as RAW. If a later data phase fails,
    # the E-column live formula is never activated.
    a_d_rows = [[r[i] for i in (0, 1, 2, 3)] for r in new_rows]
    f_k_rows = [[r[i] for i in (5, 6, 7, 8, 9, 10)] for r in new_rows]
    e_only_rows = [[r[4]] for r in new_rows]
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
# LinkedIn compatibility surface
# Implementation owner: jobs_scraper.sources.linkedin
# ─────────────────────────────────────────────────────────────
JOB_CARD_SEL = linkedin_source.JOB_CARD_SEL
TITLE_SEL = linkedin_source.TITLE_SEL
COMPANY_SEL = linkedin_source.COMPANY_SEL
LOC_SEL = linkedin_source.LOC_SEL
TIME_SEL = linkedin_source.TIME_SEL
LINK_SEL = linkedin_source.LINK_SEL
JD_DESC_SEL = linkedin_source.JD_DESC_SEL
JD_BLOCK_SEL = linkedin_source.JD_BLOCK_SEL
_clean = linkedin_source._clean


def build_list_url(tpr: str, start: int, location: str = LOCATION, geo_id: str = GEO_ID) -> str:
    return linkedin_source.build_list_url(
        tpr, start, location, geo_id, keywords=KEYWORDS,
    )


def parse_list_page(html: str) -> list[dict]:
    return linkedin_source.parse_list_page(html)


def fetch_list_page(tpr: str, start: int, location: str = LOCATION, geo_id: str = GEO_ID) -> str:
    return linkedin_source.fetch_list_page(
        _cc_session, tpr, start, location, geo_id, keywords=KEYWORDS,
    )


def build_jd_url(job_id: str) -> str:
    return linkedin_source.build_jd_url(job_id)


def fetch_jd(job_id: str) -> dict:
    return linkedin_source.fetch_jd(_cc_session, job_id)

# ─────────────────────────────────────────────────────────────
# 主程式
# ─────────────────────────────────────────────────────────────
def human_sleep(label: str = ""):
    s = random.uniform(SLEEP_MIN, SLEEP_MAX)
    if label:
        print(f"            sleep {s:.1f}s ({label})", flush=True)
    time.sleep(s)


def crawl_list(tpr: str, max_pages: int, location: str = LOCATION, geo_id: str = GEO_ID) -> list[dict]:
    seen: set[str] = set()
    all_jobs: list[dict] = []

    for p in range(max_pages):
        start = p * PAGE_SIZE
        print(f"\n  [list page {p+1}] start={start}")
        try:
            html = fetch_list_page(tpr, start, location, geo_id)
        except Exception as e:
            print(f"            FAIL: {type(e).__name__}: {e}")
            return all_jobs
        Path(f"raw_list_{p+1}.html").write_text(html)
        jobs = parse_list_page(html)
        new_jobs = [j for j in jobs if j["job_id"] not in seen]
        for j in new_jobs:
            seen.add(j["job_id"])
            all_jobs.append(j)
        print(f"            收 {len(jobs)}, 新增 {len(new_jobs)}, 重複 {len(jobs)-len(new_jobs)}, 累計 {len(all_jobs)}")
        if not new_jobs or len(jobs) < PAGE_SIZE:
            print("            到底了")
            break
        if p < max_pages - 1:
            human_sleep("list")

    return all_jobs


# ─────────────────────────────────────────────────────────────
# Jora compatibility surface
# Implementation owner: jobs_scraper.sources.jora
# ─────────────────────────────────────────────────────────────
def build_jora_list_url(jora_tpr: str, page: int, keyword: str = JORA_KEYWORD,
                        location: str = JORA_LOCATION) -> str:
    return jora_source.build_list_url(jora_tpr, page, keyword, location)


def parse_jora_list_page(html: str, location: str = JORA_LOCATION) -> list[dict]:
    return jora_source.parse_list_page(html, location=location)


def fetch_jora_jd(url: str) -> dict:
    return jora_source.fetch_jd(_cc_session, url, sleep_fn=time.sleep)


def crawl_jora_list(tpr: str, max_pages: int,
                    keyword: str = JORA_KEYWORD,
                    location: str = JORA_LOCATION) -> list[dict]:
    return jora_source.crawl_list(
        _cc_session, tpr, max_pages,
        tpr_map=JORA_TPR,
        keyword=keyword,
        location=location,
        sleep_fn=human_sleep,
    )


# ─────────────────────────────────────────────────────────────
# JobStreet compatibility surface
# Implementation owner: jobs_scraper.sources.jobstreet
# ─────────────────────────────────────────────────────────────
JOBSTREET_DETAIL_QUERY = jobstreet_source.JOBSTREET_DETAIL_QUERY


def build_jobstreet_list_url(keyword: str, page: int, daterange: str,
                              worktype: str = JOBSTREET_WORKTYPE_FT,
                              where: str = JOBSTREET_LOCATION,
                              page_size: int = 20) -> str:
    return jobstreet_source.build_list_url(
        keyword,
        page,
        daterange,
        worktype=worktype,
        where=where,
        page_size=page_size,
        list_api=JOBSTREET_LIST_API,
    )


def parse_jobstreet_list_page(data: dict, keyword: str) -> list[dict]:
    return jobstreet_source.parse_list_page(data, keyword)


def fetch_jobstreet_jd(job_id: str) -> dict:
    return jobstreet_source.fetch_jd(
        _cc_session,
        job_id,
        graphql_url=JOBSTREET_GRAPHQL,
        query=JOBSTREET_DETAIL_QUERY,
    )


def crawl_jobstreet_list(daterange: str, max_pages: int,
                          keywords: list[str] | None = None,
                          worktype: str = JOBSTREET_WORKTYPE_FT) -> list[dict]:
    return jobstreet_source.crawl_list(
        _cc_session,
        daterange,
        max_pages,
        keywords=keywords if keywords is not None else JOBSTREET_KEYWORDS,
        worktype=worktype,
        where=JOBSTREET_LOCATION,
        page_size=20,
        list_api=JOBSTREET_LIST_API,
        sleep_fn=human_sleep,
    )


def enrich_with_jd(jobs: list[dict], skip_pat: re.Pattern | None = None,
                    seen_ids: set[tuple[str, str]] | None = None,
                    refetch: bool = False,
                    json_cache: dict | None = None) -> tuple[list[dict], dict]:
    """
    抓 JD。命中 skip 關鍵字的不抓；已抓過的也不抓。

    Cache 來源 (依序檢查):
      1. in-memory jd_text: 同一個 run 內已 enrich 過
      2. json_cache: 從磁碟 *_jd.json 載入的跨 run cache (load_jd_cache_from_jsons)
      3. seen_ids (僅用於日誌): seen_jds.jsonl 內見過的 (但可能 cache 已被刪)

    --refetch 時跳過所有 cache，強制重抓。

    2026-08-22: json_cache / seen_ids 都改成 (source, job_id) tuple, 避免 LinkedIn / JobStreet 數字 ID 撞
    """
    skip_pat = skip_pat or _make_skip_pattern([])
    seen_ids = seen_ids or set()
    json_cache = json_cache or {}
    n_total = len(jobs)

    # 統計 n_skip / n_cached / n_to_fetch
    n_skip = 0
    n_cached = 0
    for j in jobs:
        if match_skip_reason(j.get("title", ""), skip_pat):
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
    if skip_pat.pattern and n_skip:
        print(f"  skip 規則: {skip_pat.pattern}")
    print(f"  json_cache: {len(json_cache)} 筆 / seen file: {len(seen_ids)} 筆 / refetch={refetch}")

    out = []
    stats = {"total": n_total, "skipped": 0, "cached": 0, "fetched": 0, "failed": 0}
    for i, j in enumerate(jobs, 1):
        reason = match_skip_reason(j.get("title", ""), skip_pat)
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
        print(f"  [{i}/{n_total}] {j['job_id']} {j['title'][:50]}")
        if src == "jora":
            result = fetch_jora_jd(j.get("url", f"{JORA_BASE}/job/Product-Manager-{jid}"))
        elif src == "jobstreet":
            result = fetch_jobstreet_jd(jid)
        else:
            result = fetch_jd(jid)
        if result.get("jd_text"):
            j2["jd_text"] = result["jd_text"]
            j2["jd_lines"] = result["jd_lines"]
            j2["jd_hash"] = jd_hash(result["jd_text"])
            # 從 JD result 補公司/位置 (Jora 列表頁沒公司, LinkedIn 已有, 但安全起見都覆寫)
            if result.get("company"):
                j2["company"] = result["company"]
            if result.get("location"):
                j2["location"] = result["location"]
            stats["fetched"] += 1
            print(f"            ✓ {len(result['jd_text'])} chars / {len(result['jd_lines'])} lines / co={j2.get('company','')[:30]}")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("range", nargs="?", default=DEFAULT_TPR,
                    choices=list(TIME_RANGES.keys()),
                    help=f"time range (default {DEFAULT_TPR})")
    ap.add_argument("--source", default="linkedin", choices=["linkedin", "jora", "jobstreet"],
                    help="資料來源 (default: linkedin). jora=sg.jora.com (HTML parse), jobstreet=sg.jobstreet.com (API+GraphQL)")
    ap.add_argument("--location", default=None,
                    help=f"目標城市/國家 (default: {LOCATION}); 已知 preset: {', '.join(KNOWN_GEO_IDS.keys())}")
    ap.add_argument("--geo-id", default=None,
                    help=f"LinkedIn geoId (default: {GEO_ID}); 跟 --location 一起給")
    ap.add_argument("--with-jd", action="store_true",
                    help="抓取每個職缺的 JD 全文 (會增加不少時間)")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="override 預設頁數上限")
    ap.add_argument("--skip-keywords", nargs="*", default=None,
                    help=f"JD 階段要跳過的標題關鍵字（覆寫預設）。"
                         f"預設: {' '.join(DEFAULT_SKIP_KEYWORDS)}")
    ap.add_argument("--no-skip", action="store_true",
                    help="完全跳過 skip 過濾，全部都抓 JD")
    ap.add_argument("--refetch", action="store_true",
                    help="忽略 seen_jds.jsonl，重新抓所有 JD")
    ap.add_argument("--reset-seen", action="store_true",
                    help="刪掉 seen_jds.jsonl 後結束（清空紀錄）")
    ap.add_argument("--seen-file", default=SEEN_FILE,
                    help=f"已抓 JD 記錄檔路徑 (default: {SEEN_FILE})")
    ap.add_argument("--to-sheet", default=None, metavar="URL_OR_ID",
                    help=f"抓完後把結果 append 到 Google Sheet (URL 或 ID; 不帶 gid 會報錯, 請用 '{SG_RAW_URL}')")
    ap.add_argument("--gid", default=None, type=int,
                    help=f"指定要寫的 worksheet gid (e.g. {SG_RAW_GID}); 不指定時用 URL 內 #gid=")
    ap.add_argument("--sheet-source", default=DEFAULT_SHEET_SOURCE,
                    help=f"寫入 Sheet 的 Source 欄位值 (default: {DEFAULT_SHEET_SOURCE})")
    ap.add_argument("--dry-run-sheet", action="store_true",
                    help="跟 --to-sheet 一起用，只印將寫入什麼、不真的寫")
    ap.add_argument("--json-summary", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    seen_path = Path(args.seen_file)

    if args.reset_seen:
        n = reset_seen(seen_path)
        print(f"已刪除 {seen_path} ({n} 筆紀錄)")
        return

    tpr, default_max = TIME_RANGES[args.range]
    if args.source == "jora":
        default_max = JORA_MAX_PAGES[args.range]
    elif args.source == "jobstreet":
        default_max = JOBSTREET_MAX_PAGES[args.range]
    max_pages = args.max_pages or default_max

    skip_pat = None
    if not args.no_skip:
        skip_words = args.skip_keywords if args.skip_keywords is not None else DEFAULT_SKIP_KEYWORDS
        skip_pat = _make_skip_pattern(skip_words)

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
    elif args.source == "jora":
        if not location:
            location = JORA_LOCATION
        if args.sheet_source == DEFAULT_SHEET_SOURCE:
            args.sheet_source = "Jora / Minimax"
    else:  # jobstreet
        if not location:
            location = JOBSTREET_LOCATION
        # JobStreet 不需要 geo_id
        geo_id = None
        if args.sheet_source == DEFAULT_SHEET_SOURCE:
            args.sheet_source = "JobStreet / Minimax"

    if args.source == "linkedin":
        print(f"==== LinkedIn Jobs / {location} (geoId={geo_id}) / {args.range} / f_TPR={tpr} ====")
    elif args.source == "jora":
        jora_tpr = JORA_TPR[args.range]
        print(f"==== Jora Jobs / {location} / {args.range} / a={jora_tpr} ====")
    else:
        js_tpr = JOBSTREET_TPR[args.range]
        print(f"==== JobStreet Jobs / {location} / {args.range} / daterange={js_tpr} (multi-keyword={len(JOBSTREET_KEYWORDS)}) ====")
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
    if args.source == "jora":
        jobs = crawl_jora_list(args.range, max_pages)
    elif args.source == "jobstreet":
        js_tpr = JOBSTREET_TPR[args.range]
        jobs = crawl_jobstreet_list(js_tpr, max_pages, keywords=JOBSTREET_KEYWORDS)
    else:
        jobs = crawl_list(tpr, max_pages, location=location, geo_id=geo_id)
    if not jobs:
        print("\n無資料，結束。")
        if args.json_summary:
            print("JOBS_SCRAPER_SUMMARY=" + json.dumps({
                "jobs_found": 0, "jobs_enriched": 0, "jobs_failed": 0,
                "output_file": None, "written": 0, "skipped_dup": 0,
                "skipped_no_jd": 0,
            }, ensure_ascii=False, separators=(",", ":")))
        return

    # 1.5) 載入 JD cache (跨 run 從 *_jd.json 抓)，跳過當前將輸出的檔
    suffix = f"_{args.range}{'_jd' if args.with_jd else ''}"
    # 檔名以 source + location 為 prefix (sg_product_jobs, tw_, jora_sg_), 避免跨源/跨國 cache 污染
    location_short = location.lower().replace(' ', '')
    short_names = {
        "singapore": "sg", "taiwan": "tw", "hongkong": "hk", "japan": "jp",
    }
    loc_prefix = short_names.get(location_short, location_short)
    # 各 source cache 獨立 prefix (sg_, jora_sg_, jobstreet_sg_), 避免跨源/跨國 cache 污染
    if args.source == "jora":
        prefix = f"jora_{loc_prefix}"
    elif args.source == "jobstreet":
        prefix = f"jobstreet_{loc_prefix}"
    else:
        prefix = loc_prefix
    out = Path(f"{prefix}_product_jobs{suffix}.json")
    json_cache = {}
    if args.with_jd and not args.refetch:
        print(f"\n==== 載入 JD cache (排除 {out.name}) ====")
        json_cache = load_jd_cache_from_jsons(skip_files={out.name})

    # 2) 抓 JD (可選)
    stats = None
    if args.with_jd:
        jobs, stats = enrich_with_jd(jobs, skip_pat=skip_pat,
                                    seen_ids=seen_ids, refetch=args.refetch,
                                    json_cache=json_cache)

    # 3) 存檔
    out.write_text(json.dumps(jobs, ensure_ascii=False, indent=2))
    print(f"\n==== 寫到 {out.resolve()} ({len(jobs)} 筆) ====")
    if stats:
        print(f"     JD: skip={stats['skipped']}  cached={stats['cached']}  "
              f"fetched={stats['fetched']}  failed={stats['failed']}")
    if seen_path.exists() and args.with_jd:
        total = sum(1 for _ in open(seen_path, "r", encoding="utf-8") if _.strip())
        print(f"     seen file: {seen_path} ({total} 筆累計)")

    # 4) 寫到 Google Sheet (可選)
    sheet_stats = {"written": 0, "skipped_dup": 0, "skipped_no_jd": 0}
    if args.to_sheet:
        if not args.with_jd:
            print("\n⚠️  --to-sheet 需要 --with-jd 才能填 JD 內容 (column H)")
            print("    跳過 sheet 寫入")
        else:
            print(f"\n==== 寫到 Google Sheet: {args.to_sheet[:50]}... ====")
            sheet_stats = push_to_sheet(
                jobs, args.to_sheet,
                sa_key_path=SHEET_SA_KEY,
                source=args.sheet_source,
                dry_run=args.dry_run_sheet,
                gid=args.gid,
                location=location,
            )
            print(f"\n  結果: {sheet_stats}")

    if args.json_summary:
        print("JOBS_SCRAPER_SUMMARY=" + json.dumps({
            "jobs_found": len(jobs),
            "jobs_enriched": ((stats.get("cached", 0) + stats.get("fetched", 0)) if stats else 0),
            "jobs_failed": (stats.get("failed", 0) if stats else 0),
            "output_file": str(out.resolve()),
            "written": int(sheet_stats.get("written", 0)),
            "skipped_dup": int(sheet_stats.get("skipped_dup", 0)),
            "skipped_no_jd": int(sheet_stats.get("skipped_no_jd", 0)),
        }, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
