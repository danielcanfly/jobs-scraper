"""Per-source adapters.

Each module here owns one source's public API surface: URL construction, list
parsing, and JD fetching. The adapters hold no global state — the HTTP session
and the sleep function are injected by the caller — so every one of them can be
exercised without touching the network.

`sg_product_jobs.py` keeps the public function names as thin wrappers and owns
the orchestration: the title skip filter, dedup, Sheet writes, and the CLI.
"""

from __future__ import annotations

__all__ = ["cake", "jobstreet", "linkedin", "onezerofour"]
