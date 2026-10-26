# Skip Filter 完整邏輯 (2026-08-29, v8.5 Bounded Repair)

> **Single source of truth**: `sg_product_jobs.py` 的 `match_skip_reason()` 是唯一入口, 本文件整理所有規則、判定流程、擴展方式。
> **對應章節**: RULES.md §1.1 / §1.2 / §15.9 / §15.19 / §15.19.1 / §15.20, BOOT_PROMPT.md §4.5
> **Dispatch**: `SKIP_FILTER_V8_5_BOUNDED_REPAIR_DISPATCH/`

---

## §1. 核心設計原則 (v8.5 改動)

> **Seniority is not role relevance.**

v8.5 之前的 v8.4 設計: senior marker (e.g. "senior", "director", "VP") 全域救回任何 skip hit。
v8.5 修法: **senior marker 不再全域救回**。理由: "Director of Sales" 仍是 sales role, "Senior Accountant" 仍是 accounting role。seniority 不改變 function 本質。

同時, contextual words (sales/quality/support/test/contract) 不再是 unconditional hard skip。
理由: "Product Manager, Sales Platform" 是真的 PM 職位, "AI Product Manager - 12 Month Contract" 是合約 PM, 不應被 "Sales" 或 "Contract" 詞殺掉。

**設計 trade-off**:
- 高 precision on obvious garbage (e.g. "倉管助理", "Operations Manager")。
- 高 recall on plausible targets (e.g. PM titles with any context)。
- Grey-zone 角色 (e.g. "Senior Marketing Specialist") 走 narrow ambiguity rule, 不是 blanket skip 也不是 blanket rescue。

---

## §2. 7 層 Precedence 流程圖

`match_skip_reason(title, skip_pat=None, *, source=None)` 按以下順序跑 (per 02_PRECEDENCE_AND_RULE_MODEL.md):

```
1. empty title                  → KEEP
2. L1 entry-level gate          → SKIP "entry_level"    (intern/junior/graduate/entry/jr/助理/初階)
3. Assistant narrow rule        → SKIP "assistant" 或 KEEP (僅 AVP/VP/director + target context)
4. L0 target-role guard         → KEEP                  (Product Manager, Head of Product, etc.)
5. L2 hard non-target role       → SKIP "hard_non_target" (designer, analyst, account*, accountant, HR, procurement, BD)
6. L3 contextual role-shape     → SKIP "contextual_role" (Sales Manager, Quality Engineer, QA Lead, etc.)
7. L5 specialist narrow rule    → SKIP "specialist" 或 KEEP (senior + target context)
8. L4 Chinese general skip      → SKIP "chinese_skip"
9. L6 104 source-specific       → SKIP "tw_extra_skip" (only source=onezerofour)
10. no rule matched             → KEEP
```

**注意 "7 層 vs 10 步"**:

- 步驟 1 (empty title) 跟步驟 10 (no rule matched) 不是 filter layer, 是 empty/fallthrough control state。
- 步驟 2-9 才是真正的 7 個 filter layer (L1 / Assistant narrow / L0 / L2 / L3 / L5 / L4 / L6)。等等, 那是 8 個? 重數一次: L1 (entry-level) / Assistant narrow / L0 (target role) / L2 (hard non-target) / L3 (contextual) / L5 (specialist narrow) / L4 (Chinese general) / L6 (104 specific) = 8 layer。但 Assistant narrow 跟 L5 specialist narrow 是 *narrow ambiguity rule*, 不是純 filter layer (它們在某些條件下會 KEEP 而不是 SKIP)。

所以嚴格說是 **8 個 filter / rule 步驟**, 加上 2 個 control state (empty / fallthrough), 總共 10 個 executable control step。標題說 "7 層" 是 legacy 計法, 跟 02_PRECEDENCE_AND_RULE_MODEL.md dispatch 的 7-layer 命名一致, 但 executable 真的有 10 個 step。讀者不要從 "7 層" 推導 precedence order, 必須看上面 1-10 號的真實順序。

**關鍵**: entry-level 跟 assistant 都在 **target-role guard 之前** 跑。Junior Product Manager 跟 Assistant Product Manager 必須先跳, 不被 target guard 救。

---

## §3. L0 Target Role Guard (新增)

`TARGET_ROLE_PATTERNS` (sg_product_jobs.py:435+) — 命中就 KEEP, override 後面所有 layer。

### 3.1 英文 (15 個 family, 含 Repair2 + Repair3 修法)

```python
# v8.5 Repair3 (P1-01): 抽 _V85_PRODUCT_FAMILY_SEP 共享 fragment,
# 認 whitespace + ASCII hyphen + en-dash U+2013 + non-breaking hyphen U+2011
_V85_PRODUCT_FAMILY_SEP = r"[\s\u2011\u2013\-]+"
_V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD = (
    r"(?!" + _V85_PRODUCT_FAMILY_SEP + r"(?:marketing|design|analyst|validation|certification|support))"
)

r"product\s+manager",                # 標準 PM
r"product\s+lead",                   # Product Lead
r"product\s+owner",                  # PO
r"product\s+director",               # Product Director (e.g. "Senior Product Director")
# 5 個 leadership pattern 一致套用 _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD (Repair2 + Repair3)
r"head\s+of\s+product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
r"director\s+of\s+product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
r"vp[,]?\s*(of\s+)?product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
r"vice\s+president[,]?\s*(of\s+)?product" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
r"chief\s+product\s+officer" + _V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD,
r"technical\s+product\s+manager",
r"ai\s+product\s+manager",
r"senior\s+product\s+manager",
r"principal\s+product\s+manager",
r"lead\s+product\s+manager",
r"group\s+product\s+manager",
r"head\s+of\s+ai",
r"director\s+of\s+ai",
```

### 3.2 中文 (5 個 substring)

```python
r"產品經理", r"產品主管", r"產品總監", r"產品負責人", r"產品長",
```

### 3.3 編譯

```python
def _v85_compile_mixed(patterns):  # 自動分流 EN (word-boundary) 跟 CN (substring)
    ...

TARGET_ROLE_REGEX = _v85_compile_mixed(TARGET_ROLE_PATTERNS)
```

### 3.4 為什麼要 negative lookahead?

`Director of Product Marketing` 內 "Director of Product" 會 match target guard。但這是 marketing role, 不是 PM role。
解法: pattern 加 `(?!\s+(marketing|design|analyst|validation|certification))` 排除後面接這些詞。

#### 3.4.1 共享 Product Family Separator (v8.5 Repair3 P1-01)

v8.5 Repair3 抽出 `_V85_PRODUCT_FAMILY_SEP = r"[\s\u2011\u2013\-]+"` 共用 separator fragment 給所有 Product-* family 用。這個 fragment 同時接受:

- ASCII whitespace (space, tab, newline)
- ASCII hyphen-minus (`-`)
- U+2011 NON-BREAKING HYPHEN (`‑`)
- U+2013 EN DASH (`–`)

不是只認 whitespace。例如 `Product-Marketing Manager`、`Product–Marketing Manager` 都會被 `product[SEP]marketing` 命中。

