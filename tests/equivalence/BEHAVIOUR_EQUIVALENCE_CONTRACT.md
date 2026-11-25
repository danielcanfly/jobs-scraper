# v1.8.4 Behaviour Equivalence Contract

This gate protects the five-source public source contract and the per-source
adapter split.

The harness file names (`test_v130_equivalence.py`, `v130_golden.json`) are kept because CI pins
that path; the frozen baseline asserted inside the harness is the **v1.4.0** five-source restore,
which is the behaviour the split had to preserve.

## Active-source invariants

1. The CLI accepts exactly five active sources: `linkedin`, `jobstreet`, `cake`, `104`, `onezerofour`.
2. `jora` is retired from active sources (the site closed) and is rejected by the CLI as a source
   choice; unknown sources are rejected the same way.
3. Every active source's URL building, list parsing, JD fetch, and crawl dispatch lives in its own
   adapter under `jobs_scraper/sources/`. `sg_product_jobs.py` keeps the public names as thin
   wrappers over those adapters, so each behaviour has exactly one implementation. An AST check
   enforces that: a wrapper that grew its own body fails the gate.
4. LinkedIn Guest API list URL construction, list parsing, JD URL construction, and JD parsing
   remain stable.
5. The `jobs_scraper/sources/` package holds one adapter per active source. No adapter may exist
   for the retired `jora` source and nothing may import one.

## List-page retry invariants

6. Every source adapter's list fetch retries a transient failure instead of ending the crawl: a
   429, a 5xx, a connection error or a JSON decode error sleeps 30/60/90s and retries, for four
   attempts in total. Any other 4xx is raised without retrying.
7. A page that legitimately contains zero jobs is an answer, not a failure: it is never retried.
8. A run counts as successful only when the list crawl actually produced pages. The process exit
   code alone is not evidence that any job was collected — an empty crawl ends the run with exit
   code 0 by design, so acceptance has to look at the crawl itself.

## Historical-data compatibility invariants

9. Existing Jora and JobStreet Sheet rows remain parseable for audit/dedup only.
10. The Jora read-only dedup helpers (`JORA_BASE`, `build_e_formula("jora", ...)`,
    `parse_sheet_row_to_key`, job-id source inference) remain available; the Jora *network*
    adapters stay absent.
11. Existing source-aware cache keys remain readable.
12. Historical compatibility must never be used to authorize a fresh retired-source network request.

## Shared behavior invariants

13. Title filtering stays skip filter v8.5 (`SKIP.md` is the semantics authority); work-mode
    detection and machine-summary parsing remain stable. Visa-signal detection keeps its
    Singapore/Taiwan coverage, but no longer judges China-specific citizenship wording — see
    the China-region invariants below.
14. The MCP / tracker layer stays LinkedIn-only: its source enum, source labels, and region
    policies are shared with `region_policy.py`, and it fails closed for every non-LinkedIn
    source. The region set may grow a city, but only together with a tab-base rule that keeps
    the Sheet target unambiguous.
15. Tracker schema and write-safety contracts are unchanged.

## Sheet-write invariants

21. A write never overwrites a row that holds data. The write start is resolved once the number
    of rows is known: a blank row in the middle of the sheet is reused only when the whole write
    fits into blank rows, otherwise the run appends at the end. A hole that fits is still filled.
    The rule exists because the opposite happened: on 2026-11-24 a run that wrote 159 rows into a
    one-row hole destroyed 415 rows of collected jobs, and the destroyed jobs were then fetched
    again because they were no longer in the sheet to be de-duplicated against.

## Generated-worker invariants

16. Code that generates a Python worker must embed its arguments as Python literals, never as
    JSON. `json.dumps(None)` is the bare token `null`, an undefined name in Python: a worker
    built that way dies with `NameError` before it reaches Google, and silently costs the run
    the subprocess timeout guard that protects the Sheet write.
17. A generated worker must not carry the jobs payload in its source. The payload travels in a
    separate JSON file the worker reads; a source that embeds it grows to megabytes and makes
    CPython pull the whole literal through its tokenizer before the write can start, which is a
    memory spike on a machine whose free-page count is already in the tens of megabytes.

## Egress invariants

18. Outbound proxy resolution lives in one place, `jobs_scraper.sources.resolve_proxies()`, and
    every adapter that talks to a third party uses it: `JOBS_SCRAPER_PROXY` first, then the
    standard `HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY`, and nothing set means a direct
    connection. A source must not reach for a proxy variable of its own — one resolver, one
    priority order, and the doctor reports exactly what the crawlers will use.
