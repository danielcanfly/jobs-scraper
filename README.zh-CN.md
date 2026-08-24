<p align="right">
  <a href="./README.md">English</a> |
  <a href="./README.zh-TW.md">繁體中文</a> |
  <a href="./README.zh-CN.md">简体中文</a>
</p>

# jobs-scraper

这是一个以本地优先为原则的产品管理职位搜索自动化工具，提供 CLI、本地 STDIO MCP server、Agent Skill，以及可携带的 Google 表格职位追踪表。

`jobs-scraper` v1.2.1 是建立在 v1.2.0 架构整理之上的 clean-defaults patch。它保留本地优先 runtime 和质量 gate，并让职位标题 skip filter 改为 opt-in。

## 概览

这个仓库适合想在本地抓取产品管理职位、把凭证留在自己电脑上，并按需同步到自己 Google 表格的人。

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

- 抓取 LinkedIn、Jora、JobStreet 职位。
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
- LinkedIn、Jora、JobStreet 的 source adapters；
- 拆分后的 Job Tracker modules；
- MCP service layer；
- selective Google Sheet reads；
- 内部 typed service errors 映射到稳定的 public error code；
- Ruff lint / import gate；
- 排除 byte-frozen equivalence harness 的 scoped Ruff format gate；
- mypy scaffold；
- coverage 报告。

## 支持来源与地点指定方式

| Source | 地点指定方式 |
|---|---|
| LinkedIn | LinkedIn 使用 LinkedIn `geoId` 指定地点 |
| Jora | Singapore only |
| JobStreet | Singapore only |

这个版本中，Jora 和 JobStreet 仅支持新加坡。非 SG 请求必须 fail closed，并返回 `SOURCE_REGION_UNSUPPORTED`。

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

## MCP 工具

| Tool | Sheet write? | 用途 |
|---|---:|---|
| `crawl_jobs` | 否 | 抓取 LinkedIn、Jora 或 JobStreet；可能更新本地缓存。 |
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
--source:         linkedin | jora | jobstreet
--with-jd:        抓取完整 JD
--to-sheet:       Google Sheet URL 或 raw ID
--gid:            旧版 direct CLI 用的 worksheet GID
--max-pages:      覆写来源页数上限
--refetch:        忽略 JD cache
--no-skip:        停用 title skip filter
--dry-run-sheet:  预览，不写入行数据
--location:       LinkedIn location/preset
--geo-id:         明确指定 LinkedIn geoId
--skip-keywords:   覆写 title skip list
--sheet-source:   D 栏 source label
```

默认不套用职位标题 skip filter。需要时可用 `--skip-keywords` 自定义：

```bash
python sg_product_jobs.py 14d --source linkedin --with-jd --skip-keywords intern junior assistant
```

也可以使用 `--no-skip` 明确表示不套用 skip。

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
- 这个版本不保证 Jora / JobStreet 在新加坡以外可用。
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
- `SOURCE_REGION_UNSUPPORTED`：这个版本中 Jora / JobStreet 只支持新加坡。
- `SHEET_NOT_FOUND`：确认 spreadsheet ID 与分享权限。
- `LinkedIn 403/429`：缩小范围或稍后再试。

## 版本与发布说明

`v1.2.1` 是建立在已经通过验证的 v1.2.0 之上的 clean-defaults patch。

- `pyproject.toml` 保存套件版本。
- `.codex-plugin/plugin.json` 保存 plugin 版本。
- `server_v1_1.py` 对外提供 MCP server 版本。
- frozen equivalence baseline 仍然是 `v1.1.1`。

## 许可

MIT。见 [`LICENSE`](LICENSE)。
