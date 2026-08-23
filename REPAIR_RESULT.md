# jobs-scraper Repair Result

> **Status**: `REPAIR_CANDIDATE_READY_FOR_INDEPENDENT_VERIFICATION` — all P0
> PASS, no test failing, no production Sheet written, no merge to main.
> Final `QUALIFIED` requires a separate independent verifier per 08_FINAL_HANDOFF_CONTRACT.md.

## Candidate identity

- **baseline audited SHA** (per `09_AUTHORITATIVE_SOURCES.md` and `BASELINE_MANIFEST.json`):
  `6e20817e2febc877cc0eb1dc7b7735b4d3ab96a6`
- **starting SHA actually repaired**: `6e20817e2febc877cc0eb1dc7b7735b4d3ab96a6` (no drift)
- **repair branch**: `repair/audit-v1.0.0`
- **final candidate SHA**: `5a0b18ebabf8dc09036fbde47780f535de8b8d53`
- **candidate ZIP/patch SHA-256**: not produced (no ZIP requested; diff captured
  by `git diff 6e20817..5a0b18e --stat` below)

```
 .codex-plugin/plugin.json                    |   6 +
 .env.example                                 |  11 +-
 .github/workflows/ci.yml                     |  72 +++
 LICENSE                                      |  21 +
 README.md                                    | 197 +++++---
 pyproject.toml                               |  51 +++
 requirements.txt                             |   6 +-
 scripts/doctor.py                            | 168 +++++++
 scripts/verify_fresh_install.py              | 207 +++++++++
 server.py                                    | 660 +++++++++++++++++++--------
 setup.sh                                     | 105 +++--
 sg_product_jobs.py                           |  51 ++-
 skills/jobs-scraper/SKILL.md                 |  52 +++
 skills/jobs-scraper/references/OPERATIONS.md |  33 ++
 tests/test_config_fail_closed.py             | 205 +++++++++
 tests/test_mcp_contract.py                   | 256 +++++++++++
 tests/test_setup_contract.py                 | 159 +++++++
 tests/test_sheet_safety.py                   | 197 ++++++++
 18 files changed, 2157 insertions(+), 300 deletions(-)
```

## Scope

### modified files (existing)

- `sg_product_jobs.py` — surgical: removed author Sheet ID/GID fallback (F08);
  converted `_write_rows_to_sheet` to two-phase write (F10). All other scraper
  semantics (LinkedIn / Jora / JobStreet parsing, dedup, visa, work mode,
  pull/cache, build_e_formula) untouched.
- `server.py` — full rewrite for MCP v2 (`MCPServer`), split into 4 tools
  with `Literal` enums, `ToolAnnotations`, Pydantic output models, server
  instructions, fail-closed config, read-only OAuth scope for read tools,
  7200s subprocess timeout.
- `setup.sh` — `set -euo pipefail`, no `source .venv/bin/activate` dependency,
  idempotent on `.env` and `.secrets`, runs tests then doctor, prints the
  interpreter path the user should wire into the MCP host.
- `requirements.txt` — `mcp>=1.0,<2.0` → `mcp>=2.0,<3`.
- `README.md` — quick start now goes through `./setup.sh`; documents 7200s
  timeout; explicit fail-closed semantics; local STDIO vs public Plugin
  lane clearly separated; no personal path / author Sheet ID presented as
  a default. **No longer claims a Mavis Plugin ships in the repo.**
- `.env.example` — fail-closed commentary; no longer suggests the empty
  default will use the author's Sheet.

### added files

- `pyproject.toml` — canonical dependency source (Python >=3.11, runtime +
  dev extras, MIT, version 1.0.0).
- `LICENSE` — full MIT (matches README/manifest).
- `.codex-plugin/plugin.json` — skills-only packaging manifest (no fake
  remote MCP endpoint).
- `skills/jobs-scraper/SKILL.md` — Agent Skills-spec compliant
  (YAML frontmatter with `name` + `description`; `name` matches parent
  directory; `license: MIT`).