注意:

- 不做全域 punctuation normalization (e.g. `Product/Marketing` 仍視為兩個 token)
- 不認 figure dash U+2012 (`‒`) — 那個留給 sales SEP 處理
- 仍維持 negative lookahead 防 substring 誤抓

#### 3.4.2 為什麼 `_v85_compile_mixed` 的 CJK detection 用範圍檢查 (v8.5 Repair7 P1-06)?

`_v85_compile_mixed` 編譯時需要分流英文 (用 word-boundary wrap `(?<![a-z])(?![a-z])`) 跟中文 (用 substring)。

早期版本用 `any(ord(c) >= 128 for c in p)` 判斷 CJK, 但這會把 SEP fragment 內的非 CJK 非 ASCII 字元 (e.g. `\u2012` FIGURE DASH) 誤判成 CJK, 導致整個 pattern list 走 `zh_patterns` 分支而不套用 word-boundary wrap。實際後果: "Quality Engineer" 在 "Quality Engineering" 內被 substring 誤抓。

v8.5 Repair7 P1-06 改成檢查實際 CJK ideograph range (`U+4E00-U+9FFF` 等), 不是 `>= 128`。同時把 `_V85_SALES_SEP` 內 literal `‒` 改成 `\u2012` escape, 確保 source string 為純 ASCII, 雙重保險。

### 3.5 為什麼 "Director of Product" KEEP?

target role guard 接受 PM 系列的 director 級 (e.g. "Director of Product Engineering", "Director of Product, Quality Platform")。
但 v8.5 拒絕 "Director of Product Marketing" (因為 marketing 排除), "Director of Product Design" (因為 design 排除) 等。

---

## §4. L1 Entry-Level Gate (新增)

`ENTRY_LEVEL_PATTERNS` (sg_product_jobs.py:471+) — 命中就 SKIP, no senior rescue, **在 target guard 之前跑**。

### 4.1 英文

```python
r"intern", r"internship", r"trainee", r"graduate", r"\bgrad\b",
r"\bentry[\s\-]?level\b", r"\bentry\b",
r"junior", r"\bjr\b",
```

### 4.2 中文 (substring)

```python
r"實習", r"工讀", r"培訓", r"訓練生", r"應屆", r"畢業", r"助理", r"初階",
```

### 4.3 為什麼 entry-level 先於 target guard?

- "Junior Product Manager" → L1 entry-level 命中 "junior" → SKIP
- "Product Manager Intern" → L1 命中 "intern" → SKIP
- "Assistant Product Manager" → L1 命中 "助理" → SKIP (順帶 assistant narrow rule 觸發)
- v8.4 之前: target guard 沒分這層, "Product Manager" 內部 substring 救回 junior/intern — 不對

---

## §5. Assistant Narrow Rule (新增, P1-02)

**預設 SKIP**。**只有 BOTH 條件成立才 KEEP**:
1. `assistant` / `asst` 後直接接 senior trigger (`vice president` / `vp` / `director` / `avp`)
2. title 含 target context (`product` / `ai` / `platform` / `growth` / `data`)

### 5.1 邏輯

```python
# Real runtime (Repair1 word-boundary compiled context):
ASSISTANT_KEEP_CONTEXTS = ["product", "ai", "platform", "growth", "data"]
ASSISTANT_KEEP_CONTEXT_REGEX = _v85_compile_contexts_as_regex(ASSISTANT_KEEP_CONTEXTS)
ASSISTANT_SENIOR_TRIGGERS = ["vice president", "vp", "director", "avp"]

def _v85_is_assistant_target_senior(title: str) -> bool:
    """assistant narrow rule: KEEP only if both (1) assistant + senior trigger
    adjacent (2) target context matches (word-boundary, Repair1)."""
    t = title.lower()
    has_adjacent_senior = any(
        f"assistant {trig}" in t or f"assistant, {trig}" in t or f"asst {trig}" in t
        for trig in ASSISTANT_SENIOR_TRIGGERS
    )
    if not has_adjacent_senior:
        return False
    return ASSISTANT_KEEP_CONTEXT_REGEX.search(t) is not None
```

### 5.2 必 KEEP (滿足 narrow)

- "Assistant Vice President, Product" → AVP + product → KEEP
- "Assistant VP, AI Product" → VP + ai → KEEP
- "Assistant Director, Product Management" → director + product → KEEP

### 5.3 必 SKIP (不滿足)

- "Assistant to CEO" → 沒 senior trigger
- "Administrative Assistant" → 沒 senior trigger
- "Assistant Director, Human Resources" → director + **無 product context** → SKIP
- "Assistant Vice President, Finance" → VP + **無 product context** → SKIP
- "Assistant Product Manager" → "assistant" 後面是 "Product" 不是 senior trigger
- "Assistant Manager, Sales" → "Assistant Manager" 不是 senior trigger (manager 不在 senior list)

---

## §6. L2 Hard Non-Target Role (新增, P0-01 核心改動)

`HARD_NON_TARGET_ROLE_PATTERNS` (sg_product_jobs.py:486+) — 命中就 SKIP, **no senior rescue**。

### 6.1 為什麼這是新行為?

v8.4: "Senior Product Designer" 命中 "product designer" 後, senior marker 救回 → KEEP (錯!)
v8.5: "Senior Product Designer" 命中 "product designer" → SKIP (designer 是 hard non-target)

seniority 不改變 function 本質。"Director of Sales" 仍是 sales role, "Senior Accountant" 仍是 accounting role。

### 6.2 英文 (24 個 family)

```python
# Product family (non-PM)
r"product\s+designer", r"product\s+designers",
r"product\s+validation", r"product\s+certification",
r"product\s+analyst", r"product\s+marketing",
# Account family
r"account\s+manager", r"account\s+managers",
r"account\s+management",  # "Director, Key Account Management"
r"key\s+account\s+manager", r"key\s+account\s+managers",
r"key\s+account\s+management",
r"client\s+manager", r"client\s+managers", r"client\s+management",
r"relationship\s+manager", r"relationship\s+managers", r"relationship\s+management",
r"account\s+executive",
r"accountant", r"accountants", r"accounting",
r"audit", r"auditor", r"auditors",
# HR / Recruiting
r"human\s+resources",
r"recruiter", r"recruiters", r"recruiting",
r"recruitment", r"head\s+of\s+recruitment",
# Procurement
r"procurement", r"purchasing", r"purchaser", r"purchasers",
r"buyer", r"buyers", r"merchandiser", r"merchandisers",
# Sales/BD (整個 family, 包含裸 "business development")
r"business\s+development",
# Quality/Test inspector
r"\binspector\b", r"\btester\b", r"inspection\s+(engineer|manager|lead|specialist)",
# Generic support
r"coordinator", r"administrator", r"clerk", r"secretary",
```

### 6.3 中文 (substring, 跨 source 跳)

```python
r"會計", r"財會", r"出納", r"稽核", r"稅務",
r"人資", r"人力資源", r"招募", r"薪酬", r"總務",
r"採購",
r"協調", r"統籌", r"秘書", r"行政",
r"工讀生", r"書記",
r"行銷", r"市場專員",
```

