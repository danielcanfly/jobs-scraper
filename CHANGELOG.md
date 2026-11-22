# Changelog

## v1.6.6 — 2026-11-22

A crawl that stops early still reports success, and a dedup pass that reads the wrong tab still looks like it worked. Both happened.

Fixed

- **A range's page budget now covers the pool that range actually has.** The LinkedIn range table gave `30d` a 25-page budget — 250 postings — while Shanghai's 30-day pool holds about 700. The crawl stopped at the budget, the run reported success, and the postings past the budget were never seen at all: the 2026-11-22 Shanghai 30d run collected 700 postings where the default would have collected 250. The same held for every other range. Measured against the live Guest API on 2026-11-22 by walking the list API until it answered with an empty page (Shanghai, geoId `107388191`): `1h` under 50, `24h` about 100, `3d` about 250, `7d` about 400, `14d` about 290, `21d` about 300, `30d` about 700 postings. The budgets are now `5 / 15 / 35 / 55 / 40 / 45 / 95` pages. A budget is a ceiling, not a target — the crawl ends itself after two consecutive pages with no new posting — so a city with a small pool still stops early and a wider budget costs it nothing. The time filters themselves are unchanged, and an explicit `--max-pages` still overrides the default.
- **The pre-detail dedup reads the tab the run is about to write to.** The dedup pass that skips postings already on the Sheet *before* fetching their JD resolved its worksheet from a label→gid table in which `"LinkedIn / Minimax"` always pointed at `SG-Raw`. A China run therefore compared its postings against Singapore's tab, kept every one of them, and paid for a full JD fetch round that the Sheet writer was going to discard anyway. Only the cross-run JSON cache hid the cost; a cache miss meant a whole extra JD crawl for postings that were never new. The target gid is now resolved with the same precedence the writer uses — explicit `--gid`, then the `#gid=` inside `--to-sheet`, then the label mapping — and threaded into the loader, into the generated worker and into `main()`. With no target given, the label mapping still applies, so the Singapore and Taiwan flows behave exactly as before.
- **The release pipeline is green again.** v1.6.5 bumped `pyproject.toml` but not `uv.lock`, so CI failed at its first gate (`uv lock --check`) and stayed red on GitHub. The lockfile is regenerated and the Agent Skill's version line — which had been left behind at v1.6.4 — moves with the rest of the build.

Acceptance

- `tests/test_linkedin_range_pages_v166.py` (7 tests) pins every range's budget to its measured pool depth, that no budget shrank, that the time filters are unchanged, that the engine uses the adapter's table, and that an explicit `--max-pages` still wins.
- `tests/test_pre_dedup_target_gid_v166.py` (17 tests) pins that an explicit gid beats the label mapping, that the label mapping still applies without one, that an unknown label is still rejected without one, that the gid reaches the loader and the generated worker (as a Python literal), that a job already on the target tab is dropped before any JD fetch, and that `main()` hands the resolved target to the dedup pass.
- The behaviour-equivalence freeze moves to `freeze_version 11` with new crawl-budget and Sheet-target invariant sections; the frozen v1.3.0 golden stays untouched.

## v1.6.5 — 2026-11-21

Two LinkedIn Guest API failures that could end a run quietly.

Fixed

- **A legitimately empty list page no longer kills the crawl.** LinkedIn's "no results" page is 26 bytes: `<!DOCTYPE html>\n\n<!---->`. Scrapling builds no root element for that body, so the list parser raised `AttributeError: 'NoneType' object has no attribute 'xpath'` — inside the parser, outside the crawl's own error handling. One empty page ended the page loop, the chunk and the run: on 2026-11-21 all three chunks of the Hangzhou crawl died this way and **zero** rows reached the Sheet, while the run still reported a clean exit. The parser now treats a body it cannot root as **zero jobs**, so the crawl's own empty-streak rule decides the results are exhausted and moves on to the next page. An empty page stays a legitimate answer — it is *not* retried, exactly as before.
- **A throttled JD fetch no longer makes a posting disappear.** `fetch_jd` gave up on the first HTTP 429. A job whose JD never arrived has no JD text, and the Sheet writer skips such a row entirely — so a rate-limited request did not fail the run, it just dropped a posting (4 of the first 10 Shanghai jobs on 2026-11-21). The JD fetch now uses the same 30/60/90s ladder as the list fetch: 429, 5xx and connection errors are retried (four attempts), any other 4xx is still a caller bug and is not retried.