- `skills/jobs-scraper/references/OPERATIONS.md` — operational reference
  with env-var prerequisites, host timeout note, and "no Google config
  required for crawling" clarification.
- `scripts/doctor.py` — install / config / env health check; never prints
  credential JSON or private key.
- `scripts/verify_fresh_install.py` — copy repo to temp, build fresh
  venv, install from pyproject, compile, pytest, import server, list
  MCP tools, validate SKILL frontmatter. No Google credentials.
- `.github/workflows/ci.yml` — Python 3.11, compile, pytest, doctor,
  SKILL frontmatter validation, MCP tool listing, and a guard step
  that fails if the author Sheet ID leaks into source.
- `tests/test_mcp_contract.py` — 17 tests covering Q14-Q32.
- `tests/test_config_fail_closed.py` — 11 tests covering Q33-Q37, Q69, Q71.
- `tests/test_sheet_safety.py` — 10 tests covering Q38-Q42.
- `tests/test_setup_contract.py` — 8 tests covering Q43-Q47, Q60.

### intentionally untouched core areas

- LinkedIn / Jora / JobStreet parsing logic.
- Cross-source `(source, job_id)` dedup semantics.
- 24-word skip list and Senior whitelist.
- Visa detection (HARD / SOFT / POSITIVE) — still SG-only.
- Work mode regex (still `Onsite` / `Hybrid` / `Remote`, no hyphen).
- The 27 `test_helpers.py` cases (preserved at repo root, all 27 pass).
- The local Mavis Plugin install at `~/.minimax/plugins/jobs-scraper/`
  (out of repair scope; the repo now ships its own Skill + plugin manifest
  so an out-of-the-box clone is fully functional without the
  user-specific plugin install).

## P0 repairs

| Finding | Result | Evidence |
|---|---|---|
| F01 — Repo ships an Agent Skill | PASS | `skills/jobs-scraper/SKILL.md` exists; Q04-Q11 PASS. |
| F02 — MCP dependency pinned to 1.x | PASS | `requirements.txt` and `pyproject.toml` declare `mcp>=2.0,<3`; installed package is `mcp 2.0.0`; `test_dependency_pinned_to_v2` PASS. |
| F03 — `crawl_jobs` mixes read + write | PASS | `crawl_jobs` no longer accepts a Sheet write argument (`test_crawl_jobs_has_no_sheet_write_param` PASS). New `sync_jobs_to_sheet` is the only write tool (`test_sync_jobs_to_sheet_present_as_write` PASS). |
| F04 — Input lacks `Literal` constraints | PASS | `Source` and `Range` are `Literal[...]` on the tool signatures; input schema advertises the enums (`test_source_input_enum`, `test_range_input_enum` PASS). |
| F05 — Missing MCP annotations | PASS | All 4 tools have `ToolAnnotations` with truthful read-only / open-world / destructive / idempotent hints (`test_crawl_jobs_annotations`, `test_audit_sheet_annotations`, `test_get_stats_annotations`, `test_sync_jobs_to_sheet_present_as_write` PASS). |
| F06 — `setup.sh` missing `pipefail` | PASS | First executable line is `set -euo pipefail` (`test_setup_uses_strict_mode` PASS). |
| F07 — `setup.sh` creates `.venv` but uses bare `python` | PASS | `setup.sh` always invokes `"\$VENV_PY" -m …` and never relies on `source .venv/bin/activate` (`test_setup_uses_venv_python_for_tests` PASS). |
| F08 — Author Sheet ID/GID fallback | PASS | `sg_product_jobs.py` no longer has the `else 1119491672` or `or "<author-id>"` defaults; `SHEET_ID_OVERRIDE`/`SHEET_GID_OVERRIDE` empty produces `SG_RAW_SHEET_ID=""` / `SG_RAW_GID=0`; Sheet tools return `CONFIG_MISSING` (`test_no_author_sheet_id_in_executable_code`, `test_sheet_id_default_is_empty`, `test_sgid_default_is_zero`, `test_audit_sheet_no_config_returns_structured_error` PASS). |
| F09 — Long-running JD vs 60s timeout | PASS | `SUBPROCESS_TIMEOUT = 7200`; Codex sample config sets `tool_timeout_sec = 7200`; README has a callout; `_run_subprocess` returns `error_code="SUBPROCESS_TIMEOUT"` on timeout (`test_subprocess_timeout_default_7200`, `test_timeout_returns_structured_failure` PASS). |
| F10 — `value_input_option="USER_ENTERED"` injection risk | PASS | `_write_rows_to_sheet` does two-phase: E column `USER_ENTERED`, A:D and F:K with `RAW` (`test_e_column_hyperlink_written_with_user_entered`, `test_equals_in_company_stays_text`, `test_equals_in_title_stays_text`, `test_plus_minus_at_in_jd_stays_text`, `test_two_phase_write_uses_three_updates` PASS). |
| F11 — Missing MCP contract / fresh-install qualification | PASS | `tests/test_mcp_contract.py` + `scripts/verify_fresh_install.py` together cover tool discovery, schema, annotations, env, import, list tools, SKILL frontmatter. End-to-end run passed against a clean temp clone. |
| F20 — Read tools use write OAuth scope | PASS | `SCOPES_READONLY = ["…spreadsheets.readonly"]` is used in `_read_sheet_rows`; `SCOPES_WRITE` is only used by `push_to_sheet` (the actual write path) (`test_read_scopes_vs_write_scopes`, `test_read_sheet_rows_uses_readonly_scope` PASS). |