### 6.4 為什麼 "sales" 不在這層?

v8.5 把裸 "sales" 從 L2 移除, 移到 L3 (contextual role-shape) 處理。
原因: "Program Manager, Sales Platform" 內 "Sales" 是 context, 不是 role suffix。
L3 要求 "sales" 後接 role suffix (e.g. "Sales Manager", "Sales Director") 才跳。

### 6.5 為什麼 "business development" 仍在這層?

BD 整個 family 是 sales track, 沒有 lookalike 案例 (G 系列沒 BD 案例)。
"Senior Business Development Manager" 預期 SKIP (A06), 所以 L2 跳 BD 仍合理。

---

## §7. L3 Contextual Role-Shape Exclusion (新增, P0-03 核心改動)

`CONTEXTUAL_ROLE_PATTERNS` (sg_product_jobs.py:517+) — 只在 domain word + role suffix 才跳。

### 7.1 為什麼這是新行為?

v8.4: "Product Manager, Sales Platform" 命中 "sales" → SKIP (錯!)
v8.5: "Product Manager, Sales Platform" 命中 "sales" 但 "sales" 後面是 "Platform" 不是 role suffix → L3 不命中 → KEEP (對!)

### 7.1.1 Sales role-shape 共享 separator fragment (Repair5 P1-01)

v8.5 Repair5 抽出共用 separator 給所有 Sales role-shape patterns 使用:

```python
_V85_SALES_SEP = r"[\s,\-/\u2012\u2011\u2013]+"  # whitespace + comma + ASCII hyphen + slash + figure dash + non-breaking hyphen + en-dash
```

> **v8.5 Repair7 (P1-06) 修正**: 早期版本 literal 寫成 `‒` (U+2012) 直接進 source string, 觸發 `_v85_compile_mixed` 內 CJK detection (`ord(c) >= 128`) 誤判, 導致整個 pattern list 走 `zh_patterns` 分支而不套用 word-boundary wrap。修正方式: (a) literal `‒` 改成 `\u2012` escape (source string 全 ASCII), (b) CJK detection 改用實際 CJK ideograph range (`U+4E00-U+9FFF` 等), 不是 `>= 128`。兩個 fix 都要做, 雙重保險。

支援 `Sales - Lead` / `AVP - Sales` / `VP / Sales` / `SVP – Sales` / `Head, Sales` 等常見職稱 typography。
仍是 role-shape only, 沒做全域 punctuation normalization。

### 7.1.2 Cross-Family Contextual Grammar Closure (v8.5 Repair7 P1-01..P1-05)

v8.5 Repair7 把 L3 從 5 個 Sales sub-function + 1 個 Quality pattern 擴充成完整 cross-family contextual grammar, 用共用 `_V85_CTX_ROLE_NOUN` fragment:

```python
_V85_CTX_ROLE_NOUN = (
    r"(manager|director|head|vp|vice\s+president|lead|"
    r"chief|officer|"
    r"specialist|engineer|executive|consultant|analyst|coordinator|"
    r"associate|rep|representative|technician|architect|"
    r"supervisor|administrator|advisor|operator)"
)
```

5 個 family 都用這個 fragment:

- **Sales** (P1-01): forward `sales[SEP]<role>` + `sales[SEP](development|operations|enablement|strategy)[SEP]<role>` + reverse `^<role>[SEP]sales[SEP]<subfunction>`
- **Quality** (P1-02): forward `quality[SEP]<role>` / `quality engineering[SEP]<role>` / `quality assurance[SEP]<role>` + reverse `^<role>[SEP](of[SEP])?quality([SEP](assurance|engineering)([SEP]<role>)?)?` (trailing optional)
- **QA / Test** (P1-03): forward `qa[SEP]<role>` / `(test|testing)[SEP]<role>` / `(test|testing)[SEP]engineering[SEP]<role>` + reverse `^<role>[SEP](of[SEP])?(qa|testing|test engineering)`
- **Support** (P1-04): forward `(customer|technical|it|desktop|tier|application|product)[SEP]support[SEP](operations?)?[SEP]<role>` + reverse `^<role>[SEP](of[SEP])?(customer|technical|it|application|product)?\s*support`
- **中文 cross-family** (P1-05): `品質` / `品質保證` / `品質管理` / `品管` / `品保` / `測試` / `客服` / `技術支援` / `技術服務` 全部加 `_V85_CN_ORG_PARTICLE = r"(部\s*)?"` optional 部門粒度, 不只 Sales

關鍵設計:

- 仍維持 role-shape only, 沒加裸 `sales / quality / support / test` universal hard skip
- Reverse `^<role>[SEP]<domain>` patterns 全部 `^`-anchored, 避免 `Program Manager, Quality Platform` 被誤抓
- Target-role precedence 維持: target guard 在 L3 之前跑, 所以 `Product Manager, Quality Platform` 仍 KEEP
- 中文 `部?` optional, 沒 `部` 也命中 (e.g. `品質經理` 跟 `品質部經理` 都命中)

### 7.2 英文 (role-shape only, 含 Repair4 + Repair5 擴充)

```python
# === Sales (Repair5 separator-aware) ===
r"sales" + _V85_SALES_SEP + "(manager|director|executive|specialist|engineer|rep|representative|associate|consultant|lead|head|vp|vice\s+president)",
r"(head|director|vp|vice\s+president)" + _V85_SALES_SEP + "(of" + _V85_SALES_SEP + ")?sales",
r"(avp|svp|evp)" + _V85_SALES_SEP + "(of" + _V85_SALES_SEP + ")?sales",  # AVP/SVP/EVP Sales (Repair4)
# Sales sub-function family (Repair5 P1-02)
r"sales" + _V85_SALES_SEP + "development" + _V85_SALES_SEP + "(representative|rep|manager|lead|director)",
r"sales" + _V85_SALES_SEP + "operations" + _V85_SALES_SEP + "(manager|lead|director|head|vp)",
r"sales" + _V85_SALES_SEP + "enablement" + _V85_SALES_SEP + "(manager|lead|director|head)",
r"sales" + _V85_SALES_SEP + "strategy" + _V85_SALES_SEP + "(manager|lead|director)",
r"sales" + _V85_SALES_SEP + "(&|and)" + _V85_SALES_SEP + "marketing" + _V85_SALES_SEP + "(manager|director|lead)",
r"chief" + _V85_SALES_SEP + "sales" + _V85_SALES_SEP + "officer",  # Chief Sales Officer (Repair4)
r"sales" + _V85_SALES_SEP + "engineer",
# === Quality ===
r"quality\s+(engineer|manager|director|specialist|assurance|control|analyst|lead|coordinator)",
r"quality\s+assurance\s+(engineer|manager|director|specialist|lead|analyst)",
r"qa\s+(engineer|manager|lead|director|specialist|analyst|automation|architect)",
# === Test ===
r"(test|testing)\s+(engineer|manager|lead|director|specialist|analyst|automation|architect)",
r"software\s+(tester|testing|test|qa|quality)",
# === Support ===
r"(customer|technical|it|desktop|tier|application|product)\s+support\s+(engineer|specialist|analyst|manager|technician|lead|representative)",
r"support\s+(engineer|specialist|analyst|manager|lead|technician|representative)",
```

