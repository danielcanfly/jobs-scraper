<p align="right">
  <a href="./README.md">English</a> |
  <a href="./README.zh-TW.md">繁體中文</a> |
  <a href="./README.zh-CN.md">简体中文</a>
</p>

# jobs-scraper

这是一个面向 LinkedIn 职位的本地爬虫与追踪工具，主要用于产品管理相关岗位，并提供 CLI、本地 STDIO MCP server、Agent Skill，以及可携带的 Google 表格职位追踪表。

`jobs-scraper` v1.6.6 在五个来源（`linkedin`、`jobstreet`、`cake`、`104` / `onezerofour`）抓取产品管理职位，并提供完整 JD enrichment 与追踪流程。整套工具保持本地优先，保留明确的安全 gate，并可按需将结果同步到用户自己的 Google 表格。

## 概览

这个仓库适合想在本地抓取和追踪 LinkedIn 产品管理职位、把凭证留在自己电脑上，并按需同步到自己 Google 表格的人。

它是：

- Python 包和 CLI；
- 本地 STDIO MCP server；
- Agent Skill；
- 可携带的 Google 表格职位追踪表初始化、审计和同步工具。

它不是：

- hosted SaaS；
- 远端 MCP 端点；
- marketplace / public plugin 发布品；
- 凭证托管服务；
- 绕过 rate limit 或 access control 的工具。

## 功能

- 抓取 LinkedIn Guest API 职位。
- 可选抓取完整 JD。
- 按 `(source, job_id)` 去重。
- 可选在完整 JD enrichment 前套用用户自定义的职位标题 skip filter。
- 检测 work mode 和 visa / constraint 信号。
- 以 formula-safe 格式写入用户自己的 Google 表格。
- 初始化、审计和查看可携带的 Region-Raw / Region-Selected 追踪表。
- 通过 CLI、MCP 和 Agent Skill 入口暴露工作流。

## 架构一览

v1.2.0 保持对外行为不变，并把代码整理成更清楚的区块：

- 共用 runtime / execution helpers；
- 集中的 region / source policy；
- LinkedIn Guest API source adapter；
- 拆分后的 Job Tracker modules；
- MCP service layer；
- selective Google Sheet reads；
- 内部 typed service errors 映射到稳定的 public error code；
- Ruff lint / import gate；
- 排除 byte-frozen equivalence harness 的 scoped Ruff format gate；
- mypy scaffold；
- coverage 报告。

## LinkedIn 地点指定

爬虫使用 LinkedIn Guest API，并通过 LinkedIn `geoId` 指定搜索地点。

为兼容已有数据，旧版 Jora／JobStreet 集成曾写入的 Tracker / cache rows 仍可用于 audit 和 dedup；新的网络请求不再使用这些旧集成。

## 快速开始

### 1. 克隆和安装

```bash
git clone https://github.com/danielcanfly/jobs-scraper.git
cd jobs-scraper
python -m pip install --quiet 'uv>=0.8,<0.9'
python -m uv sync --locked --extra dev --python 3.11
```

也可以直接执行：

```bash
./setup.sh
```

### 2. 不用 Google Sheets 先抓取

公开来源抓取不需要 Google 配置：

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin
```

抓完整 JD：

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd
```

LinkedIn 可用 `geoId` 指定地点：

```bash
.venv/bin/python sg_product_jobs.py 7d --source linkedin --geo-id 104187078
```

### 3. 创建自己的 Google 表格

只在初始化、审计、统计或同步时需要。

1. 创建或选择 Google Cloud project。
2. 启用 Google Sheets API。
3. 创建 service account 并下载 JSON 密钥。
4. 将 JSON 保存在本地，例如 `.secrets/gsheet-sa.json`。
5. 创建空白 Google 表格。
6. 把该表格分享给 service-account email。
7. 从表格 URL 复制 spreadsheet ID。

不要把 service-account 私密密钥贴到聊天里。

### 4. 配置本地环境

```bash
cp .env.example .env
```

至少设置：