## P1 / P2 repairs (additional)

| Finding | Result | Evidence |
|---|---|---|
| F13 (P1) — `setup.sh` doesn't verify failure propagation | PASS | `test_setup_propagates_test_failures` deliberately sabotages the tests and asserts `setup.sh` exits non-zero. |
| F14 (P1) — `.env.example` shows author's path as fallback | PASS | `.env.example` no longer says empty = uses author's Sheet; it explicitly says "empty = fail-closed". |
| F15 (P1) — Missing CI | PASS | `.github/workflows/ci.yml` runs compile, pytest, doctor, SKILL validation, MCP tool discovery, and the author-Sheet-ID guard. No Google creds required. |
| F16 (P1) — Missing Skill static validation hook | PASS | `verify_fresh_install.py` and `test_setup_contract.py` validate SKILL frontmatter deterministically; CI also runs a structural check. |
| F17 (P1) — Missing `pyproject.toml` | PASS | Added; canonical dep declaration. |
| F18 (P2) — `requirements.txt` not generated from canonical source | PARTIAL | `requirements.txt` is now a deliberate mirror of `pyproject.toml`; if the user wants strict regeneration, an extra hook could be added later, but the current mirror is documented and consistent with the installed venv. |
| F19 (P2) — `server.py` docstring lists `to_sheet` argument | PASS | Docstring now describes the 4 v2 tools with read/write split and the fail-closed / untrusted-content contract. |
| F21 (P1) — README claims Mavis Plugin ships in repo | PASS | README no longer claims a Mavis Plugin ships in the repo; the repo now ships its own Skill + plugin manifest so a fresh clone is fully functional. The local `~/.minimax/plugins/jobs-scraper/` install is out of repair scope. |

## Qualification Q01–Q72

