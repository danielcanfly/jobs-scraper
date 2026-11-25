# Changelog

## v1.8.3 — 2026-11-25

The repository held the supervisors, but the sync never carried them.

Fixed

- **The plugin runtime was never going to receive `ops/`.** v1.8.2 put the 33 crawl supervisors and the tooling around them into the repository, but `scripts/sync-from-repo.sh` merges only the directories on its manifest, and `ops` was not on it. Thirty-five tracked files — every supervisor, every pool probe, the chain runner, the state reset tool — existed in the repository and would never arrive in the runtime that actually executes them. The crawl supervisors are frozen baseline behaviour (contract item 42b), so a runtime copy that drifts from the repository's copy runs behaviour the baseline does not describe. `ops` is on the manifest now, and the manifest itself is frozen: it is the mechanism that gives the upstream repository, the plugin runtime and a working copy the same bytes for every tracked file, so a change to it would change what "the same build" means.
- **The sync overwrote the script it was running.** `scripts/` is on the merge manifest, so a sync rewrites `scripts/sync-from-repo.sh` while that script is still executing it. bash reads a running script incrementally, and the read offset does not move when the file's length changes, so the next segment was parsed from the wrong place and the run died on `syntax error near unexpected token '('` — after the merge, before the verify. It only showed up once the script itself changed, which is exactly when it was needed. The sync now runs from a temporary copy of itself, so the file on disk may change underneath it.

Added

- **`scripts/check_sync_manifest.py` fails CI when a tracked file is not covered by the manifest.** It runs where the tracked set is authoritative — the upstream checkout — and checks that every file `git ls-files` reports is either a named root file or inside a merged directory, that every manifest entry exists and is not empty, and that the private state (`.env`, `.secrets`, `seen_jds.jsonl`, `local_tools`, the Mavis-specific files) is on the preserve list rather than on the travel list. This is the check that would have caught v1.8.2. It recognises the upstream checkout by its origin remote and reports that it does not apply anywhere else: the plugin runtime and a working copy have their own tracked files, and judging those against the manifest would report files that are deliberately not carried.
- **`tests/test_plugin_sync_manifest_v183.py` (12 tests)** guards the same property from inside the test suite, and it reads the tree next to the manifest rather than git, because the same tree exists in three places with three different git histories: `ops` is on the merge manifest, every frozen supervisor travels with it, every merged directory exists and is not empty, every top-level directory of the tree is covered by the manifest, private state is never carried and always preserved, and the guard skips a checkout that is not the upstream one.

Changed

- **The stale script copies are gone from the runtime directory.** There were 33 of them, unversioned and with hard-coded paths, byte-different from the repository's copies only in how they resolved their paths. Two copies of a supervisor that can both be launched is one too many, and the repository's copy is the one that is version-controlled. The runtime directory now holds logs and state only.
- `RULES.md` gains a section on how the three placements are kept identical, including the two mistakes that cost this release: a tracked directory missing from the merge manifest, and comparing a placement against its own file list instead of the upstream one.

Unchanged

- The engine's behaviour is untouched. The contract gains three items (46–48) about how the sync carries the frozen supervisors and where a crawl is launched from; nothing about how a crawl fetches, paces, deduplicates or writes changed. The pacing budgets, the page spans, the parallel detail fetches and the Sheet write path are all as they were in v1.8.2.

## v1.8.2 — 2026-11-25

The operational half of the crawler was living on one machine and nowhere else.

Added

- **`ops/` — the crawl supervisors and the tooling around them are now in the repository.** 33 scripts that used to exist only in `~/.minimax-agent/projects/.runs/`: the SG and TW chunked supervisors, the JobStreet keyword-axis supervisor, the chain runner, the state reset tool, the China runners, and the pool-depth probes. They encode the things a live run taught us — the page-span chunk plans, the `tw_paused.flag` switch, the state-file key format, the "pool exhausted is an end, not a gap" rule, and how each source's pool depth was measured — and none of it was version-controlled. Losing one of those files meant re-deriving it from logs.
- Every path in those scripts is now resolved from the environment (`JOBS_SCRAPER_DIR`, `JOBS_SCRAPER_RUNTIME_DIR`, `UPSTREAM_DIR`, `SHEET_ID`) with the previous location as the default, so the same script runs on another machine. The two China runners used to carry a hard-coded spreadsheet ID; they now fail closed when `SHEET_ID` is unset, which is the same rule the engine itself follows.
- Scripts call each other relative to their own directory, so the repository copy is the single source of truth and the runtime directory holds only state.
- `ops/README.md` documents the layout, the state-file convention and the trap it carries, how to launch a crawl through `launchctl`, how to measure a pool, and how to back up the private state without putting it on GitHub.

Unchanged

- The engine's behaviour is untouched by this release: the contract, the pacing budgets, the page spans, the parallel detail fetches and the Sheet write path are all as they were in v1.8.1. The four crawl supervisors are added to the frozen baseline, because the contract already describes how a supervisor treats a span beyond the pool.

## v1.8.1 — 2026-11-25

The 104 budget was never applied to the requests that mattered.

Fixed

- **The 104 list was paced at the global 3–10s, not at the 1.0–2.0s v1.8.0 promised.** 104's list paging runs inside the adapter's own `ThreadPoolExecutor` workers, and a fresh thread in Python 3.11 starts with a clean context — so the source the engine had pinned in the main thread was invisible in the worker, and every 104 list page fell back to the global budget. A live TW 7d run showed it: list sleeps of 4.8s, 6.8s, 9.4s, 4.9s and 3.2s, while the detail fetches in the same run slept 1.5–1.7s, the 104 value. The contract already required a worker to set the source itself (items 36 and 44); the implementation did not, and v1.8.0's own test missed it because it stubbed `crawl_list` out entirely and therefore read the main thread's context variable. The pacing hook is now invoked inside the worker thread, which is where the source is pinned.
- **The 104 budget is chosen by aggregate request rate, not by the gap between two requests.** 104's list API is sensitive to how many requests are in flight at once: eight keyword workers at 1.0–2.0s each is an aggregate 2.1 req/s and was answered with 403 at the start of a run (recovered by the 30/60/90s ladder), while a single worker at 1.0–2.0s is an aggregate 0.5–1.0 req/s and walked 50 pages — 1,010 postings — with zero failures. One keyword in flight now uses the 104 budget; several keywords in flight keep the global budget, which is the aggregate rate 104 has always been crawled at.

Acceptance

- `tests/test_sleep_worker_propagation_v181.py` (6 tests) walks the adapter's real worker path: the pacing happens off the main thread, the source is visible there, a single keyword lands inside the 104 budget and not inside the global one, and a parallel crawl lands in the global budget. Reverting the engine fix fails three of them.
- 936 passed, freeze v13, hygiene PASS, ruff/mypy clean.

## v1.8.0 — 2026-11-24

The crawl was not slow because the network was slow. It was slow because the
engine waited.

Fixed

- **80% of a run's wall time was `time.sleep()`.** Measured 2026-11-24 against the live APIs: a JobStreet list page costs 0.80s of network time, a JobStreet JD 0.29s, a LinkedIn list page 0.92s — and the engine then slept 3–10s (6.5s on average) after *every* request. The sg 30d JobStreet phase made 1,750 requests over 3h51m: 80% sleeping, 6% on the wire, 14% on process start-up and the sheet read.
- **Every source now owns its pacing, and the adapter is where that budget lives.** JobStreet paces at 0.5–1.0s — its public list API and GraphQL endpoint survived a stress test of 0.5s between requests across 200 requests with zero failures, and 10 req/s with zero failures. LinkedIn paces at 1.5–3.0s: the Guest API really does return 429, so it stays conservative and keeps its 30/60/90s retry ladder. 104 paces at 1.0–2.0s: its detail API survived 59 requests at 0.3s apart with zero failures, and its list API — which had **no** general pacing at all, so eight keyword workers hit it without a pause — was answered with 403 after one dense burst. Cake stays at 3–10s, because Cake answers 429 at 2–5s. A budget can be overridden from the environment (`JOBS_SCRAPER_<SOURCE>_SLEEP_MIN` / `_MAX`) without touching the code.
- **Chunks crawl a page span instead of re-crawling the whole prefix.** The supervisors used the cumulative style — chunk *N* crawled pages 1..*N* — so every earlier page was fetched again on every chunk. The 30d JobStreet run made 2,179 page fetches for a pool that needs ~406: a 5.4× redundancy, and 7.5× for `product lead` alone (1,260 fetches for 169 pages). LinkedIn paid 3.55× the same way. A chunk now owns a span (`--start-page` / `--max-pages`) and crawls only its own pages; cross-chunk de-duplication is unaffected, because the seen file and the pre-detail dedup against the target tab both survive across processes.
- **Detail fetches run in a thread pool.** They were a sequential `for` loop, so every detail's sleep stacked into the wall time. The pool defaults to 3 workers (like Cake's) and can be set with `JOBS_SCRAPER_JD_WORKERS`. The threads do network I/O and nothing else — the seen file, the counters and the output order stay in the main thread, so `seen_jds.jsonl` cannot interleave and the Sheet's row order does not change.
- A span beyond the pool returns no data, and that is an end rather than a gap: the supervisor records it as "pool exhausted" instead of retrying it or reporting a coverage hole.
- The 104 adapter honours a page span as well, and it paces its list pages, not only its details.