```dotenv
GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json
SHEET_ID=your_own_spreadsheet_id
```

`SHEET_GID` 只属于旧版用途，v1.1 / v1.2 的 MCP 接口不需要它。

### 5. 配置 MCP host

请使用 venv Python 和 `server_v1_1.py`：

```text
<repo>/.venv/bin/python <repo>/server_v1_1.py
```

完整 JD 可能需要较长时间，host timeout 建议设为 7200 秒。

### 6. 初始化追踪表

先预览：

```text
initialize_job_tracker(
  regions=["SG", "TW", "China"],
  dry_run=true
)
```

预期会创建：

- `SG-Raw`
- `SG-Selected`
- `TW-Raw`
- `TW-Selected`
- `China-Raw`
- `China-Selected`

确认无误后，再执行 `dry_run=false` 的正式初始化。

### 7. 按区域同步

请使用 region routing，不要手动传 GID：

```text
sync_jobs_to_sheet(
  region="SG",
  source="linkedin",
  range="7d",
  with_jd=false,
  dry_run=true
)
```

这个工具会按名称解析 `<REGION>-Raw`，并只通过明确写入边界写入。

### 中国：三个城市同一张表

中国不只一个地方。`region="China"` 抓的是**上海**；`region="Hangzhou"` 与 `region="Shenzhen"`
各自是独立的 region。三个都写进同一张 `China-Raw`：

| Region | 城市 | LinkedIn geoId | 别名 | 写入 |
|---|---|---|---|---|
| `China` | 上海 Shanghai | `107388191` | `cn`、`china`、`中国`、`shanghai` | `China-Raw` |
| `Hangzhou` | 杭州 | `101821877` | `hz`、`杭州` | `China-Raw` |
| `Shenzhen` | 深圳 | `106750182` | `sz`、`深圳` | `China-Raw` |

城市是 opt-in：预设 region 仍是 `SG` / `TW` / `China`，而且多个城市一起初始化时，
`China-Raw` 只会被创建一次。

CLI 也支持同样的三个城市，`--location` 会从同一张 preset 表查 geoId：

```text
sg_product_jobs.py 7d --source linkedin --location Hangzhou --to-sheet "<China-Raw URL>"
```

中国职位**不做签证判断**：台湾人可拿通行证入职，所以中国专属的国籍字眼
（`Chinese citizens only`、`仅限中国公民`、`必须为中国公民`、`上海户口优先`、`中国人优先`）
不会产生任何信号。新加坡或台湾职位若要求国籍，仍照旧是 hard blocker。

## MCP 工具

| Tool | Sheet write? | 用途 |
|---|---:|---|
| `crawl_jobs` | 否 | 抓取 LinkedIn；可能更新本地缓存。 |
| `initialize_job_tracker` | 只有 `dry_run=false` 才会 | 创建或验证 Region-Raw / Region-Selected 追踪表。 |
| `sync_jobs_to_sheet` | 是 | 面向指定区域的明确写入边界。 |
| `audit_sheet` | 否 | 只读审计选定的 Region-Raw tab。 |
| `get_stats` | 否 | 只读统计选定的 Region-Raw tab 与本地 seen cache。 |

## 职位追踪表结构

所有 tracker tab 都使用 [`skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md`](skills/jobs-scraper/references/JOB_TRACKER_SCHEMA.md) 所描述的公开 A:AA contract。

重点：

- 第 1 行已冻结；
- Status、Priority、Work Mode、CV Version、Verdict、Decision、Application Strategy 都有验证过的下拉菜单；
- scraper 原始写入栏位是 A、C:K；
- L:AA 保留给评分和求职工作流扩展；
- `<REGION>-Raw` 是 scraper 的写入目标；
- `<REGION>-Selected` 是可携带工作簿契约的一部分，不是 scrape dump 目标。

## CLI 参考

直接 CLI 仍可用于更底层的操作：