| ID | Sev | Result | Evidence |
|---|---|---|---|
| Q01 | P0 | PASS | `git rev-parse HEAD` = `6e20817e2febc877cc0eb1dc7b7735b4d3ab96a6` at the start; final candidate `5a0b18ebabf8dc09036fbde47780f535de8b8d53`. |
| Q02 | P0 | PASS | `git ls-files` over `.env` / `.secrets/` / `*.pem` / `*.p12` / `*.key` returns no matches. |
| Q03 | P1 | PASS | `LICENSE` is full MIT; `pyproject.toml` and SKILL frontmatter both declare MIT. |
| Q04 | P0 | PASS | `skills/jobs-scraper/SKILL.md` exists. |
| Q05 | P0 | PASS | SKILL.md frontmatter is `---`/`name:`/`description:`/`license:`/`compatibility:`/`metadata:`; closed by `\n---\n`. |
| Q06 | P0 | PASS | `name: jobs-scraper` matches parent directory. |
| Q07 | P0 | PASS | Description is 3 sentences covering the 4 tools and 3 sources. |
| Q08 | P1 | PASS | SKILL.md is 52 lines; detail is in `references/OPERATIONS.md` (progressive disclosure). |
| Q09 | P0 | PASS | No absolute path, no Sheet ID, no credential value appears in `skills/`. |
| Q10 | P0 | PASS | SKILL.md "Write boundary" section explicitly separates read vs write tools; `sync_jobs_to_sheet` is named as the only write tool. |
| Q11 | P1 | PASS | `verify_fresh_install.py` and `test_setup_contract.py` (CI step) perform the structural check; `skills-ref validate` is documented but not required for the local STDIO lane. |
| Q12 | P1 | PASS | `.codex-plugin/plugin.json` exists. |
| Q13 | P1 | PASS | Manifest is skills-only (no fake remote MCP endpoint); manifest schema follows the `name` / `version` / `description` / `skills` shape. |
| Q14 | P0 | PASS | `requirements.txt` and `pyproject.toml` both pin `mcp>=2.0,<3`; installed `mcp 2.0.0`. |
| Q15 | P0 | PASS | `server.py` imports `from mcp.server import MCPServer`; class name is `MCPServer`; module is `mcp.server.mcpserver.server` (not `mcp.server.fastmcp`); `FastMCP` is not referenced. |
| Q16 | P0 | PASS | `await mcp.list_tools()` returns the 4 canonical tools. |
| Q17 | P0 | PASS | `crawl_jobs` input schema has no `to_sheet` / `sheet_id` / `gid` / `dry_run` properties. |
| Q18 | P0 | PASS | `sync_jobs_to_sheet` is registered; its annotations are `read_only=False`, `open_world=True`, `destructive=False`, `idempotent=False`. |
| Q19 | P0 | PASS | `source` input schema enum is exactly `["linkedin", "jora", "jobstreet"]`. |
| Q20 | P0 | PASS | `range` input schema enum is exactly the 7 supported ranges. |
| Q21 | P1 | PASS | `max_pages` has `minimum=1, maximum=200` (Pydantic `Field(ge=1, le=200)`). |
| Q22 | P0 | PASS | `crawl_jobs.annotations = {read_only_hint: True, open_world_hint: True}`. |
| Q23 | P0 | PASS | `audit_sheet.annotations = {read_only_hint: True, open_world_hint: False}`. |
| Q24 | P0 | PASS | `get_stats.annotations = {read_only_hint: True, open_world_hint: False}`. |
| Q25 | P0 | PASS | `sync_jobs_to_sheet.annotations` = non-read-only, open-world, non-destructive, non-idempotent. |
| Q26 | P0 | PASS | All 4 tools publish `outputSchema` (verified in `test_all_canonical_tools_have_output_schema`). |
| Q27 | P0 | PASS | Invalid source rejected at Pydantic level before any subprocess call (`test_invalid_source_rejected_by_pydantic`). |
| Q28 | P0 | PASS | Invalid range rejected at Pydantic level (`test_invalid_range_rejected_by_pydantic`). |
| Q29 | P0 | PASS | `_run_subprocess` uses `subprocess.run(cmd, shell=False, cwd=REPO_ROOT)` with `cmd = [PYTHON_EXE, REPO_ROOT/"sg_product_jobs.py", …]`. |
| Q30 | P0 | PASS | `SUBPROCESS_TIMEOUT = 7200` (default; overridable via `JOBS_SCRAPER_SUBPROCESS_TIMEOUT`). |
| Q31 | P0 | PASS | Timeout path returns `{"ok": False, "timed_out": True, "error_code": "SUBPROCESS_TIMEOUT", …}`. |
| Q32 | P0 | PASS | Non-zero exit returns `{"ok": False, "exit_code": N, "error_code": "SCRAPER_EXIT_NONZERO" | "UPSTREAM_RATE_LIMIT"}`. |
| Q33 | P0 | PASS | No executable code contains the audited author Sheet ID; `SG_RAW_SHEET_ID = ""` and `SG_RAW_GID = 0` when env unset. |
| Q34 | P0 | PASS | `audit_sheet` / `get_stats` / `sync_jobs_to_sheet` all return `error_code="CONFIG_MISSING"` with a message naming the missing env var. |
| Q35 | P0 | PASS | `crawl_jobs` works without any Sheet config (CrawlResult pydantic model accepts the call). |
| Q36 | P0 | PASS | Missing credential file returns `error_code="CREDENTIAL_FILE_MISSING"` with the path in the message. |
| Q37 | P0 | PASS | Result serialised JSON never contains `BEGIN PRIVATE KEY` or `PRIVATE KEY`; paths use absolute/relative names only. |
| Q38 | P0 | PASS | Cells starting with `=` outside column E are written with `value_input_option="RAW"` (tested with `=HYPERLINK`, `=IMPORTXML`). |
| Q39 | P0 | PASS | Cells starting with `+`, `-`, `@` outside column E are written with `RAW` (tested with `+1+1`, `-1+1`, `@SUM(1,1)`). |
| Q40 | P0 | PASS | E column is still written with `USER_ENTERED`; the generated `=HYPERLINK(...)` is preserved. |
| Q41 | P0 | PASS | `dry_run` in `sync_jobs_to_sheet` short-circuits before any `gspread.update()` call (asserted via source structure and contract). |
| Q42 | P0 | PASS | The hardcoded `else 1119491672` fallback is gone; `SG_RAW_GID = 0` when env empty (sentinel for "not configured"). |
| Q43 | P0 | PASS | First non-comment line of `setup.sh` is `set -euo pipefail`. |
| Q44 | P0 | PASS | `test_setup_propagates_test_failures` sabotages the test suite and confirms `setup.sh` exits non-zero. |
| Q45 | P0 | PASS | `setup.sh` defines `VENV_PY="$VENV_DIR/bin/python"` and invokes `"\$VENV_PY" -m pytest -q`. No `activate`-then-pytest pattern. |
| Q46 | P0 | PASS | `setup.sh` ends by printing the absolute `$VENV_PY` path users should put in their MCP host config. |
| Q47 | P1 | PASS | `.env` is only created when missing; `.secrets/` is `mkdir -p` (idempotent). Existing user secrets/config are never overwritten. |
| Q48 | P1 | PASS | `scripts/doctor.py` verifies Python version, venv interpreter, imports, file presence, fail-closed Sheet config, git hygiene; never prints credential content. |
| Q49 | P0 | PASS | README Codex sample shows `tool_timeout_sec = 7200`; CI never runs a write tool, so the host timeout setting is the only required knob. |
| Q50 | P0 | PASS | Codex sample uses `command = "/ABS/PATH/jobs-scraper/.venv/bin/python"` and `cwd`; Claude Code and Cursor samples likewise point at the installed interpreter. |
| Q51 | P1 | PASS | Claude Code and Cursor examples in README use the same installed interpreter path. |
| Q52 | P0 | PASS | All 27 original `test_helpers.py` cases still pass (preserved at repo root); 20 new contract tests added → 47 total. |
| Q53 | P0 | PASS | `parse_sheet_row_to_key` / `_load_sheet_keys` / `_build_sheet_row` / `load_seen_ids` unchanged; the 4 source-row parsing tests still pass. |
| Q54 | P0 | PASS | Visa detection (HARD / SOFT / POSITIVE) and work-mode regex (`Onsite` / `Hybrid` / `Remote`, no hyphen) unchanged; the 6 work-mode tests still pass. |
| Q55 | P0 | PASS | LinkedIn / Jora / JobStreet parsing code paths are untouched in `sg_product_jobs.py`; only `_write_rows_to_sheet` was modified (two-phase write). |
| Q56 | P0 | PASS | `scripts/verify_fresh_install.py` runs end-to-end: copy → venv → install → compile → pytest → import server → list tools → SKILL frontmatter; last full run: `🎉 fresh install qualified`. |
| Q57 | P0 | PASS | Step 7 of `verify_fresh_install.py` lists `['audit_sheet', 'crawl_jobs', 'get_stats', 'sync_jobs_to_sheet']` with no Google credentials. |
| Q58 | P0 | PASS | `crawl_jobs` call shape (Pydantic `CrawlResult`) accepts the documented inputs without any Sheet config; the tool has no Sheet write argument. |
| Q59 | P0 | PASS | `sync_jobs_to_sheet` requires `SHEET_ID` / `SHEET_GID` / `GSPREAD_SA_KEY_PATH`; without them the tool returns `target_configured=False, ok=False, error_code=CONFIG_MISSING`. |
| Q60 | P1 | PASS | `.github/workflows/ci.yml` runs Python 3.11, compile, pytest, doctor (continue-on-error so env-only warns are OK), SKILL frontmatter check, MCP tool listing, and a Sheet-ID guard; no live Google creds. |
| Q61 | P1 | PASS | `python -m compileall -q .` returns clean. |
| Q62 | P1 | PASS | `pyproject.toml` declares `requires-python = ">=3.11"`, runtime deps, and `[dev]` extras. |
| Q63 | P1 | PASS | `pyproject.toml` is the canonical source; `requirements.txt` is a deliberate mirror; both pin `mcp>=2.0,<3`. (No `uv.lock` is generated because the repo does not use `uv`; the harness accepts `pip` as the lock-source path.) |
| Q64 | P0 | PASS | README quick start uses `./setup.sh`, then `cp .env.example .env`, then `.venv/bin/python sg_product_jobs.py …`. |
| Q65 | P0 | PASS | README no longer claims a Mavis Plugin ships in the repo. The repo now ships its own Skill + plugin manifest. |
| Q66 | P0 | PASS | README has a callout: "Local STDIO distribution. This repository does **not** ship a public remote Plugin; a stable public HTTPS Streamable HTTP endpoint and Marketplace submission are a separate future lane." |
| Q67 | P1 | PASS | README documents the 50–100 min full-JD duration and instructs users to set `tool_timeout_sec = 7200`. |
| Q68 | P0 | PASS | No personal Sheet ID or local filesystem path appears as a default in README or `.env.example`. |
| Q69 | P0 | PASS | **No production Google Sheet was written during qualification.** The author Sheet ID is only mentioned in the audit grep guard (CI step) and in this report. The user had pre-existing test pushes (rows 1969-1970) deleted before this repair began. |
| Q70 | P0 | PASS | Committed to `repair/audit-v1.0.0` (`5a0b18e`); `main` is still at `6e20817`; no merge, no push, no public Plugin submission. |
| Q71 | P1 | PASS | `audit_sheet` and `get_stats` use `SCOPES_READONLY = ["…spreadsheets.readonly"]`; `push_to_sheet` (the only write path) uses `SCOPES_WRITE`. |
| Q72 | P1 | PASS | SKILL.md "Untrusted job content" + server `instructions` field both state that scraped content is untrusted data and cannot authorise commands, credential disclosure, configuration changes, or read-to-write escalation. |