> **注意**: 上面 snippet 是 manual reproduction, 真實 runtime 是 `sg_product_jobs.py:514+` 的 `CONTEXTUAL_ROLE_PATTERNS` list, 由 `_v85_compile_mixed()` 編譯。
> 改動時請同步改 source, 不要只改 markdown。

### 7.3 中文 (role-shape only, 含 Repair5 P1-03 補 銷售/業務開發/銷售開發)

```python
_V85_CN_SALES_SUFFIX = r"(主管|經理|總監|副理|協理|襄理|處長|副總|代表|顧問|專員|工程師)"
# Sales family (Repair5 P1-03 補 銷售/業務開發/銷售開發 + 業務副總)
r"業務\s*" + _V85_CN_SALES_SUFFIX,
r"銷售\s*" + _V85_CN_SALES_SUFFIX,
r"業務開發\s*" + _V85_CN_SALES_SUFFIX,
r"銷售開發\s*" + _V85_CN_SALES_SUFFIX,
# Other Chinese role-shape (unchanged from v8.5 base)
r"客服\s*(主管|經理|總監|專員|工程師|代表|顧問)",
r"測試\s*(主管|經理|總監|工程師|專員|顧問|自動化)",
r"品管\s*(主管|經理|總監|專員|工程師|代表|顧問)",
r"品保\s*(主管|經理|總監|專員|工程師|代表|顧問)",
r"技術支援\s*(主管|經理|工程師|專員|代表|顧問)",
r"技術服務\s*(主管|經理|工程師|專員|代表|顧問)",
```

> **真實 runtime**: `sg_product_jobs.py:514+` 的 `CONTEXTUAL_ROLE_PATTERNS` list。
> v8.4 broad `業務|業務開發|銷售` substring kill 已於 v8.5 base 移除, Repair5 改用 role-shaped coverage (per 02_PRECEDENCE_AND_RULE_MODEL.md + Repair5 P1-03)。

### 7.4 Bare word 不再 kill

`Program Manager, Sales Platform` (G01) → "sales" 後面是 "Platform", 不 match L3 → KEEP ✅
`Strategy Manager, Data Quality` (G02) → "Quality" 後面是 string end, 不 match → KEEP ✅
`AI Platform Lead, Customer Support Automation` (G03) → "Support" 後面是 "Automation", 不 match L3 → KEEP ✅

---

## §8. L5 Specialist Narrow Rule (新增, P1-03)

**預設 SKIP**。**只有 ALL THREE 條件成立才 KEEP**:
1. title 含 senior marker (e.g. Senior, Principal, AVP, Director)
2. title 含 target/product/AI context
3. 沒 hard non-target role identity

### 8.1 邏輯

```python
# Real runtime (Repair1 word-boundary compiled context):
SPECIALIST_KEEP_CONTEXTS = ["product", "ai", "platform", "data", "growth", "ux", "operations"]
SPECIALIST_KEEP_CONTEXT_REGEX = _v85_compile_contexts_as_regex(SPECIALIST_KEEP_CONTEXTS)

def _v85_is_specialist_senior_with_target(title):
    """specialist narrow rule: KEEP only if (1) senior marker present
    (2) target context matches (word-boundary, Repair1)."""
    t = title.lower()
    if not _v85_has_senior_marker(t):
        return False
    return SPECIALIST_KEEP_CONTEXT_REGEX.search(t) is not None
```

### 8.2 必 KEEP (三條件成立)

- "Senior Product Specialist" → senior + product → KEEP
- "Principal AI Product Specialist" → senior + ai + product → KEEP
- "AVP, Product Specialist" → senior (avp) + product → KEEP

### 8.3 必 SKIP (條件不成立)

- "Product Specialist" → 沒 senior marker
- "Senior Marketing Specialist" → senior 但 no product context
- "Senior Recruitment Specialist" → senior 但 no product context
- "Senior Sales Specialist" → senior + sales → L3 contextual role-shape 命中 `sales + specialist` → SKIP `contextual_role` (注意: 這是 L3 不是 L2; L2 已於 v8.5 base 移除裸 `sales`)
- "Quality Specialist" → 沒 senior marker

### 8.4 F04 deviation

dispatch §03 F04 標 `SKIP*` (帶 *), docstring 說 "if an existing explicit product requirement intentionally includes non-senior Product Specialist, preserve that requirement and flag the deviation with evidence instead of silently changing product policy"。v8.5 採 SKIP (no senior → no keep), 標記於 `KNOWN_DEVIATIONS.md`。

---

## §9. L4 Chinese General Skip (簡化)

`CHINESE_SKIP_REGEX` (sg_product_jobs.py:618+) — source-agnostic (4 source 都跑)。

### 9.1 v8.5 簡化

v8.4: 13 個 pattern 含 "業務|業務開發|銷售", "技術支援|客服", "測試|品質", "約聘|短期|兼職|派遣"。
v8.5: 移除 "業務|業務開發|銷售", "技術支援|客服", "測試|品質", "約聘|短期|兼職|派遣" (移到 L2 hard non-target 中文 或 L3 contextual role-shape 中文)。
v8.5 保留 **8 個** pattern (intern/trainee/graduate/junior/assistant/coordinator/clerk/product marketing) — runtime `CHINESE_SKIP_PATTERNS` list 確認為 8 個 regex entries (`r"實習|工讀"` / `r"培訓|訓練生"` / `r"應屆|畢業"` / `r"助理|初階"` / `r"助理|秘書|行政"` / `r"協調|統籌"` / `r"工讀生|書記"` / `r"行銷|市場專員"`)。

### 9.2 為什麼 "業務" 移到 L2/L3 role-shape 而非保留 L4 廣域 kill?

v8.4 把 `業務|業務開發|銷售` 放在 L4 中文 broad substring kill 層。
這個做法的副作用是會誤殺 "Product Manager, Sales Platform" 等 PM 職稱 (只要含 "Sales" 就跳)。

v8.5 base 改用 role-shaped exclusion:
- L2 中文 hard non-target 不放 `業務` / `業務開發` / `銷售` (這些是 domain 詞, 不是 role identity)
- L3 中文 contextual role-shape 用 `業務\s*<suffix>` / `銷售\s*<suffix>` / `業務開發\s*<suffix>` / `銷售開發\s*<suffix>` (Repair5 P1-03 補; Repair6 P1-03 加 `部?` particle)
- 結果: `業務經理` (A20) 仍命中 L3 (SKIP), `Product Manager, Sales Platform` 不命中 L3 (KEEP)

Trade-off 記錄: 任何把 `業務` / `銷售` 放 L2 broad substring 的 PR 應該被 reject, 因為會誤殺 PM 類職稱。

---

## §10. L6 Source-Specific (onezerofour + cake, 但無 senior rescue)