Neither fix is China-specific — the empty page and the 429 are properties of the Guest API and hit every source and every region the same way.

Acceptance

- `tests/test_linkedin_resilience_v165.py` (12 tests) pins the empty page parsing to zero jobs, that a crawl keeps going past an empty page and still collects the jobs of the next one, that an empty page is not retried, and the JD ladder: a 429, a 5xx and a connection error are retried and then succeed, four 429s report the rate limit, a 200 and a non-429 4xx are not retried, and the engine still injects the sleep hook.
- The behaviour-equivalence freeze moves to `freeze_version 10` with a new LinkedIn-resilience invariant section; the frozen v1.3.0 golden stays untouched.

## v1.6.4 — 2026-11-19

China is three cities now, and a China posting carries no visa judgement.

Added

- **Hangzhou and Shenzhen are regions of their own.** `China` was Shanghai; it now is one of three. `region="Hangzhou"` and `region="Shenzhen"` crawl their own city and write into the same `China-Raw` tab, resolved through a new tab-base rule in `region_policy.py` (`REGION_TAB_BASE`) instead of the plain `<REGION>-Raw` naming. Aliases work too: `hz` / `杭州`, `sz` / `深圳`.
- **Both geoIds were verified against the live Guest API**, not copied from a list: `Hangzhou` is `101821877` and `Shenzhen` is `106750182` (LinkedIn GEO typeahead), and a real list fetch for each returns postings located in that city. They sit in the LinkedIn adapter's preset table, so `--location Hangzhou` and `--location Shenzhen` work on the CLI as well.
- The city regions are **opt-in**: the default region set stays `SG` / `TW` / `China`, and the expected-tab list is de-duplicated so initializing several China regions never creates `China-Raw` twice.

Changed

- **China-specific visa judgement is gone.** `Chinese citizens only`, `PRC nationals only`, `must be a Chinese citizen`, `僅限中國公民`, `必須為中國公民`, `上海戶口優先`, `中國人優先` and `大陸人優先` no longer produce any visa signal, because a Taiwan resident can take a permit into mainland China.
- The generic coverage was deliberately kept and strengthened: a Singapore or Taiwan posting that requires any citizenship is still a HARD signal. A nationality-agnostic `must be a <nationality> citizen/national` pattern replaces the deleted Chinese/PRC-specific one so a Singapore posting that asks for a Chinese citizen is not silently downgraded. The Singapore-only gate on the Sheet's visa column is unchanged, and China rows were never evaluated in the first place.

Acceptance

- `tests/test_china_regions_v164.py` (12 tests) pins the two geoIds and that they stay distinct, the CLI preset resolution, the city aliases, the tab-base rule, the de-duplicated expected-tab list, the initializer plan that creates `China-Raw` once, the seven China phrases that now produce no signal, and the Singapore/Taiwan citizenship phrases that must still be HARD.
- The MCP contract tests and the frozen golden region enum grow to `SG | TW | China | Hangzhou | Shenzhen`.
- The behaviour-equivalence freeze moves to `freeze_version 9` with a new China-region invariant section.

## v1.6.3 — 2026-11-19

The crawl path can be told which way out to take.

Fixed

- The LinkedIn Guest API started answering a direct request with **HTTP 451** ("Unavailable For Legal Reasons") from this machine, so every LinkedIn chunk ended with `無資料，結束` and the run collected nothing. The Google Sheets API times out on a direct connection here for the same reason: the egress IP is filtered.
- Both work through the local proxy. The resolution now lives in one shared helper, `jobs_scraper.sources.resolve_proxies()`, and every adapter that talks to a third party uses it. `JOBS_SCRAPER_PROXY` wins when set, then the standard `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`. Nothing is set → direct.
- `CAKE_HTTP_PROXY` keeps its own priority for the Cake source and now falls back to the shared resolution instead of duplicating it.
- The LinkedIn adapter passes the resolved proxy on both its list fetch and its JD fetch, so the crawl does not depend on libcurl picking the variable up implicitly.

