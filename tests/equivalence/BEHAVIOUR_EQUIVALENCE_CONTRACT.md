# v1.4.0 Behaviour Equivalence Contract

This gate protects the restored five-source public source contract.

The harness file names (`test_v130_equivalence.py`, `v130_golden.json`) are kept because CI pins
that path; the frozen baseline asserted below is **v1.4.0**.

## Active-source invariants

1. The CLI accepts exactly five active sources: `linkedin`, `jobstreet`, `cake`, `104`, `onezerofour`.
2. `jora` is retired from active sources (the site closed) and is rejected by the CLI as a source
   choice; unknown sources are rejected the same way.
3. Every active source's URL building, list parsing, JD fetch, and crawl dispatch lives in
   `sg_product_jobs.py` — the single source of truth.
4. The removed `jobs_scraper/sources/` adapter package must not exist and must not be imported
   again by a refactor.
5. LinkedIn Guest API list URL construction, list parsing, JD URL construction, and JD parsing
   remain stable.

## Historical-data compatibility invariants

6. Existing Jora and JobStreet Sheet rows remain parseable for audit/dedup only.
7. The Jora read-only dedup helpers (`JORA_BASE`, `build_e_formula("jora", ...)`,
   `parse_sheet_row_to_key`, job-id source inference) remain available; the Jora *network*
   adapters stay absent.
8. Existing source-aware cache keys remain readable.
9. Historical compatibility must never be used to authorize a fresh retired-source network request.

## Shared behavior invariants

10. Title filtering stays skip filter v8.5 (`SKIP.md` is the semantics authority); work-mode
    detection, visa-signal detection, and machine-summary parsing remain stable.
11. The MCP / tracker layer stays LinkedIn-only: its source enum, source labels, and region
    policies are unchanged, and it fails closed for every non-LinkedIn source.
12. Tracker schema and write-safety contracts are unchanged.

Any future source expansion or retirement is an explicit public-contract change and requires a new
authorized equivalence baseline.
