"""Regression tests for outbound proxy resolution across the source adapters.

2026-11-19: the LinkedIn Guest API started answering a direct request with
HTTP 451 ("Unavailable For Legal Reasons") on this machine, and the Google
Sheets API times out on a direct connection too. Both work through the local
proxy, so the crawl path needs a way to say "go this way" — without forcing a
proxy on users whose network does not need one.

The resolution lives in one shared helper, `jobs_scraper.sources.resolve_proxies`,
so every adapter agrees on the priority order and the doctor can report the
same thing the crawlers will actually use.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from jobs_scraper.sources import cake as _cake
from jobs_scraper.sources import linkedin as _linkedin
from jobs_scraper.sources import resolve_proxies

PROXY_KEYS = ("JOBS_SCRAPER_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "CAKE_HTTP_PROXY")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from "no proxy configured"."""
    for key in PROXY_KEYS:
        monkeypatch.delenv(key, raising=False)


def _load_doctor():
    """Import scripts/doctor.py by path — it is a script, not a package."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "doctor.py"
    spec = importlib.util.spec_from_file_location("jobs_scraper_doctor", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_no_proxy_configured_returns_none():
    assert resolve_proxies() is None


def test_jobs_scraper_proxy_wins_over_the_standard_variables(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "http://127.0.0.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    assert resolve_proxies() == {"http": "http://127.0.0.1:9999", "https": "http://127.0.0.1:9999"}


@pytest.mark.parametrize("key", ["HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"])
def test_standard_proxy_variables_are_honoured(monkeypatch, key):
    monkeypatch.setenv(key, "http://127.0.0.1:7777")
    assert resolve_proxies() == {"http": "http://127.0.0.1:7777", "https": "http://127.0.0.1:7777"}


def test_a_bare_host_port_is_normalised_to_http():
    assert resolve_proxies.__doc__ is not None
    import os

    os.environ["HTTPS_PROXY"] = "127.0.0.1:12000"
    try:
        assert resolve_proxies() == {"http": "http://127.0.0.1:12000", "https": "http://127.0.0.1:12000"}
    finally:
        del os.environ["HTTPS_PROXY"]


def test_an_empty_variable_falls_through_to_the_next_one(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "   ")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:6666")
    assert resolve_proxies() == {"http": "http://127.0.0.1:6666", "https": "http://127.0.0.1:6666"}


def test_cake_keeps_its_own_variable_first(monkeypatch):
    monkeypatch.setenv("CAKE_HTTP_PROXY", "http://127.0.0.1:5555")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:4444")
    assert _cake.proxies() == {"http": "http://127.0.0.1:5555", "https": "http://127.0.0.1:5555"}


def test_cake_falls_back_to_the_shared_resolution(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "http://127.0.0.1:3333")
    assert _cake.proxies() == {"http": "http://127.0.0.1:3333", "https": "http://127.0.0.1:3333"}


class _FakeResponse:
    status_code = 200
    text = "<html>jobs</html>"

    def raise_for_status(self):
        return None


class _RecordingSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse()


def test_linkedin_list_fetch_passes_the_resolved_proxy(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "http://127.0.0.1:12000")
    session = _RecordingSession()
    page = _linkedin.fetch_list_page("r86400", 0, session=session, sleep=lambda _s: None)
    assert page == "<html>jobs</html>"
    assert session.calls[0]["proxies"] == {"http": "http://127.0.0.1:12000", "https": "http://127.0.0.1:12000"}


def test_linkedin_list_fetch_passes_no_proxy_when_none_is_configured():
    session = _RecordingSession()
    _linkedin.fetch_list_page("r86400", 0, session=session, sleep=lambda _s: None)
    assert session.calls[0]["proxies"] is None


def test_linkedin_jd_fetch_passes_the_resolved_proxy(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "http://127.0.0.1:12000")
    session = _RecordingSession()
    _linkedin.fetch_jd("12345", session=session)
    assert session.calls[0]["proxies"] == {"http": "http://127.0.0.1:12000", "https": "http://127.0.0.1:12000"}


def test_doctor_reports_a_direct_connection_when_no_proxy_is_set():
    doctor = _load_doctor()
    msg, tag = doctor.check_proxy()
    assert "直連" in msg
    assert tag == "WARN"


def test_doctor_reports_a_reachable_proxy_as_pass(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_PROXY", "http://127.0.0.1:9")
    doctor = _load_doctor()
    msg, tag = doctor.check_proxy()
    # Port 9 (discard) is closed here, so the check must fail loudly rather than
    # pretend a dead proxy is fine.
    assert "JOBS_SCRAPER_PROXY=http://127.0.0.1:9" in msg
    assert tag == "FAIL"
