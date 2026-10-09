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
