# v1.6.0 Behaviour Equivalence Contract

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
    detection, visa-signal detection, and machine-summary parsing remain stable.
14. The MCP / tracker layer stays LinkedIn-only: its source enum, source labels, and region
    policies are unchanged, and it fails closed for every non-LinkedIn source.
15. Tracker schema and write-safety contracts are unchanged.

Any future source expansion or retirement is an explicit public-contract change and requires a new
authorized equivalence baseline.