Acceptance

- `tests/test_source_proxy.py` pins the priority order, the `host:port` normalisation, the empty-variable fall-through, Cake's own override, that the LinkedIn list and JD fetches pass the resolved proxy, and that the doctor's proxy check reports a direct connection, a reachable proxy and a dead proxy differently.
- `doctor` now reports which proxy is in effect and probes whether it is still reachable — a dead proxy fails every source at once, which is much harder to diagnose than a direct connection.

Also in this release

- `.env.example` documents the proxy variables and why they exist.
- The version line moves to 1.6.3 across the engine, both MCP entrypoints, both plugin manifests, the Agent Skill, `pyproject.toml`, `uv.lock` and the three READMEs.
- The behaviour-equivalence freeze moves to `freeze_version 8`.

## v1.6.2 — 2026-11-19

The Sheet-write worker stops being a multi-megabyte Python file.

Fixed

- `push_to_sheet` builds its worker by generating a Python source file, and the jobs payload used to be serialised into that source as a string literal. A 30-page run serialises to megabytes, and CPython had to pull the whole literal through its tokenizer before the worker could start — a memory spike that lands exactly on the Sheet write.
- On this 8 GB machine that spike is not academic. The box runs with roughly 60 MB of free pages and about 10 GB of swap in use, and macOS's jetsam is actively killing processes — 2026-11-19 12:45:55 `Process knowledgeconstructiond [65607] killed by jetsam reason per-process-limit`.
- The payload now lives in its own JSON file that the worker reads with `json.load()`. The generated worker stays a few kilobytes whatever the run size, so the write path no longer adds a memory spike of its own.

Acceptance

- `tests/test_push_worker_code_gen.py` asserts the generated source stays under 4 KB for a 500-job payload, and that the worker still forwards `gid`, `location` and job titles containing quotes and newlines correctly.

Also in this release

- The version line moves to 1.6.2 across the engine, both MCP entrypoints, both plugin manifests, the Agent Skill, `pyproject.toml`, `uv.lock` and the three READMEs.
- The behaviour-equivalence freeze moves to `freeze_version 7`.

## v1.6.1 — 2026-11-19

The Sheet-write subprocess stops dying before it ever reaches Google.

Fixed