Acceptance

- `tests/test_sleep_budget_v180.py` (12 tests) pins the per-source defaults, the environment override, the fallback on a malformed or inverted range, and that the engine's sleep follows the source being crawled.
- `tests/test_page_range_chunks_v180.py` (12 tests) pins that a span touches only its own pages, that consecutive spans cover every page exactly once, that the cumulative style demonstrably re-crawls, and that the soft stop still fires at the pool end.
- `tests/test_jd_parallel_v180.py` (11 tests) pins that the workers really overlap, that a single worker stays sequential, that the seen file is only written from the main thread, and that the output order matches the input order.
- 922 passed, freeze v12, hygiene PASS, ruff/mypy clean.

## v1.7.0 — 2026-11-24

A Sheet write never overwrites a row that holds data.

Fixed

- **415 collected rows were destroyed by the sg 14d run.** The write start was always "the first blank row in the sheet", and the run wrote its rows from there. The sheet carries a hole in the middle when a previous run was killed after writing part of a batch, and a write of 159 rows into a one-row hole overwrites the 158 rows of data below it. On 2026-11-24 that is exactly what happened: the LinkedIn 100-page chunk landed in a hole at row 2860, and the JobStreet chunks that followed landed at 3019 and overwrote rows that were already there — 415 rows of collected jobs gone.
- The destroyed jobs then cost more than the rows: they were no longer in the sheet, so the pre-detail dedup stopped skipping them and the next run fetched their JDs again for nothing.
- The write start is now resolved once the number of rows is known. A hole is used only when the whole write fits into blank rows; otherwise the run appends at the end. A hole that fits is still filled, so the normal case is unchanged, and a write can never destroy a row that holds data.