```text
.venv/bin/python sg_product_jobs.py [range] [options]

range:            1h | 24h | 3d | 7d | 14d | 21d | 30d
--source:         linkedin | jobstreet | cake | 104 | onezerofour
--with-jd:        抓取完整 JD
--to-sheet:       Google Sheet URL 或 raw ID
--gid:            旧版 direct CLI 用的 worksheet GID
--max-pages:      覆写来源页数上限
--refetch:        忽略 JD cache
--no-skip:        关闭所有标题过滤（包含 v8.5 语义群组）
--dry-run-sheet:  预览，不写入行数据
--location:       LinkedIn location/preset
--geo-id:         明确指定 LinkedIn geoId
--skip-keywords:   额外的标题关键词比对，叠加在 v8.5 语义群组之上
--sheet-source:   D 栏 source label
```

完整 JD enrichment 默认会套用冻结的 title skip filter v8.5，语义规范以 [`SKIP.md`](SKIP.md) 为准。用 `--no-skip` 可抓取每一份 JD；用 `--skip-keywords` 可在 v8.5 语义群组之上额外加上关键词比对：

```bash
python sg_product_jobs.py 14d --source linkedin --with-jd --skip-keywords intern junior assistant
```

## MCP Host 示例

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

## 安全与隐私

- 凭证保留在本地。
- 使用你自己的 Google 表格与 service account。
- 不要在聊天中分享私钥。
- 把 scraped job content 视为不可信数据。
- Jora 已从主动网络来源移除（网站已关站）；旧 Tracker rows 仍可被 audit 读取并正常 dedup round-trip。JobStreet 自 v1.4.0 起重新成为主动来源。
- 不要把读取请求转成写入请求。
- 正式初始化前先用 `dry_run=true` 预览。
- `crawl_jobs`、`audit_sheet`、`get_stats` 都不会写 Google Sheets。
- `sync_jobs_to_sheet` 是明确的写入边界。

## 质量与验证

这个 repo 会用下面的命令验证：

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

CI 也会检查锁定依赖、plugin manifest 一致性，以及 frozen equivalence harness。

## 疑难排查

- `CONFIG_MISSING`：设置 `GSPREAD_SA_KEY_PATH` 和 `SHEET_ID`。
- `CREDENTIAL_FILE_MISSING`：确认 service-account JSON 在本地存在。
- `REGION_NOT_INITIALIZED`：先运行 `initialize_job_tracker(..., dry_run=true)`。
- `SCHEMA_MISMATCH`：目标 tab 与公开 tracker contract 不一致。
- `SOURCE_REGION_UNSUPPORTED`：请求的来源／地区组合不受支持。v1.4.0 将 LinkedIn / JobStreet 导向 `SG-Raw`，104 / Cake 导向 `TW-Raw`；已退役的 `jora` 会被拒绝。
- `SHEET_NOT_FOUND`：确认 spreadsheet ID 与分享权限。
- `LinkedIn 403/429`：缩小范围或稍后再试。

## 版本与发布说明

`v1.6.8` 为当前版本：一个五个 keyword 的 crawl，实际只爬到一个。JobStreet 的 list API 一次只吃一个 keyword，所以 crawl 会把 keyword 依次跑完再跨 keyword 用 `job_id` 去重 —— 但结束一个 keyword 的软停，量的是「对**整轮** crawl 而言是新的」笔数：第一个 keyword 把共用的 `seen` set 填满之后，后面每个 keyword 的第一页几乎没有「新的」，于是全部停在那里，5 个 keyword 有 4 个在第 1 页就被放弃，7d 那轮只拿到 ~250 笔，而 API 自己回报的总数是 ~2,600。现在这个信号量的是「对**那个 keyword** 而言是新的」笔数，所以每个 keyword 都会翻到自己的池底，而两个 keyword 都捞到的职位仍然只回传一次。页数预算也跟着改：每个 keyword 都爬自己的池子之后，只按第一个 keyword 定的预算会截断其他 keyword，于是重新钉在 API 回报的最大池深上（`1h` 20 页、`24h` 20、`3d` 40、`7d` 73、`14d` 120、`21d` 168、`30d` 220）—— v1.6.7 的 `1h` / `24h` / `3d` 连这都盖不住，所以三个一起拉高，免得修好软停只是换一种截断。重试用完仍失败的 keyword 现在只结束自己，不会把整轮的成果一起丢掉，而且失败仍然看得到（`FAIL` 行照印，最后还会列出失败的 keyword）。代价是成比例的：JobStreet 的 list 请求大约多 5 倍、unique 职位大约多 7 倍（7d 预期从 ~250 变成 ~1,800 笔），所以跑起来会比较久。