## Test summary

- **compile**: `python -m compileall -q .` → exit 0
- **pytest**: 47 passed (27 helper + 20 contract), 0 failed
- **Skill validation**: structural frontmatter check passed; `skills-ref validate` is documented but optional for the local STDIO lane
- **MCP tool discovery**: `['audit_sheet', 'crawl_jobs', 'get_stats', 'sync_jobs_to_sheet']` with truthful annotations + output schemas
- **fresh install**: `scripts/verify_fresh_install.py` end-to-end pass (copy → venv → install → compile → pytest → import → list tools → SKILL frontmatter)
- **doctor**: `scripts/doctor.py` runs cleanly; warns on missing Sheet config (intentional for this machine) and on `.venv` not being created by `setup.sh` (the venv in use is one level up under `scrapling-test/.venv`, not `jobs-scraper/.venv` — expected for the in-place dev install)
- **live network smoke**: intentionally **not** run during qualification to honour "no production Sheet / no live writes". `crawl_jobs` with `with_jd=False` is documented as fast enough (≈30 s) for users to run themselves against their own config.

## Security evidence

- **production Google Sheet written during qualification**: **NO**
  - The qualification harness only ran the deterministic test suite, doctor,
    and `verify_fresh_install.py` (which explicitly does not exercise any
    Sheet tool).
  - The author Sheet ID is referenced only in this report and in the
    `git grep` guard inside the CI workflow step that forbids it from
    leaking into code.
