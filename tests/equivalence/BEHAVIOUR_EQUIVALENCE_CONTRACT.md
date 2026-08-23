# v1.2.0 Behaviour Equivalence Contract

Baseline: annotated tag `v1.1.1`, dereferenced commit `8fbf32484418c2d5edd1fc1e0e451232515dadd8`, tree `f0ba649aa4d989fceffa51b14c49a1f4b7e311c4`.

This directory is the Phase A gate for the v1.2.0 architecture cleanup.

## Rule

No production architecture refactor may begin until deterministic characterization coverage for the externally observable v1.1.1 behaviour is green in CI.

The harness must freeze behaviour, not implementation structure. It may add fixtures, golden outputs, normalization helpers, test-only adapters, and CI/test wiring, but it must not change production scraping, parsing, Sheet, MCP, or Job Tracker semantics while Phase A is open.

## Frozen surfaces

The Phase A harness must cover, with deterministic local fixtures/mocks and no production Google Sheet writes:

1. LinkedIn list URL/query construction and detail endpoint construction.
2. Jora list URL/query construction.
3. JobStreet list API parameters and GraphQL JD request payload.
4. Source parsing and normalized job outputs from representative synthetic HTML/JSON fixtures.
5. Title filtering, including the Senior whitelist behaviour.
6. `(source, job_id)` dedup semantics.
7. Work-mode detection.
8. Visa/constraint detection semantics.
9. A:K scraper row generation and E-column formula semantics.
10. Google Sheet write-phase ordering: data phases precede intentional formula activation.
11. Machine-readable `JOBS_SCRAPER_SUMMARY=` contract.
12. Legacy MCP four-tool public contract.
13. v1.1 MCP five-tool public contract.
14. Job Tracker A:AA schema, region aliases/routing, and Raw/Selected naming contract.

## Equivalence principle

During later refactor phases, the same fixtures and expected observable outputs must pass unchanged. If a desired product behaviour change is discovered, record it separately; do not silently update golden expectations inside the architecture-refactor delta.

## Release gate

`v1.2.0` may not be qualified merely because legacy tests remain green. Final qualification must include an explicit behaviour-equivalence gate against the frozen v1.1.1 baseline in addition to normal regression, fresh-install, MCP, repository-hygiene, and later quality gates.
