# v1.3.0 Behaviour Equivalence Contract

This gate protects the intentionally narrowed LinkedIn-only public source contract.

## Active-source invariants

1. linkedin is the only accepted CLI/MCP crawl or sync source.
2. LinkedIn Guest API list URL construction and list parsing remain stable.
3. LinkedIn Guest API JD URL construction and JD parsing remain stable.
4. Retired sources (jora, jobstreet) fail closed before a fresh crawl/sync subprocess can run.
5. No Jora or JobStreet adapter module or active network wrapper may be present.

## Historical-data compatibility invariants

6. Existing Jora and JobStreet Sheet rows remain parseable for audit/dedup only.
7. Existing source-aware cache keys remain readable.
8. Historical compatibility must never be used to authorize a fresh retired-source network request.

## Shared behavior invariants

9. Title filtering, work-mode detection, visa-signal detection, and machine-summary parsing remain stable.
10. MCP tool sets remain unchanged except that source enums are exactly linkedin-only.
11. Region routing remains SG / TW / China for LinkedIn.
12. Tracker schema and write-safety contracts are unchanged.

Any future source expansion is an explicit public-contract change and requires a new authorized equivalence baseline.