`ONEZEROFOUR_EXTRA_SKIP_PATTERNS` (sg_product_jobs.py:1019+) — 13 組 regex, **Repair9 v2 起 source 擴展到**:
- `source='onezerofour'` (104, 跟 v8.4 內容相同, 2026-08-29 第一批)
- `source='cake'` (Cake, Repair9 v2 HPM policy 2026-08-31 起)

`_L6_SOURCES = {"onezerofour", "cake"}` set 化, 未來加台灣其他平台只要 `set.add("xxx")` 就會自動套用同 13 組 64 詞 (對齊 104 模式)。

### 10.1 v8.5 → Repair9 演進

- v8.4: 命中後 senior marker 救回 (e.g. "主任倉管" → KEEP)
- v8.5 Repair7: 改 `source == "onezerofour"` gate, **不救回**
- v8.5 Repair8: 改 `_L6_SOURCES` set 化, 加入 `cake` (`source in _L6_SOURCES`)
- v8.5 Repair9 v2: 維持 Repair8 設計, HPM 確認 Cake 是 Taiwan-intake, L6 套用範圍 = all Cake jobs (含非台灣地點的 Chinese-language 職缺)

### 10.2 為什麼 L6 對 Cake 也能 work

- Cake API 沒 senior marker 的內部 metadata, 用 title 文字比對就足夠
- 64 個 L6 詞 (倉管/門市/作業員/業務/司機/廚師/老師/...) 主要針對**繁體中文職缺**, Cake 在台灣+香港+新加坡 (繁中) 範圍命中率最高
- 對 non-繁中 Cake 職缺 (英文 Astera Labs / Logitech 等), L6 詞不會命中, 不會誤殺
- HPM 接受「小 false-positive 風險在偶爾 non-Taiwan Chinese Cake jobs」

### 10.3 Cake source-specific 路由 (Repair9 v2 新)

- Cake **永遠寫到 TW-Raw** (gid=CAKE_TW_RAW_GID=764063873, 跟 104 共用), 不分 SG/CN/HK/US
- `Location` 欄位保留 Cake API `locations[0]` 原始值 (例如 "Taipei City, Taiwan" / "Singapore" / "California, United States")
- 不會用 `location = CAKE_LOCATION_SCOPE = "Global"` 覆蓋 row 級 location
- CLI `--location` 對 cake **不生效** (cake search scope 由 `CAKE_LOCATIONS` env var 或 `CAKE_LOCATIONS` 常數控制, 沒對外暴露 CLI flag)

### 10.4 Cake runtime specs (Repair9 v2)

跟 104 對齊但有 source-specific 微調:

| 項目 | 104 | Cake (Repair9 v2) |
|---|---|---|
| **Keyword 數** | 9 (`ONEZEROFOUR_KEYWORDS`) | 9 (`CAKE_KEYWORDS`, 跟 104 一樣 9 個) |
| **MAX_PAGES 預設** | 1h=1 / 24h=4 / 3d=7 / 7d=15 / 14d=30 / 21d=30 / 30d=50 | 1h=1 / 24h=4 / 3d=7 / 7d=15 / 14d=15 / 21d=20 / 30d=25 (14d/21d/30d 降階, cake server 對高 page 429 敏感) |
| **平行 workers** | `ThreadPoolExecutor(8)` | `ThreadPoolExecutor(3)` (cake 對並發敏感, 8 worker 觸發 429) |
| **Sort by** | server-side `isnew` 過濾 | `sort_by="latest"` 預設 (popularity 不能證明 ranged coverage COMPLETE) |
| **Time filter** | server-side `isnew=0/3/7/14/30` | client-side `content_updated_at` 對 cutoff (Cake 沒 server time filter) |
| **Time range 語意** | `1h=0` (退化), `21d=30` (退化) | `1h=1 hour`, `24h=24 hours`, `3d/7d/14d/21d/30d=exact days` |
| **Retry** | 30/60/90s on 4xx/5xx | 30/60/90s on 429/5xx/connection error (4xx non-429 raise 直接, 視為 caller bug) |
| **Coverage diagnostic** | n/a (server-side) | `coverage_state ∈ {COMPLETE, TRUNCATED, UNKNOWN_NO_CUTOFF, EMPTY}` 每次跑 print |
| **50% soft stop** | n/a (104 用 max_pages + 50% 邏輯) | **無**, 因為 popularity 改 latest 後每頁都 fresh 不用 soft stop |
| **Sleep range** | 全域 `SLEEP_MIN=3.0, MAX=10.0` | cake-specific `CAKE_SLEEP_MIN=3.0, MAX=10.0` (跟全域同, 但隔開避免動到其他 source) |
| **Detail HTML** | AJAX API (5xx retry) | 公開 HTML (CF 403, fallback list description) |

### 10.5 Cake "Coverage" 語意

R9 v2 **取消**了「0 missed jobs」這種聲稱 (P2-07):
- `sort_by=latest` + `max_pages` 預設下, 大多數情況 coverage = `TRUNCATED` (碰到 max_pages 但沒碰到時間邊界)
- 只有當至少一個 job 的 `content_updated_at` 早於 cutoff 時, coverage = `COMPLETE`
- 如果 `cutoff is None` (沒指定 daterange), coverage = `UNKNOWN_NO_CUTOFF`
- 如果沒抓任何 job, coverage = `EMPTY`
- 對 **non-Taiwan Cake 英文職缺** (例如 "Director of Product @ Astera Labs California") 不會被 L6 命中 (L6 詞是繁中, 英文職缺不會 substring 命中)
- 對 **non-Taiwan Cake 繁中職缺** 可能被 L6 命中 (`tw_extra_skip`) — HPM 接受這個小 false-positive 風險
- L6 對 Cake 不區分地點 (no region gate), 跟 104 一樣, 因為 title 文字比對就足夠

---

## §11. 保留的 Backward-Compat 結構

### 11.1 `DEFAULT_SKIP_KEYWORDS` (DEPRECATED)

仍保留 v8.4 內容 (59 個), 但 `match_skip_reason` v8.5 不再用。
保留原因: `enrich_with_jd` 仍傳 `skip_pat` argument (build 給 `_make_skip_pattern(DEFAULT_SKIP_KEYWORDS)`), v8.5 接受這個 argument 但忽略。
dispatch §05 強調: "Preserve the public signature of match_skip_reason(title, skip_pat, *, source=None) unless impossible"。

### 11.2 兩個 narrow rules 內部 senior-marker 機制 **不是共用** (v8.5 真相)

`SENIOR_MARKERS_ANYWHERE` constant 仍存在 (backward compat), 但 specialist 跟 assistant 在 v8.5 runtime 是**分開**的兩條路徑, 沒有共用同一份 compiled regex:

- **Specialist** (`_v85_is_specialist_senior_with_target`): 呼叫 `_v85_has_senior_marker(title)` → 內部呼叫 `_get_senior_markers_pattern()`, 回傳 word-boundary (EN) + substring (CN) 混合 regex。Senior marker 集合是 generic (Senior, Principal, Lead, AVP, SVP, EVP, VP, Director, Head, Chief, 資深, 主任 等)。
- **Assistant** (`_v85_is_assistant_target_senior`): 自己用 `ASSISTANT_SENIOR_TRIGGERS = ["vice president", "vp", "director", "avp"]` 做 substring 檢查 (要求 assistant 緊接 senior trigger)。Senior 集合較窄, 只認跟 assistant role 配對的 leadership titles。