19. A proxy that is configured but dead fails every source at once. The doctor therefore probes
    the configured proxy and reports it, rather than letting the failure surface as an empty
    crawl much later.
20. Every adapter that talks to a third party sends the request the way a browser would. The
    104 adapter is the case in point: without the `sec-fetch-dest` / `sec-fetch-mode` /
    `sec-fetch-site` group (plus `x-requested-with` and `Origin`) the 104 jobs search API
    answers 403 while its homepage answers 200 — the source dies quietly as "no jobs", not as
    an error. A source-specific bot-protection requirement is part of the source's contract and
    must not be trimmed away; a source that is silently empty is worse than one that fails.

## China-region invariants

20. China is three crawlable places, not one: `Shanghai` (the `China` region), `Hangzhou` and
    `Shenzhen` (their own regions). Each city has a verified LinkedIn geoId in the LinkedIn
    adapter's preset table, and `--location <city>` resolves to exactly that geoId.
21. The two city regions write into the China sheet: a region resolves its tab through a
    tab-base rule, so `Hangzhou` and `Shenzhen` both land on `China-Raw` / `China-Selected`.
    The expected-tab list is de-duplicated, because two regions sharing a tab must not make the
    initializer create that tab twice.
22. The city regions are opt-in: the default region set stays `SG` / `TW` / `China`.
23. A China posting carries no visa judgement. China-specific citizenship wording (`Chinese
    citizens only`, `PRC nationals only`, `僅限中國公民`, `必須為中國公民`, `上海戶口優先`,
    `中國人優先`) produces no signal at all, because a Taiwan resident can take a permit into
    mainland China. The generic coverage stays: a Singapore or Taiwan posting that requires any
    citizenship — including `must be a Chinese citizen` — is still a hard blocker, and the
    Singapore-only gate on the Sheet's visa column is unchanged.

## LinkedIn resilience invariants

24. A legitimately empty list page is zero jobs, never an exception. LinkedIn answers "no results"
    with a 26-byte body that yields no parseable root; the list parser must return an empty list for
    it, so the crawl's empty-streak rule decides the results are exhausted and the next page is
    still crawled. An empty page is never retried — invariant 7 stays in force.
25. The LinkedIn JD fetch uses the same transient-failure ladder as the list fetch: a 429, a 5xx or
    a connection error sleeps 30/60/90s and retries, for four attempts in total; any other 4xx is
    not retried. A JD that never arrives must not make the posting disappear from the Sheet, so the
    ladder is part of the write contract rather than an optimisation.

## Crawl-budget invariants

26. A range's page budget must cover the pool that range actually has, in **every** known city, not
    only the one it was measured in first. The budget is a ceiling, not a target: `crawl_list` ends a
    crawl after two consecutive pages with no new posting, so a city with a small pool stops early and
    a wider budget costs it nothing. A budget below the pool size truncates the crawl silently — the
    run reports success and the postings past the budget are never seen. The LinkedIn budgets are
    pinned to the deepest measured pool per range (Shanghai geoId 107388191 on 2026-11-22, Singapore
    geoId 102454443 on 2026-11-23): 1h 8 pages, 24h 15, 3d 35, 7d 80, and 100 for 14d/21d/30d.
27. The JobStreet budgets are pinned to the totals the JobStreet API states for itself (Singapore,
    2026-11-23), sized for the largest keyword's pool plus headroom: 1h 20 pages, 24h 20, 3d 40, 7d 73,
    14d 120, 21d 168, 30d 220. The JobStreet `daterange` parameter takes a number of days, mapped
    through `JOBSTREET_TPR` — never the CLI range name.
28. The time filter of every range is unchanged (`r3600`, `r86400`, `r259200`, `r604800`, `r1209600`,
    `r1814400`, `r2592000`); only the budget moves. An explicit `--max-pages` still overrides the
    default, and no budget ever shrinks.

## Pagination-ceiling invariants

29. The Guest API refuses to paginate past `start=1000`: it answers HTTP 400 rather than an empty
    page. A budget beyond 100 pages buys nothing, and a crawl that asks for an unreachable page ends
    with what it collected instead of aborting — the ceiling is an end, not a failure, so a supervisor
    never reads it as a coverage gap.
30. A non-429 4xx on a LinkedIn list page is raised immediately. The retry ladder is for transient
    failures (429, 5xx, connection error); a 4xx that is not a rate limit is a caller bug, and
    retrying it only burns the backoff ladder. The LinkedIn adapter raises `FatalListPageError` for
    it, exactly as the JobStreet adapter does.