Acceptance

- `tests/test_sheet_write_start_v170.py` (8 tests) pins that a one-row hole is still filled when one row is written, that a hole too small for the write falls back to appending, that a run of blank rows is used only when it fits, that a hole at the tail is used, and that the key collection is unaffected by a hole.
- The write path resolves the start inside `push_to_sheet`, so the subprocess worker (which calls the same function) is covered too.

## v1.6.9 — 2026-11-24

The 104 source talks to 104 the way a browser does — or it talks to nobody.

Fixed

- **104's jobs search API was answering 403 and nobody noticed.** The homepage returned 200, but `/jobs/search/api/jobs` returned a block page for every request. Two things were missing: the `sec-fetch-dest` / `sec-fetch-mode` / `sec-fetch-site` header group (a browser's XHR always sends them and 104's bot protection looks at them), and the shared proxy resolution — a direct request from this machine is refused as well, the proxy is not. The adapter now sends both, together with `x-requested-with: XMLHttpRequest` and `Origin`.
- The 104 list and detail fetches now pass `proxies=resolve_proxies()`, so the 104 adapter obeys the same single resolver as LinkedIn, JobStreet and Cake. It has no source-specific proxy variable of its own.
- The symptom was the dangerous kind: an empty crawl, not an error. `無資料，結束` with exit 0 looked like "Taiwan has no product jobs this week". It did not — the request never reached the API.

Acceptance

- `tests/test_onezerofour_headers_proxy.py` (7 tests) pins the three `sec-fetch-*` headers, `x-requested-with` and `Origin`, that the detail request keeps its own referer, that the list and detail fetches pass the resolved proxy, that no proxy configured means a direct connection, and that the adapter reads no proxy variable of its own.
- Verified against the live API: the list page returns 22 postings and the detail API returns the full job description.

## v1.6.8 — 2026-11-23

A five-keyword crawl that crawled one keyword.

Fixed