兩者不是同一份 regex, 也不是透過 `SENIOR_MARKERS_ANYWHERE` 共用。`SENIOR_MARKERS_ANYWHERE` 仍存在但 v8.5 `match_skip_reason` 沒直接用, 只在 backward-compat helper 內部出現。

v8.5 不再用全域 senior rescue, 只在 narrow ambiguity rules 內部分別檢查 senior marker。

### 11.3 `SENIOR_FOLLOWERS` (保留)

仍存在, 給 v8.4 backward-compat `_is_senior_assistant_title` 使用 (雖 v8.5 match_skip_reason 不再呼叫)。

### 11.4 `WHITELIST_RULES` (保留)

`{"assistant": "adjacent", "specialist": "anywhere"}` 保留為 v8.4 backward compat 文件。
v8.5 不再使用 (改用 narrow ambiguity rules)。

---

## §12. v8.5 改動 Summary

| 改動 | v8.4 | v8.5 |
|---|---|---|
| 3 層架構 (L1 broad / L2 Chinese / L3 104) | ✅ | ❌ 拆成 5 semantic groups |
| 7 層 precedence | ❌ | ✅ |
| 全域 senior rescue | ✅ 任何 skip hit | ❌ 移除 |
| Target-role guard (L0) | ❌ | ✅ 新增 |
| Entry-level gate (L1) | ❌ (跟 L1 混) | ✅ 獨立, 在 target guard 前 |
| Assistant narrow rule | adjacent + anywhere (寬) | AVP/VP/director + target context (嚴) |
| Specialist narrow rule | senior anywhere (寬) | senior + target context (嚴) |
| L2 hard non-target | 沒有 (混在 L1) | ✅ 獨立, no senior rescue |
| L3 contextual role-shape | ❌ (bare word) | ✅ role-shape only |
| Bare "sales" "quality" "test" "support" | ✅ 跳 (誤殺) | ❌ 不跳 |
| "contract" "temp" "temporary" | ✅ unconditional 跳 | ❌ 不跳 (PM 角色留) |
| 104 source-specific + senior rescue | ✅ | ❌ no senior rescue |

---

## §13. 必 KEEP / 必 SKIP 範例速查

### 13.1 必 SKIP (即使 senior 也不救)

- 所有 PM 以外的 senior 角色: "Senior Product Designer", "Director of Sales", "VP Human Resources", "Quality Director", "Head of Procurement", "Senior Account Manager", "Senior Accountant", "Senior QA Manager", "Senior Test Engineer"
- 中文 senior role: "會計經理", "人資總監", "採購副總", "業務經理", "品管經理", "門市店長", "主任倉管", "業務經理"
- 整個 sales/BD family: "Director of Sales", "VP Sales", "Sales Manager", "Head of Sales", "Senior Business Development Manager"
- 整個 HR/Recruiting family: "Senior Recruiter", "Director of Recruiting", "Head of Recruitment"
- 整個 accounting/audit family: "Senior Accountant", "Finance Audit Director", "Senior Auditor"
- 整個 procurement family: "Senior Buyer", "Director of Procurement", "Senior Purchaser"
- 整個 quality/test 角色: "Quality Director", "Senior QA Manager", "Senior Test Engineer", "Quality Inspector"

### 13.2 必 KEEP (即使含 skip 詞)

- 標準 PM 變體: "Senior Product Manager", "AI Product Manager", "Lead Product Manager", "Group Product Manager", "Product Director", "VP of Product", "Chief Product Officer", "Product Owner", "Head of Product", "Director of Product"
- 修飾前綴的 PM: "Technical Product Manager", "Principal Product Manager, Trust & Quality", "AI Product Manager - 12 Month Contract"
- PM 內含 contextual words (v8.5 不再誤殺): "Product Manager, Sales Platform", "Product Manager, Data Quality", "Product Manager, Customer Support Platform", "Product Manager, Test Infrastructure", "Product Manager, Quality & Trust"
- 中文 PM: "產品經理－銷售平台", "產品經理－品質與信任", "產品總監－銷售科技", "產品經理－客服自動化"
- Assistant narrow 命中: "Assistant Vice President, Product", "Assistant VP, AI Product", "Assistant Director, Product Management"
- Specialist narrow 命中: "Senior Product Specialist", "Principal AI Product Specialist", "AVP, Product Specialist"
- Bare contextual survival: "Program Manager, Sales Platform", "Strategy Manager, Data Quality", "AI Platform Lead, Customer Support Automation", "Product Operations Lead, Test Infrastructure"
- Employment type 不阻擋: "Product Manager (Contract)", "AI Product Manager - Temporary", "Technical Product Manager - Temp Assignment"

### 13.3 Entry-level 一律跳 (priority over target guard)

- "Junior Product Manager", "Jr Product Manager", "Product Manager Intern", "Product Management Intern", "Graduate Product Manager", "Trainee Product Manager", "Assistant Product Manager"
- 中文: "產品經理實習生", "初階產品經理", "產品助理"

---

## §14. 加新詞的 SOP (v8.5)

### 14.1 加 L0 target role (KEEP 詞)

直接編輯 `TARGET_ROLE_PATTERNS` list, append 新 regex (含 word-boundary 跟 negative lookahead 處理 lookalike)。

### 14.2 加 L1 entry-level (SKIP 詞)

編輯 `ENTRY_LEVEL_PATTERNS` list, append。

### 14.3 加 L2 hard non-target (SKIP, no senior rescue)

編輯 `HARD_NON_TARGET_ROLE_PATTERNS` list, append。
注意: 完整 role family 用 role-shape (例如 "account manager" 而不是 "account")。

### 14.4 加 L3 contextual role-shape (SKIP only in role shape)

編輯 `CONTEXTUAL_ROLE_PATTERNS` list, append。
格式: `r"domain_word\s+(role_suffix|...)"`。

### 14.5 加 L6 104 source-specific (only 104)

編輯 `ONEZEROFOUR_EXTRA_SKIP_PATTERNS` list, append。

### 14.6 環境變數覆寫 (測試用途)

- `ONEZEROFOUR_KEYWORDS="..."` 改搜尋關鍵字
- `ONEZEROFOUR_EXTRA_SKIP="regex1||regex2||..."` 覆寫 L6 list

---

## §15. 測試覆蓋