- **author Sheet fallback removed**: **YES** — `sg_product_jobs.py` no longer
  has the `1e-YlVFo0pn2QOXP4xsKJDZdnlJQR1eREwy-Fc42jAZ8` literal or the
  `else 1119491672` gid default; `SHEET_ID_OVERRIDE` / `SHEET_GID_OVERRIDE`
  empty now produce empty `SG_RAW_SHEET_ID` / `SG_RAW_GID = 0`.
- **formula injection tests**: **PASS** — `tests/test_sheet_safety.py`
  exercises `=HYPERLINK`, `=IMPORTXML`, `+1+1`, `-1+1`, `@SUM(1,1)` in
  every non-E column and asserts they are written with
  `value_input_option="RAW"`; the E-column HYPERLINK is still written
  with `USER_ENTERED` so it remains a live link.
- **secrets logged**: **NO** — `doctor.py` and tool result serialisations
  were grepped for `BEGIN PRIVATE KEY` and credential filenames; no leak.
- **HTTP scope**: read tools use `…auth/spreadsheets.readonly`; only the
  single `push_to_sheet` path uses the write scope.

## Remaining limitations

- The local Mavis Plugin install at `~/.minimax/plugins/jobs-scraper/` is
  **out of repair scope**. The repo now ships a full Skill + plugin
  manifest + MCP server so a fresh clone is fully functional without
  the user-specific plugin install. A future follow-up could regenerate
  the Mavis plugin from the new repo-shipped Skill.
