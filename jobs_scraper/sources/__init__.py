"""Per-source adapters.

Each module here owns one source's public API surface: URL construction, list
parsing, and JD fetching. The adapters hold no global state — the HTTP session
and the sleep function are injected by the caller — so every one of them can be
exercised without touching the network.

`sg_product_jobs.py` keeps the public function names as thin wrappers and owns
the orchestration: the title skip filter, dedup, Sheet writes, and the CLI.
"""

from __future__ import annotations

import os

__all__ = ["cake", "jobstreet", "linkedin", "onezerofour", "resolve_proxies"]


def resolve_proxies() -> dict[str, str] | None:
    """從環境變數解析要用的 proxy, 給所有 source 共用。

    優先順序:
      1) JOBS_SCRAPER_PROXY — 專給爬蟲路徑用, 不影響 Google Sheet 的連線
      2) HTTPS_PROXY / HTTP_PROXY / ALL_PROXY — 標準慣例, requests 與 curl_cffi 都認

    沒設就回 None(直連)。回傳值可直接餵給 curl_cffi 的 `proxies=`。

    2026-11-19: LinkedIn 的 Guest API 開始對直連回 451(Unavailable For Legal
    Reasons) —— 在某些網路區段是整段被擋, 走本地 proxy 就正常。curl_cffi 本身
    讀 HTTPS_PROXY env, 但把 proxy 解析集中到這裡, 才能用 JOBS_SCRAPER_PROXY
    單獨指定爬蟲走哪條線, 而不影響 Sheet 寫入要走的路徑。
    """
    proxy = (
        os.getenv("JOBS_SCRAPER_PROXY", "").strip()
        or os.getenv("HTTPS_PROXY", "").strip()
        or os.getenv("HTTP_PROXY", "").strip()
        or os.getenv("ALL_PROXY", "").strip()
    )
    if not proxy:
        return None
    if "://" not in proxy:
        proxy = f"http://{proxy}"
    return {"http": proxy, "https": proxy}