## Keyword-coverage invariants

33. Every JobStreet keyword is crawled to the end of its own pool. The soft stop that ends a keyword
    measures the postings that are new to **that keyword**, never the postings that are new to the whole
    crawl: the five keywords share one `seen` set, and a signal measured against that set stops every
    keyword after the first one on its first page — a five-keyword crawl that crawls one keyword, and a
    seven-day run that yields ~250 postings where the API's own totals promise ~2,600. The shared set
    decides only what is returned: a posting two keywords both match is still returned once.
34. The JobStreet page budget is sized for the largest keyword's pool plus headroom, because every
    keyword now pages to its own pool end: 1h 20 pages, 24h 20, 3d 40, 7d 73, 14d 120, 21d 168, 30d 220
    (Singapore, 2026-11-23). A keyword that exhausts its retries ends that keyword only — the failure
    stays visible (the `FAIL` line, and a summary of the failed keywords) while the other keywords'
    postings are not discarded with it. Per-keyword crawling multiplies the request count by about five,
    so a single failure aborting everything would be a regression the change itself introduces.

## Sheet-target invariants

31. The pre-detail dedup reads the tab the run is about to write to. The target gid is resolved with
    the same precedence the writer uses — explicit `--gid`, then the `#gid=` inside `--to-sheet`,
    then the source-label mapping — and it is threaded into the loader, into the generated worker and
    into `main()`. A label→gid table alone is not a target: "LinkedIn / Minimax" points at SG-Raw,
    so a China run compared its postings against Singapore's tab and paid for a JD fetch round that
    the writer was going to discard.
32. With no target given, the label→gid mapping still applies, so the Singapore and Taiwan flows
    behave exactly as before. An explicit target is authoritative and does not require a known label.

Any future source expansion or retirement is an explicit public-contract change and requires a new
authorized equivalence baseline.

## Pacing invariants (v1.8.0)

35. Every source owns its own request pacing, and the adapter is where that budget lives: the
    JobStreet adapter paces at 0.5–1.0s, the LinkedIn adapter at 1.5–3.0s, the 104 adapter at
    1.0–2.0s, Cake stays at 3–10s.
    Measured 2026-11-24: the pure network time of a JobStreet list page is 0.80s, of a JobStreet
    JD 0.29s, of a LinkedIn list page 0.92s — while the old 3–10s sleep between every request made
    80% of a run's wall time waiting. A shared budget across sources with very different bot
    protection is over-conservative for the tolerant ones.
35a. The 104 adapter paces too, and it paces its list pages as well as its details. 104's list API
    had no general pacing at all — only a retry backoff — so eight keyword workers hit it without a
    pause between pages; a dense burst was answered with 403 (measured 2026-11-24: eight concurrent
    requests and ten back-to-back requests both answered 200, but a burst that followed a detail run
    answered 403). Its detail API tolerates far more (59 requests at 0.3s apart, zero failures), so
    the 104 budget is 1.0–2.0s: four times faster than the global budget, still conservative.
35b. The 104 list pacing is chosen by **aggregate request rate**, not by the gap between one
    request and the next. 104's list API is sensitive to how many requests are in flight at once:
    eight keyword workers at 1.0–2.0s each is an aggregate 2.1 req/s and was answered with 403 at
    the start of a run, while a single worker at 1.0–2.0s is an aggregate 0.5–1.0 req/s and walked
    50 pages (1,010 postings) with zero failures. So one keyword in flight uses the 104 budget
    (1.0–2.0s) and several keywords in flight keep the global budget (3–10s, an aggregate ~1.2
    req/s, the rate 104 has always been crawled at). The pacing hook is invoked inside the adapter's
    own worker thread, so that is where the source is pinned — a context variable set in the main
    thread is not visible in a worker, and the 104 list budget silently fell back to the global one
    for an entire release before this was caught by a live run.
36. The engine keeps **one** sleep injection point, `human_sleep`, and the source being crawled
    selects the range through a context variable. A test that replaces `human_sleep` therefore
    replaces every source's pacing, and a worker thread has to set the source itself — a fresh
    thread starts with a clean context.
37. A source's budget can be overridden from the environment
    (`JOBS_SCRAPER_<SOURCE>_SLEEP_MIN` / `_MAX`) without touching the code. A malformed value falls
    back to the default and an inverted range is swapped, never rejected.
38. The retry ladders are unchanged by the pacing change: JobStreet and LinkedIn still retry a
    transient 429/5xx/connection/JSON failure with 30/60/90s and still raise a non-429 4xx
    immediately. The lower per-request budget is a pacing change, not a retry change.

