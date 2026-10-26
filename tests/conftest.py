"""Shared test helpers for the jobs-scraper contract suite.

The scraper reads its configuration from the environment at import time, and
`sg_product_jobs` additionally calls `load_dotenv()` on import. That means a test
that imports the module picks up whatever the ambient `.env` happens to contain.

In a development checkout there is no `.env`, so "the default is empty" holds.
In the installed plugin runtime there *is* a `.env` with real Sheet settings, so
the same import returns real values and a default-value assertion would fail for
the wrong reason.

`clean_env_module` re-imports a module with the environment scrubbed, so a
default-value contract can be asserted in both environments. It is fail-safe:
the previous environment and the previously imported module are always restored.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from typing import Iterator

# Environment keys that carry Sheet / gid configuration.
_SCRUBBED_KEYS = (
    "SHEET_ID",
    "SHEET_GID",
    "SHEET_GID_OVERRIDE",
    "SG_RAW_GID",
    "TW_RAW_GID",
    "GSPREAD_SA_KEY_PATH",
)


@contextmanager
def clean_env_module(module_name: str, env: dict[str, str] | None = None) -> Iterator[object]:
    """Import `module_name` with a scrubbed environment, then restore everything.

    `PYTHON_DOTENV_DISABLED=1` stops `load_dotenv()` from re-populating the
    environment from the on-disk `.env` file, so the import sees exactly the
    environment this contextmanager set up.
    """
    saved = {k: os.environ.get(k) for k in (*_SCRUBBED_KEYS, "PYTHON_DOTENV_DISABLED")}
    for key in _SCRUBBED_KEYS:
        os.environ.pop(key, None)
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    if env:
        os.environ.update(env)

    # Keep a handle on whatever module object was already imported and put it
    # back afterwards. Other test modules hold a module-level reference
    # (`import sg_product_jobs as S`); popping the entry from sys.modules would
    # leave them pointing at a stale object while a second copy of the module
    # lives in sys.modules, and the two copies then diverge.
    previous = sys.modules.get(module_name)
    sys.modules.pop(module_name, None)
    try:
        yield importlib.import_module(module_name)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous
