# v1.6.5 Behaviour Equivalence Contract

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

Any future source expansion or retirement is an explicit public-contract change and requires a new
authorized equivalence baseline.