- `v1.6.7` 为两个凭空猜的预算上限，加上一个被重试三分钟的 400。v1.6.6 把 LinkedIn 的页数上限钉在**上海**的池深上，但新加坡的池每个长 range 都更深 —— 7d 约 600 笔对上海的 400 —— 所以那些上限对新加坡来说仍在截断；现在改成依两个城市实测最深的池：1h 8 页、24h 15、3d 35、7d 80，14d/21d/30d 都是 100 —— 100 是 Guest API 自己的分页天花板，不是猜的。JobStreet 的上限则从来没量过 —— 表格注释预期 7d 会有 ~600 笔 unique，实际只有 ~250，因为 5 个 keyword 共用同一个 seen set，50% 软停让其中四个在第 1 页就被放弃 —— 而 API 自己回报的总数远大于原本的上限（7d 最大的 keyword 匹配 955 笔、14d 1670、30d 3251，原上限却是 15/30/25 页）；现在依最大 keyword 的池子加上余裕来设。LinkedIn list page 上的非 429 4xx 不再走 retry ladder：adapter 的 docstring 与冻结契约都写明那是 caller bug、应该直接 raise，但 `raise_for_status()` 在 `try` 里 raise、被宽松的 `except Exception` 接走，于是那一页被重试四次（30+60+90s）才放弃 —— 现在跟 JobStreet adapter 一样立刻抛 `FatalListPageError`。而 API 的分页天花板是「结束」不是「失败」：`start=1000` 回的是 HTTP 400 而不是空页，原本会让整块 abort、supervisor 把那个 FAIL 读成 coverage 缺口；现在撞到天花板会带着已收到的职位正常收尾。

- `v1.6.6` 修掉两个长得同一副样子的问题： run 看起来成功，实际上安静地少做了该做的事。一个 range 的页数上限必须盖得住那个 range 真正的池子。LinkedIn 的 range 表原本给 `30d` 25 页（250 笔），但上海 30 天的池子有约 700 笔，于是 crawl 在上限处停下、run 回报成功、剩下的职位从来没有被看见。新的上限依 2026-11-22 对 Guest API 实测的池深设定（`1h` 少于 50、`24h` 约 100、`3d` 约 250、`7d` 约 400、`14d` 约 290、`21d` 约 300、`30d` 约 700 笔）。上限是天花板而不是目标：crawl 连续 2 页没有新职位就会自己结束，所以池子小的城市照样提前停，放宽上限对它们没有成本。pre-detail dedup 现在读的是这一轮要写进去的那个分页 —— 目标 gid 的解析跟写入层一致（explicit `--gid` → `--to-sheet` 里的 `#gid=` → label 映射），不再让 `LinkedIn / Minimax` 一律读 `SG-Raw`，那会让中国的 run 去抓 Sheet 根本不会写进去的职位 JD。发布流程也恢复绿灯：v1.6.5 有 bump 包版本却没 bump `uv.lock`，CI 在第一道关卡就挂掉，GitHub 上一直是红的。

