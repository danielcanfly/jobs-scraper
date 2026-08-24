from __future__ import annotations

import inspect

import pytest

import jobs_scraper.sources.jora as JA
import sg_product_jobs as M


def test_jora_root_public_helpers_delegate_to_adapter():
    assert M.build_jora_list_url("7d", 3, "product manager", "Singapore") == JA.build_list_url(
        "7d", 3, "product manager", "Singapore"
    )
    assert M.parse_jora_list_page("<html></html>", "Singapore") == JA.parse_list_page(
        "<html></html>", location="Singapore"
    )


def test_jora_adapter_keeps_session_injection_boundary(monkeypatch):
    calls: list[tuple[str, dict]] = []

    class Response:
        status_code = 200
        text = "<main><h1>Senior Product Manager</h1><div><span>Acme</span><span>–</span><span>Singapore</span></div><div class='job-detail'><p>Build products</p></div></main>"

    class Session:
        def get(self, url: str, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr(M, "_cc_session", Session())
    observed = M.fetch_jora_jd("https://sg.jora.com/job/Senior-Product-Manager-3edbbb646574ed2a0a926fee537b0e7c")
    assert calls == [
        (
            "https://sg.jora.com/job/Senior-Product-Manager-3edbbb646574ed2a0a926fee537b0e7c",
            {"timeout": 20, "impersonate": "chrome"},
        )
    ]
    assert observed["jd_text"] == "Build products"
    assert observed["company"] == "Acme"
    assert observed["location"] == "Singapore"


def test_jora_crawl_adapter_accepts_injected_sleep(monkeypatch):
    sleeps: list[str] = []

    class Response:
        status_code = 200
        text = ""

    class Session:
        def get(self, url: str, **kwargs):
            return Response()

    observed = JA.crawl_list(
        Session(),
        "7d",
        1,
        tpr_map={"7d": "7d"},
        sleep_fn=lambda label: sleeps.append(label),
    )
    assert observed == []
    assert sleeps == []


def test_jora_root_does_not_own_adapter_implementation_after_b3b():
    # Root compatibility functions may delegate, but implementation details should
    # live in jobs_scraper.sources.jora once B3b is complete.
    source = inspect.getsource(M.build_jora_list_url)
    assert "jora_source.build_list_url" in source
