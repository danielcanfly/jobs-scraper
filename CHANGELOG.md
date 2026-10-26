# Changelog

## v1.4.0 — 2026-10-26

Single version line. The plugin runtime, working copies, and this repository now carry one identical build.

Restored sources (the v1.3.0 release was LinkedIn-only; all five sources are back):

- `linkedin`, `jobstreet`, `cake`, `104` / `onezerofour` all live in `sg_product_jobs.py`, which owns URL building, list parsing, JD fetch, the title skip filter, dedup, and Sheet row writes.
- `jora` stays retired from active sources (the site closed in 2026) and is kept only for back-compat dedup of historical rows.

Fixed regressions:

- Sheet write order. `_write_rows_to_sheet` now writes `A:D RAW` -> `F:K RAW` -> `E USER_ENTERED`, so the E-column HYPERLINK is the last phase. Previously the formula was written first in the plugin build, and the working copy wrote all of `A:K` in a single `USER_ENTERED` call — which weakened the formula-injection boundary and could leave a live hyperlink behind when a data phase failed.
- LinkedIn list-page 429 hard abort. `fetch_list_page` retries on 429 / 5xx / connection error with 30/60/90s backoff across 4 attempts; a non-429 4xx raises immediately. Without it, one 429 aborted the whole list crawl and long-range runs covered only a fraction of their pages.

Title filtering:

- Skip filter v8.5 (Repair7, qualified) is the shipped default. `SKIP.md` is the semantics authority; the filter logic is a frozen contract and is not changed by this release.

State:

- `seen_jds.jsonl` is now a single source of truth shared by every execution context. Independent copies caused silent duplicates: a job fetched in one context was not recognised in the other and was written to the Sheet twice.

Removed:

- `jobs_scraper/sources/` — an unused duplicate of the LinkedIn adapter with no importer.

Also in this release:

- Version metadata unified to `1.4.0` across `sg_product_jobs.py`, `pyproject.toml`, `.minimax-plugin/plugin.json`, `.codex-plugin/plugin.json`, `server.py`, `server_v1_1.py`, and the Agent Skill.
- `RULES.md` merged into a single public-safe technical reference covering all five sources.

# Changelog

## v1.3.1 — 2026-10-09

LinkedIn list page 429 hard-abort fix.

- Added 30/60/90s backoff retry to `jobs_scraper/sources/linkedin.py::fetch_list_page`.
- Without retry, list page 429 → `r.raise_for_status()` → HTTPError → caller hard abort, leaving 14d/21d/30d runs at 6-12 pages (~57 jobs) instead of the full 30 pages (~286 jobs).
- Retry triggers on 429, 5xx, or connection error; 4 attempts; 4xx (non-429) raises immediately.
- Single page can now sustain up to 3.5 min of backoff (30+60+90s) before giving up.

## v1.3.0 — 2026-09-20

LinkedIn-only source release.

- Removed active Jora and JobStreet network adapters, crawl branches, configuration, and source-specific tests.
- Narrowed CLI and MCP source contracts to linkedin.
- Removed the JobStreet-only BeautifulSoup dependency.
- Preserved read-only parsing of historical Jora/JobStreet tracker/cache rows so existing audits and deduplication continue to work.
- Rebased the active behaviour-equivalence gate on the v1.3.0 LinkedIn-only contract.
- Updated public docs, Agent Skill metadata, CI assertions, and plugin/package version metadata.

## v1.1.1 — 2026-08-24

Narrow repository-hygiene hardening release. Scraper business behaviour is unchanged from v1.1.0.

- Replaced the private-workbook-oriented `RULES.md` with a public-safe technical reference.
- Removed package-author production worksheet metadata from current tracked text, including a legacy CLI help example and historical test literals.
- Added `scripts/check_repo_hygiene.py`, which scans the entire Git-tracked tree for known production identifiers, concrete Google Sheet URLs, service-account identities, and private-key material.
- Replaced the previous hand-picked CI production-ID grep with the repository-wide hygiene guard.
- Updated package, plugin, Agent Skill, MCP server, and `uv.lock` patch-version identity to `1.1.1`.
- Corrected the dependency-file MCP tool-count comment to include `initialize_job_tracker`.
- Moved the stale v1.0 repair-stage status report out of the repository root into `docs/history/v1.0-repair-result.md`, with an explicit historical-only banner.

Explicitly unchanged:

- LinkedIn/Jora/JobStreet URL construction and source crawling behaviour.
- JobStreet GraphQL JD retrieval.
- JD parsing, title filters, dedup, work-mode and visa semantics.
- Google Sheet row-write ordering and A:K scraper ownership.
- Legacy `server.py` behaviour.

## v1.1.0 — 2026-08-23

Added portable Region-Raw / Region-Selected Google Sheet onboarding, the A:AA Job Tracker Schema v1, atomic tracker initialization, and region-aware v1.1 MCP tools without requiring users to configure a worksheet GID.

## v1.0.0 — 2026-08-23

First independently qualified release of the multi-source scraper, local Agent Skill, and local STDIO MCP workflow.