| 測試檔 | 涵蓋 | 測試數 |
|---|---|---|
| `test_v85_hostile.py` (NEW v8.5) | A-I + J 全矩陣 | 16 |
| `test_skip_filter_expansion.py` (UPDATED) | 既有 L1 詞 + word-boundary regression | 7 |
| `test_onezerofour_extra_skip.py` (UPDATED) | L6 104 extra + source-specific | 9 |
| `test_onezerofour_url_build.py` | (無關 skip) | 9 |
| `test_onezerofour_list_parse.py` | (無關 skip) | 8 |
| `test_onezerofour_detail_fetch.py` | (無關 skip) | 9 |
| `test_onezerofour_sheet_safety.py` | (無關 skip) | 10 |
| `test_pre_detail_sheet_dedup.py` | (無關 skip) | 10 |
| `test_config_fail_closed.py` | (無關 skip) | 12 |
| `test_mcp_contract.py` | (無關 skip) | 19 |
| `test_setup_contract.py` | (無關 skip) | 7 |
| `test_sheet_safety.py` | (無關 skip) | 9 |
| `test_cake_url_build.py` (NEW Repair8) | Cake URL build (companies/page/jobs/path) | 4 |
| `test_cake_list_parse.py` (NEW Repair8) | Cake list parse (path = job_id, locations[0] = row location) | 3 |
| `test_cake_detail_fetch.py` (NEW Repair8) | Cake JD (HTML 403 fallback list description) | 2 |
| `test_cake_r9_integration.py` (NEW Repair9) | R9-A Time windows + R9-B max-pages + R9-C Coverage + R9-D TW-Raw routing + R9-E L6 on Cake + R9-F retry + R9-G concurrency + R9-H base contract (45 cases) | 45 |

**累計**: 163 + 9 cake + 45 R9 = 217/217 全綠 (2026-08-31 v8.5 Repair9 v2, 含 7 個 R7 test functions + 5 個 doc lint + 96 個 A-I 既有 + 14 R1 + 19 R2 + 32 R3 + 36 R4 + 52 R5 + 49 R6 + 107 R7 + 9 cake + 45 R9)。
跑全部: `cd ~/.minimax/plugins/jobs-scraper && .venv/bin/python -m pytest -q`

---

## §16. 修訂歷史

| 日期 | 版本 | 改動 |
|---|---|---|
| 2026-08-19 | v0 | 24 個英文 skip 詞 + senior whitelist (assistant/specialist) |
| 2026-08-24 | v1 | Daniel 加 18 個新詞, 28 個, `recruiter` etc |
| 2026-08-29 早上 | A 階段 | 13 組 CHINESE_SKIP + 12 個中文 senior 詞 (3 層架構) |
| 2026-08-29 中午 | A 階段 | 13 組 ONEZEROFOUR_EXTRA + 修 "幹事" 漏 |
| 2026-08-29 下午 | A 階段 | DEFAULT_SKIP_KEYWORDS 28→59 (Daniel 18 個 + 13 變體) |
| 2026-08-29 下午 | A 階段 | senior whitelist 對全 skip 詞生效 + word-boundary 修 cto bug |
| 2026-08-29 晚 | v8.4 | **本文件 (v8.4) 發布**, 完整邏輯整合 |
| 2026-08-29 深夜 | **v8.5** | **Bounded Repair**: 移除全域 senior rescue, 加 L0 target guard + L2 hard non-target + L3 contextual role-shape, 收窄 assistant/specialist ambiguity rules, 移除 contract/temp/temporary unconditional skip, 保持 104 source-specific (但 no senior rescue). 5→7 層 precedence. 125/125 tests 全綠. |
| 2026-08-29 | **v8.5 Repair1** | `ai` / `ux` substring 改用 word-boundary regex; assistant / specialist narrow rule 用 `_v85_compile_contexts_as_regex`. 14 R1 tests + 110 truth table rows. |
| 2026-08-29 | **v8.5 Repair2** | Assistant hard_non_target veto (P1-02 收窄); VP / Vice President suffix guard (P1-04). 19 R2 tests. |
| 2026-08-30 | **v8.5 Repair3** | Product-* family separator 改用共用 `_V85_PRODUCT_FAMILY_SEP = r"[\s\u2011\u2013\-]+"` 認 hyphen/en-dash/non-breaking hyphen. 32 R3 tests. |
| 2026-08-30 | **v8.5 Repair4** | Sales role-shape 加 AVP/SVP/EVP prefix + Sales Lead/Head/VP + Chief Sales Officer + Sales Operations/Enablement manager/lead. 36 R4 tests. |
| 2026-08-30 | **v8.5 Repair5** | 共用 `_V85_SALES_SEP = r"[\s,\-/\u2012\u2011\u2013]+"` (6 種 separator); 5 個 Sales sub-function family (Dev/Ops/Enablement/Strategy/&Marketing); 中文 銷售/業務開發/銷售開發 role-shaped coverage. 52 R5 tests. |
| 2026-08-30 | **v8.5 Repair6** | `^`-anchored reverse-order Sales sub-function (Manager/Lead, Sales Development); forward-order sub-function 補 head/vp suffix; Taiwan 中文 部門粒度 `部?` (跨 Sales). Docstring consistency scan + 5 doc lint tests. 49 R6 tests. |
| 2026-08-30 | **v8.5 Repair7** | **Cross-family contextual grammar closure** (本輪): (P1-01) Sales sub-function role-noun closure 共用 `_V85_CTX_ROLE_NOUN`; (P1-02) Quality 雙向 leadership + role grammar (Director/Head/VP of Quality + Quality Engineering); (P1-03) QA / Test 雙向 (Director/Head/VP of QA/Testing + Test Engineering); (P1-04) Support 雙向 (Customer/Technical Support + Support Operations); (P1-05) 中文 cross-family 9 個 family 全部加 `_V85_CN_ORG_PARTICLE`; (P1-06) `^` anchored reverse + `_V85_SALES_SEP` literal `‒` 改 `\u2012` escape + `_v85_compile_mixed` CJK detection 改用實際 CJK ideograph range (修 R7-80 `AI Platform Lead, Quality Engineering` 誤抓). 107 R7 tests (A=18, B=12, C=14, D=16, E=14, F=18, G=15). 163/163 tests 全綠. |
| 2026-08-30 | **v8.5 Repair8** | **Cake source 整合** (cake handoff 8/30 23:01): 8 改動: (1) `_L6_SOURCES = {"onezerofour", "cake"}` set 化, Cake 套用 L6; (2) 104 keywords 9 個; (3) CAKE_KEYWORDS 9 個; (4) CAKE_MAX_PAGES 對齊 104; (5) CAKE time filter (content_updated_at client-side); (6) CAKE 平行化 (`ThreadPoolExecutor(max_workers=3)`); (7) `_cake_list_with_retry` 30/60/90s; (8) CAKE-specific sleep 3-10s. R7 frozen 405-row truth table 不破壞, 173/173 tests 全綠. |
| 2026-08-31 | **v8.5 Repair9 v2** | **Cake routing + time-window auditability** (HPM policy 8/31 改): (P1-01) CLI `--max-pages` 接到 `crawl_cake_list`; (P1-02) `1h = 1 hour` (從 1 day 改), 用 `CAKE_TIME_FILTER` 支援 hours/days; (P1-03) `sort_by="latest"` 預設, `coverage_state` ∈ {COMPLETE, TRUNCATED, UNKNOWN_NO_CUTOFF, EMPTY} diagnostic; (P1-04) Cake 路由 `CAKE_TW_RAW_GID=764063873` (跟 104 共用), `location` 保留 Cake `locations[0]`, 不覆蓋成 "Global", CLI `--location` 對 cake 不生效 (明示); (P1-05) SKIP.md §10 加 L6 Cake 說明; (P1-06) 新建 `tests/test_cake_r9_integration.py` 45 個 R9 test cases (R9-A 到 R9-H); (P1-07) return ZIP 內含 5 個核心檔案**完整源碼**; (P2-01..09) 9 個文件 truthfulness 修法. |

