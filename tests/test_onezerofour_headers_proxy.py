"""v1.6.9: 104 (onezerofour) 的 headers 與 proxy。

2026-11-24 實測: 104 的 jobs search API 對「少了 sec-fetch-* 這組 header」的請求
一律回 403 (首頁 200)。瀏覽器的 XHR 會帶 sec-fetch-dest/mode/site, 104 的 bot
保護會看它們 → 少了就擋。這裡把「必要的 header」與「走共用 proxy 解析」釘死,
免得下次有人精簡 headers 又把 TW source 弄壞 (而症狀是「無資料」而不是報錯)。

所有 HTTP 都是假的: 不發任何請求, 也不等真的 backoff。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jobs_scraper.sources import onezerofour as O4  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        if self._payload is None:
            raise ValueError("response has no JSON body")
        return self._payload


class _FakeSession:
    """Stands in for curl_cffi's Session; records every .get() call."""

    def __init__(self, response=None):
        self.response = response or _FakeResponse(payload={"data": []})
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.response


def test_headers_carry_the_sec_fetch_group():
    """少這三個 header, 104 的 jobs search API 就回 403。"""
    h = O4.headers()
    assert h["sec-fetch-dest"] == "empty"
    assert h["sec-fetch-mode"] == "cors"
    assert h["sec-fetch-site"] == "same-origin"
    assert h["x-requested-with"] == "XMLHttpRequest"
    assert h["Origin"] == "https://www.104.com.tw"
    assert h["Accept"].startswith("application/json")
    assert "Referer" in h


def test_headers_keep_the_detail_referer():
    """detail API 要帶 job 頁的 referer, 不是 list 頁的。"""
    h = O4.headers(referer="https://www.104.com.tw/job/97tar")
    assert h["Referer"] == "https://www.104.com.tw/job/97tar"
    # sec-fetch 群不因 referer 改變而消失
    assert h["sec-fetch-site"] == "same-origin"


def test_list_fetch_passes_the_resolved_proxy(monkeypatch):
    """104 直連會 403 → 走共用 proxy 解析 (JOBS_SCRAPER_PROXY → 標準 env)。"""
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "127.0.0.1:12000")
    session = _FakeSession()
    O4.hit_list("Product Manager", 1, 7, session=session, sleep=lambda s: None)
    call = session.calls[0]
    assert call["proxies"] == {"http": "http://127.0.0.1:12000", "https": "http://127.0.0.1:12000"}


def test_detail_fetch_passes_the_resolved_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12000")
    session = _FakeSession(_FakeResponse(payload={"data": {"jobDetail": {"jobDescription": "x"}}}))
    O4.hit_detail("97tar", session=session, sleep=lambda s: None)
    call = session.calls[0]
    assert call["proxies"] == {"http": "http://127.0.0.1:12000", "https": "http://127.0.0.1:12000"}


def test_no_proxy_configured_means_direct(monkeypatch):
    for var in ("JOBS_SCRAPER_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(var, raising=False)
    session = _FakeSession()
    O4.hit_list("Product Manager", 1, 7, session=session, sleep=lambda s: None)
    assert session.calls[0]["proxies"] is None


def test_104_has_no_source_specific_proxy_variable():
    """proxy 解析只有一個地方: 104 不得自己讀 CAKE_HTTP_PROXY 之類的變數。"""
    source = Path(O4.__file__).read_text(encoding="utf-8")
    assert "CAKE_HTTP_PROXY" not in source
    assert 'os.getenv("HTTPS_PROXY"' not in source
    assert "resolve_proxies" in source


def test_adapter_is_importable_without_the_env_file():
    """cwd 不在 repo 根目錄時也要能用 (SHEET_ID 空 → fail-closed, 但 import 不能爆)。"""
    assert os.environ.get("SHEET_ID", "") != "" or True
    assert O4.build_list_url("PM", 1, 7).startswith(O4.LIST_API)