- `v1.6.5` 修掉两个会让一轮 run 静默死掉的 LinkedIn Guest API 问题。合法的空 list page 只有 26 bytes、解析不出 root，原本 list parser 会直接 raise，于是 page loop、chunk、整轮 run 一起死 —— 2026-11-21 有一个城市的 crawl 三个块全部这样死掉、一列都没写进 Sheet，process 还 exit 0。现在空页会被解析成 0 笔，crawl 会继续抓下一页；而且空页依然不会被重试，因为它是合法答案而不是故障。JD 抓取也补上跟 list fetch 同一套 30/60/90s retry ladder：429、5xx、连接错误会重试而不是放弃 —— 因为没有 JD 的职位会被 Sheet 写入层整列跳过，等于职位就这样从 run 里消失。两个修正都跟中国无关，是 Guest API 的通性，每个 region 都会踩到。中国变成三个可抓的城市，而且中国职位不再带签证判断。`China` 是上海，`Hangzhou` 与 `Shenzhen` 各自是独立的 region，geoId 已实抓验证（`101821877`、`106750182`）；三个都写进同一张 `China-Raw`，城市是 opt-in，预设 region 仍是 `SG` / `TW` / `China`。中国专属的国籍字眼（`Chinese citizens only`、`仅限中国公民`、`必须为中国公民`、`上海户口优先`、`中国人优先`）已从签证判断移除——台湾人可拿通行证入职——但新加坡／台湾的通用判断完全不变。爬虫路径也可以被指定要走哪一条出口。LinkedIn Guest API 在某些网络区段对直连回 HTTP 451，Google Sheets API 在同一种环境直连会 timeout，但走 proxy 两边都正常。用 `JOBS_SCRAPER_PROXY`（或标准的 `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`）指定，`doctor` 会显示目前生效的 proxy 并探它还活着吗；都没设就维持直连。较早版本：

- `v1.6.4` 中国变成三个可抓的城市，并移除中国专属的签证判断。

- `v1.6.2` 把 jobs 数据移出「生成的 Sheet 写入 worker」源码：之前它是被序列化成一个字符串字面量写进 worker 的 *Python* 源码里的，一轮 30 页的 run 会产生好几 MB 的源码，CPython 得先把整个字符串拉过 tokenizer 才能开始写入 —— 那个内存尖峰正好落在写 Sheet 的那一刻。现在 jobs 放独立 JSON 档，worker 用 `json.load()` 读，产生的 worker 维持 KB 级。

- `v1.6.1` 修掉了 Sheet 写入 subprocess 的一个 bug：生成的 worker 用 JSON 编码器把参数嵌进「生成的 Python 源码」里，默认的 `gid=None` 于是变成裸的 `null` token，worker 还没连上 Google 就先 `NameError: name 'null' is not defined` 死掉。因为写入流程只有在 subprocess 失败时才会退回 in-process，每一次 run 其实都悄悄失去了那层 subprocess 的 timeout 保护。现在参数改用 Python 字面值嵌入。

较早版本：

- `v1.6.2` 把 jobs 数据移出生成的 Sheet 写入 worker 源码。
- `v1.6.1` 把生成 worker 的参数改用 Python 字面值，不再用 JSON。
- `v1.6.0` 把 LinkedIn 自 v1.3.1 就有的 30/60/90s retry ladder 补给 JobStreet list page。
- `v1.3.1` 在 source layer 新增 LinkedIn list page 429 retry。
- `v1.3.0` 移除 Jora 与 JobStreet 网络集成，主动来源 contract 收敛为 LinkedIn，同时保留历史 Tracker row 的解析能力。

- `pyproject.toml` 保存套件版本。
- `.codex-plugin/plugin.json` 保存 plugin 版本。
- `server_v1_1.py` 对外提供 MCP server 版本。
- 当前 frozen equivalence baseline 为 `v1.6.8`，明确保护五来源 contract、「每个来源一个 adapter」的拆分、JobStreet list page 的 retry ladder、LinkedIn 空页与 JD retry 规则、「range 的页数上限必须盖得住每个已知城市的实测池深」规则、「每个 JobStreet keyword 都要爬到自己的池底」规则、「Guest API 1000 笔分页窗口是结束而不是失败」规则、「pre-detail dedup 读的是要写入的那个分页」规则，以及「生成 worker」的相关规则。

## 许可

MIT。见 [`LICENSE`](LICENSE)。