## Page-range invariants (v1.8.0)

39. A crawl may be given a page **span** (`--start-page` / `--max-pages`), and a chunk that owns a
    span crawls only its own pages. The cumulative style — chunk *N* crawls pages 1..*N* — re-crawled
    every earlier page on every chunk: 2,179 page fetches for a 30d JobStreet pool that needs ~406,
    a 5.4× redundancy (7.5× for one keyword), and 355 for a 100-page LinkedIn pool, a 3.55× one.
40. Consecutive spans cover every page exactly once: no page is fetched twice and none is skipped.
    Cross-chunk de-duplication does not depend on the span — it is the seen file plus the
    pre-detail dedup against the target tab, both of which survive across processes.
41. `--start-page` defaults to 1, so a crawl without a span behaves exactly as before.
42. A span that lies beyond the pool returns no data. That is an end, not a gap: the supervisor
    records it as "pool exhausted" rather than retrying it or reporting a coverage hole.
42a. The 104 adapter honours a span as well: its keyword worker crawls only its own pages, so a
    chunk that owns a span never re-crawls the prefix.
42b. The crawl supervisors live in the repository, under `ops/`, and are part of the frozen
    baseline. The rules above about how a supervisor treats a span beyond the pool, about
    which chunk keys the state file holds, and about a failed chunk not being recorded as
    done are the supervisors' behaviour, so the scripts that implement them are frozen with
    the rest of the baseline. A supervisor resolves its paths from the environment and never
    carries a spreadsheet id, a service-account identity or a private key: the repository's
    hygiene guard scans the whole tracked tree for exactly those, and the China runners fail
    closed when no spreadsheet id is configured.

## Parallel-detail invariants (v1.8.0)

43. Detail fetches run in a thread pool (`JOBS_SCRAPER_JD_WORKERS`, default 3). The threads do
    network I/O and nothing else: the seen file, the counters and the output list are written by the
    main thread after the pool drains, so the seen file cannot interleave and the output order
    still matches the input order. The Sheet's row order therefore does not change.
44. A worker sets the source's pacing context itself, because a fresh thread starts with a clean
    context and would otherwise fall back to the global budget.
45. A worker count of 1 keeps the fully sequential behaviour, and the detail fetch still reports a
    failure as a failed row instead of raising.

## Plugin-sync invariants (v1.8.3)

46. The plugin runtime receives the repository's `ops/` directory on every sync. The crawl
    supervisors in there are frozen baseline behaviour (item 42b), so a runtime that kept a
    private copy of them would run behaviour the baseline does not describe. `ops` is one of
    the merged directories in the sync manifest, and the manifest itself is frozen (item 47).
47. The sync manifest is part of the frozen baseline. It is the mechanism that gives the three
    placements — the upstream repository, the plugin runtime and a working copy — the same
    bytes for every tracked file, so a change to it would change what "the same build" means.
    It merges rather than replaces: a directory upstream owns is merged file by file, a file
    the local side owns alone is never deleted, and the Mavis-specific files and the private
    runtime state sit on an explicit preserve list that a sync never touches. The sync runs
    from a temporary copy of itself: it merges the repository's `scripts/` directory over its
    own location, and bash reads a running script incrementally, so a script that rewrites
    itself while it runs resumes at a byte offset that no longer matches the file and dies on
    a syntax error. The copy is what runs, so the file on disk may change underneath it.
    The guard that checks the manifest runs in the upstream checkout, where the tracked set is
    authoritative. The plugin runtime and a working copy have their own tracked files — the
    Mavis-specific ones and whatever is left on that machine — so the guard recognises a
    checkout that is not the upstream one and reports that it does not apply, rather than
    failing on a file set it was never meant to judge.
48. The sync carries the frozen supervisors but does not run them. A crawl is launched from
    the repository checkout, and the runtime directory holds only logs and state, so there is
    exactly one copy of a supervisor that can be launched.

## Working-copy sync invariants (v1.8.4)

49. The working copy is reached from the upstream checkout by
    `scripts/sync-working-copy.sh`, not by a hand-typed copy loop. The file list is the
    upstream checkout's tracked set — never the working copy's own `git ls-files`, because the
    working copy has its own repository and tracks whatever is left on that machine. The
    script merges: a file the working copy owns alone is never deleted, and the private state
    (`.env`, `.secrets`, `seen_jds.jsonl`, the JD caches) neither travels nor is touched. A
    file that differs from the upstream, or is missing from the working copy, is drift, and
    the check reports it instead of passing.