- **Every JobStreet keyword now runs to the end of its own pool.** The list API takes one keyword per request, so the crawl runs the keyword set one after another and de-duplicates by `job_id` across them — but the soft stop that ended a keyword counted the postings that were new to the *whole crawl*. After the first keyword had filled the shared `seen` set, every later keyword saw almost nothing "new" on its first page and stopped there: four of the five keywords were abandoned on page 1, and the 7d run produced ~250 postings where the API's own totals promise ~2,600. The signal now measures the postings that are new to *that keyword*, so each keyword pages to the end of its own results, while a posting two keywords both match is still returned once.
- **The page budget follows the largest keyword.** Once every keyword crawls its own pool, a budget sized for the first keyword truncates the others. The budgets are re-pinned to the largest pool the API reports (Singapore, 2026-11-23: `product manager` 520, `product director` 382, `director of product` 394, `head of product` 184, `product lead` 1109 for 7d): `1h` 20 pages, `24h` 20, `3d` 40, `7d` 73, `14d` 120, `21d` 168, `30d` 220. v1.6.7's `1h` / `24h` / `3d` budgets were below even that, so they are raised together — otherwise the soft-stop fix would only trade one kind of truncation for another.
- **A failed keyword no longer costs the whole run.** A keyword that exhausted its retries ended the entire crawl, discarding the other keywords' postings. Per-keyword crawling multiplies the request count by five, so a single failure aborting everything is a regression the change itself introduces; the failure now ends that keyword only, and stays visible — the `FAIL` line is still printed, and the crawl ends with a summary of which keywords failed.

Cost

- JobStreet list requests multiply by about five (each keyword now pages to its own pool), and the unique postings multiply by about seven — the 7d run is expected to yield roughly 1,800 postings instead of ~250. The JD fetch is one request per unique posting, so the run gets longer in proportion. The list API tolerates the request rate (measured: 200 requests at 0.5s pacing, zero failures).

Acceptance

- `tests/test_jobstreet_per_keyword_v168.py` (8 tests) pins the per-keyword soft stop (a later keyword is not stopped by an earlier one, a keyword with a nearly empty page stops there, a keyword runs to its own pool end), the unchanged cross-keyword de-duplication, the failure isolation, and the budgets (they cover the largest measured pool, and no budget shrank). The three behavioural tests fail against the v1.6.7 adapter.
- The behaviour-equivalence freeze moves to `freeze_version 13` with a new keyword-coverage invariant section.

## v1.6.7 — 2026-11-23

Two budgets that were guesses, and a 400 that was retried for three minutes.

Fixed

- **The budgets now cover Singapore, not just Shanghai.** v1.6.6 pinned the LinkedIn page budgets to Shanghai's pool depths. Singapore's pools are deeper for every long range — 7d holds about 600 postings against Shanghai's 400 — so v1.6.6's budgets still truncated a Singapore run. The budgets are now pinned to the deepest measured pool per range across both cities: `1h` 8 pages, `24h` 15, `3d` 35, `7d` 80, and 100 for `14d`/`21d`/`30d` — where 100 is the Guest API's own pagination ceiling rather than a guess.
- **JobStreet's budgets were never measured at all.** The table carried a comment predicting ~600 unique postings for 7d; the actual result was ~250, because the five keywords share one `seen` set and the 50% soft-stop abandons four of them on their first page. The API states its own totals, and they are much larger than the budgets: 7d's largest keyword matches 955 postings, 14d's 1670, 30d's 3251 — against budgets of 15, 30 and 25 pages. The budgets are now sized for the largest keyword's pool plus headroom.
- **A non-429 4xx on a LinkedIn list page no longer burns the retry ladder.** The adapter's own docstring — and the frozen contract — say a 4xx other than 429 is a caller bug and is raised without retrying. The code did the opposite: `raise_for_status()` raised inside the `try`, the broad `except Exception` caught it, and the page was retried four times (30+60+90s) before the crawl gave up. It now raises `FatalListPageError` immediately, exactly like the JobStreet adapter.
- **The Guest API's pagination ceiling is an end, not a failure.** `start=1000` answers HTTP 400 rather than an empty page (measured: `start=990` → 200 with an empty body, `start=1000` → 400). A crawl that reached it aborted the whole chunk, and the supervisor read the FAIL as a coverage gap. It is now recognised as "there is nothing more to page", so the crawl ends with what it collected.

Acceptance

- `tests/test_crawl_budget_v167.py` (11 tests) pins every LinkedIn budget to its measured pool, every JobStreet budget to the API's own totals, that no budget shrank, that the time filters are unchanged, that a non-429 4xx is not retried, that a 429 still is, and that a crawl reaching the pagination ceiling ends with what it collected and without a FAIL.
- The behaviour-equivalence freeze moves to `freeze_version 12` with a new pagination-ceiling invariant section.

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