---

## §17. 參考檔案

- `sg_product_jobs.py`: 主要實作
  - `DEFAULT_SKIP_KEYWORDS` (line 312+, DEPRECATED, v8.4 backward compat)
  - `TARGET_ROLE_PATTERNS` / `TARGET_ROLE_REGEX` (line 435+, NEW v8.5)
  - `ENTRY_LEVEL_PATTERNS` / `ENTRY_LEVEL_REGEX` (line 471+, NEW v8.5)
  - `HARD_NON_TARGET_ROLE_PATTERNS` / `_REGEX` (line 486+, NEW v8.5)
  - `CONTEXTUAL_ROLE_PATTERNS` / `_REGEX` (line 528+, NEW v8.5)
  - `_v85_compile_mixed` (line ~430, helper)
  - `_v85_is_assistant_target_senior` (line ~565, narrow rule)
  - `_v85_is_specialist_senior_with_target` (line ~590, narrow rule)
  - `SPECIALIST_KEEP_CONTEXTS` / `ASSISTANT_KEEP_CONTEXTS` / `ASSISTANT_SENIOR_TRIGGERS`
  - `CHINESE_SKIP_PATTERNS` + `CHINESE_SKIP_REGEX` (line 618+, simplified v8.5)
  - `ONEZEROFOUR_EXTRA_SKIP_PATTERNS` + `_REGEX` (line 646+, source-specific preserved)
  - `match_skip_reason` (line 696+, v8.5 7 層 precedence)
  - `SENIOR_FOLLOWERS` / `SENIOR_MARKERS_ANYWHERE` (line 359+, DEPRECATED 但保留)
  - `WHITELIST_RULES` (line 373+, DEPRECATED)
- `tests/test_v85_hostile.py` (NEW v8.5): A-I + J 矩陣 16 tests
- `tests/test_skip_filter_expansion.py` (UPDATED): 既有 L1 詞 + word-boundary
- `tests/test_onezerofour_extra_skip.py` (UPDATED): 104 source-specific
- `RULES.md` §1.1 / §1.2 / §15.9 / §15.19 / §15.19.1 / §15.20: 章節對應
- `BOOT_PROMPT.md` §4.5: 速查版
- `SKIP_FILTER_V8_5_BOUNDED_REPAIR_DISPATCH/`: 完整 dispatch package
- `HANDOFF_V8_5_REPAIR.md`: 整合記錄

---

## §18. Known divergences between this document and the runtime (2026-10-26)

The v8.5 Repair7 implementation was qualified on 2026-08-30, but this document was
written across the repair rounds and a few sections still describe an earlier
shape. The **runtime is authoritative**; the notes below record every place the
prose and the code disagree, so nobody has to rediscover them.

Findings were produced by rebuilding the test suite from the implementation and
diffing the observed behaviour against this document
(`tests/test_v85_hostile.py`, 325 cases; `tests/test_skip_filter_expansion.py`, 89 cases).

### 18.1 Reason-code attribution

The **KEEP / SKIP outcome always matches this document**. Only the reason token
that gets attributed differs in a few places, because the executable precedence
is `entry-level → assistant → target guard → hard non-target → contextual →
specialist → Chinese → 104/Cake`, while some sections below group cases by a
different layer:

| Title | This document groups it under | Runtime returns |
|---|---|---|
| `Assistant Director, Human Resources` | L5 specialist (§8) | `hard_non_target` (L2 fires first) |
| `Senior Recruitment Specialist` | L5 specialist (§8) | `hard_non_target` (L2 fires before L5) |
| `Quality Specialist` | L5 specialist (§8) | `contextual_role` (L3 fires before L5) |

### 18.2 `chinese_skip` is unreachable

All 16 L4 triggers are shadowed by an earlier layer — `實習/工讀/培訓/訓練生/應屆/畢業/助理/初階`
match L1 (`entry_level`), and `秘書/行政/協調/統籌/工讀生/書記/行銷/市場專員` match L2
(`hard_non_target`). No title ever returns the `chinese_skip` token. The SKIP
outcome is unaffected; only the attribution label is.

### 18.3 §7.2 role-suffix snippet is stale

§7.2's "manual reproduction" lists `automation` / `control` / `assurance` in the
role-suffix set. The runtime's `_V85_CTX_ROLE_NOUN` deliberately excludes them
(§7.1.2 is correct). So `QA Automation Lead` and `Test Automation Architect`
**KEEP**, contrary to what §7.2 implies. §7.1.2 matches the runtime.

### 18.4 Other prose details

- §4.3 is imprecise: `Assistant Product Manager` is skipped by the *assistant*
  rule (token `assistant`), not by the Chinese `助理` L1 pattern.
- §5.1's snippet omits the `asst. {trig}` form, which the runtime does have —
  `Asst. VP, Product` KEEPs. §11.2's snippet likewise omits the Chinese contexts
  present in `SPECIALIST_KEEP_CONTEXTS`.
- §13.1 mixes source-scoped titles into a source-agnostic table: `門市店長` and
  `主任倉管` only skip for `source=onezerofour|cake` (§10); they KEEP for
  linkedin / jobstreet / jora / `None`.
- §10's own comment cites `行政幹事` as an L6 example, but L2's `行政` fires
  first, so the token is `hard_non_target` for every source.

### 18.5 The v1.2.1 skip-profile API does not exist

`ACTIVE_DEFAULT_SKIP_KEYWORDS` and `resolve_skip_words` — the helpers the older
upstream contract test expected — are not implemented. The shipped surface is
`DEFAULT_SKIP_KEYWORDS`, `_make_skip_pattern()`, and `match_skip_reason()`.

### 18.6 `--no-skip` and `--skip-keywords` (fixed in v1.4.0)

Until v1.4.0 these two CLI flags had **no effect on what got skipped**: v8.5
made `match_skip_reason` ignore its `skip_pat` argument, and `enrich_with_jd`
routed every title through it. The help text claimed otherwise.

v1.4.0 semantics:

| CLI | Effective filter |
|---|---|
| *(default)* | v8.5 semantic groups only |
| `--skip-keywords A B` | v8.5 semantic groups **plus** an extra keyword match |
| `--no-skip` | no title filter at all |

The v8.5 filter logic itself is unchanged; only the CLI wiring was corrected.

### 18.7 Cake coverage aggregation

`_aggregate_cake_coverage` returns `EMPTY` — not `COMPLETE` — when a keyword
proved the time-range boundary but produced zero surviving jobs, because the
boundary proof is discarded rather than counted as coverage. The outcome
(`EMPTY`) is defensible; the loss of the proof is not obvious from the code.