- `sg_product_jobs.py` generated the worker that performs the Sheet write by embedding its arguments with `json.dumps`. That is JSON syntax, but it was being written into generated **Python** source — and `json.dumps(None)` is the bare token `null`, an undefined name in Python.
- `--gid` defaults to `None` (the SG runs carry the worksheet id in the URL's `#gid=`), so **every** run built a worker that died on startup with `NameError: name 'null' is not defined`. The same applied to any `None` argument, such as a `None` location.
- The visible symptom was one line per run: `[PUSH SUBPROCESS WARN] worker fail: NameError: name 'null' is not defined`, immediately followed by `fallback 到 in-process (可能 hang)`.
- The damage was silent. That subprocess exists to put a hard timeout around the gspread write: `timeout_s` cannot interrupt a hung urllib3 socket from inside the process, only `subprocess.terminate()` can. Every run therefore lost the guard and wrote the Sheet in-process, where a hung write blocks the whole run with no bound. The guard had been inert since it was added on 2026-08-29.
- Arguments are now embedded as Python literals (`_py_literal`), so `None` stays `None`, `True` stays `True`, and strings are escaped by Python rather than by a JSON encoder.

Acceptance

- `tests/test_push_worker_code_gen.py` pins the behaviour: the generated code compiles with the default `gid=None` and with a `None` location, it never contains a bare `gid=null`, and executing it against a stubbed engine forwards `gid=None`, an explicit gid, and a title containing quotes and newlines without breaking out of the generated literal.
- The two worker templates moved into `_build_pre_dedup_worker_code` / `_build_push_worker_code`, so the generated source can be tested directly instead of only through a live Sheet write.

Also in this release

- The version line moves to 1.6.1 across the engine, both MCP entrypoints, both plugin manifests, the Agent Skill, `pyproject.toml`, `uv.lock` and the three READMEs.
- The behaviour-equivalence freeze moves to `freeze_version 6`: the five-source contract, the one-adapter-per-source split and the JobStreet retry ladder stay frozen, and the generated-worker literal rule plus its regression test are added to the frozen blobs.

## v1.6.0 — 2026-10-31

The JobStreet list page gets the retry ladder LinkedIn has had since v1.3.1.

Fixed

- A JobStreet list page had no retry at all. Any failure — a connection error, a non-200 status, or a JSON decode error — ended the keyword crawl immediately.
- When the very first page failed, the crawl produced zero jobs, `main()` printed "無資料，結束" and exited 0. The caller therefore saw a **successful** run that had silently collected nothing. The real instance: on 2026-10-30 the 7d run's first JobStreet page hit curl error 56 ("Connection closed abruptly"), wrote zero rows, and still exited 0 — a false success that a supervising runner nearly accepted as a finished chunk.
- Now a 429, a 5xx, a connection error or a JSON decode error sleeps 30/60/90s and retries (four attempts in total), and any other 4xx is raised immediately instead of burning three minutes of backoff on a caller bug. The JobStreet adapter mirrors LinkedIn's ladder exactly.

Acceptance

- A run counts as successful only when the list crawl actually produced pages. The process exit code alone is not evidence that any job was collected — `RULES.md` §3 now states this for JobStreet, and the same rule applies to every source.
- `tests/test_jobstreet_list_retry.py` pins the behaviour: connection error, 429, 5xx and JSON decode error each retry and recover; the ladder stops after four attempts; a non-429 4xx is never retried; a legitimate empty page is an answer, not a failure; and a crawl whose first page recovers keeps its jobs.

Also in this release

- The version line moves to 1.6.0 across the engine, both MCP entrypoints, both plugin manifests, the Agent Skill, `pyproject.toml`, `uv.lock` and the three READMEs.
- The behaviour-equivalence freeze moves to `freeze_version 5`: the v1.5.0 five-source / one-adapter-per-source contract stays frozen, and the JobStreet retry ladder is added to the frozen blobs so it cannot drift either.

## v1.5.0 — 2026-10-26

Stage 2 of the unification: the fetching layer moves out of the engine into per-source adapters.

Structure

- Each active source's URL building, list parsing, and JD fetching now lives in `jobs_scraper/sources/<source>.py` — `linkedin.py`, `jobstreet.py`, `cake.py`, `onezerofour.py`.
- The adapters hold no global state. The HTTP session, the sleep function, and any function one adapter calls from another are injected by the caller, so the retry ladders stay observable and every adapter is exercisable without touching the network.
- `sg_product_jobs.py` keeps the public names as thin wrappers. The wrappers read the session, sleep, and hit function at call time, so patching `sg_product_jobs._cc_session`, `sg_product_jobs.time`, or a source-level function keeps working exactly as before. The engine shrinks from ~3400 to ~2870 lines and keeps what belongs to it: the title skip filter, dedup, Sheet writes, the crawl orchestration, and the CLI.
- The engine's constants alias the adapter's, so `sg_product_jobs.LINKEDIN_*`, `CAKE_*`, `JOBSTREET_*`, and `ONEZEROFOUR_*` keep working.

Contract

- Nothing observable changed. Every source's existing contract tests pass unchanged, and each move was additionally checked by diffing the old implementation against the new one across its whole branch surface — the retry ladder and its trigger conditions, the request payloads and headers, every response and error branch, the per-keyword crawl and cross-keyword de-duplication, the Cake coverage state machine, the 104 slug and work-mode mapping, and the LinkedIn JD fallback.
- The frozen behaviours are untouched: title filter v8.5, the three-phase Sheet write order, cross-source identity, the work-mode values, the retry ladders, and `seen_jds.jsonl` as the single source of truth.
- The equivalence contract moves with the code. `tests/equivalence/test_v130_equivalence.py` now expects the sources package to exist, and an AST check asserts the engine keeps only wrappers — so no behaviour ends up implemented twice.

Also in this release

- The four one-off 104 migration helpers move out of the published tree into `local_tools/`, which the gitignore and the sync preservation list both keep.

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