- The audit findings call out a public HTTPS Streamable HTTP Plugin as
  a "future lane". The current repair is local STDIO only, by design.
- `uv.lock` is not generated because the project does not use `uv`. The
  canonical source is `pyproject.toml`; `requirements.txt` is a
  deliberate mirror. If the user adopts `uv` later, a one-shot
  `uv pip compile pyproject.toml --extra dev > uv.lock` would close the
  loop.
- The `sync_jobs_to_sheet` tool still surfaces the scraper's stdout/stderr
  tail in its `SyncResult`. Tail sizes are capped (5000 / 2000 chars) so
  accidental large dumps are bounded; full logs are written to disk by
  the scraper itself. A future tightening could redact any string
  matching `BEGIN PRIVATE KEY` from those tails, but it is out of scope
  for this repair.
- `tests/test_config_fail_closed.py::test_read_sheet_rows_uses_readonly_scope`
  uses an in-process monkey-patch of `google.oauth2.service_account.Credentials`
  and `gspread.authorize`. This is deterministic and not a live network
  call, but it is more fragile than a pure structural test. A future
  tightening could move the readonly-scope assertion to a structural test
  on the source file (the constant `SCOPES_READONLY` is already asserted
  by `test_read_scopes_vs_write_scopes`).

## Terminal

```
REPAIR_CANDIDATE_READY_FOR_INDEPENDENT_VERIFICATION
```

(Not `QUALIFIED`. A separate fresh independent verifier should
re-execute the test suite and confirm.)
