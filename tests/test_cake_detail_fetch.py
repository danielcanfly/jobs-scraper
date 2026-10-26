"""Characterization tests: Cake JD fetch + HTML-403 fallback.

``fetch_cake_jd`` first tries the public detail page and falls back to the
description already carried by the search response when the HTML is blocked
(403), is a Cloudflare "Just a moment..." interstitial, or is too short to be
a JD.

All HTTP is faked via ``sg_product_jobs._cc_session``; no request leaves the
process.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402

LONG_JD = (
    "<html><body><h1>Senior Product Manager</h1>"
    "<p>You will own the product roadmap for our platform.</p>"
    "<p>This role is based in Taipei and reports to the Head of Product.</p>"
    "</body></html>"
)


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise AssertionError("detail fetch must not parse JSON")


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {url}")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def _install(monkeypatch, responses):
    session = _FakeSession(responses)
    monkeypatch.setattr(M, "_cc_session", session)
    return session


def _job(**overrides):
    job = {
        "job_id": "senior-product-manager-1234",
        "path": "senior-product-manager-1234",
        "page_path": "acme-corp",
        "title": "Senior Product Manager",
        "company": "Acme Corp",
        "location": "Taipei City",
        "description": "We are hiring a senior product manager to own the roadmap.\nApply now.",
        "source": "cake",
    }
    job.update(overrides)
    return job


def test_detail_url_requested_for_the_job(monkeypatch):
    session = _install(monkeypatch, [_FakeResponse(text=LONG_JD)])
    M.fetch_cake_jd(_job())
    assert session.calls[0]["url"] == ("https://www.cake.me/companies/acme-corp/jobs/senior-product-manager-1234")


def test_detail_request_uses_html_accept_header(monkeypatch):
    session = _install(monkeypatch, [_FakeResponse(text=LONG_JD)])
    M.fetch_cake_jd(_job())
    headers = session.calls[0]["headers"]
    assert headers["Accept"].startswith("text/html")
    assert headers["Referer"] == "https://www.cake.me/"


def test_detail_html_success(monkeypatch):
    _install(monkeypatch, [_FakeResponse(text=LONG_JD)])
    out = M.fetch_cake_jd(_job())
    assert out["jd_source"] == "detail_html"
    assert out["error"] is None
    assert "You will own the product roadmap" in out["jd_text"]
    assert out["jd_html"] == LONG_JD
    assert out["company"] == "Acme Corp"
    assert out["location"] == "Taipei City"
    assert out["title"] == "Senior Product Manager"


def test_detail_html_jd_lines_is_a_single_line(monkeypatch):
    """_cake_text_from_html collapses whitespace, so jd_lines has one entry."""
    _install(monkeypatch, [_FakeResponse(text=LONG_JD)])
    out = M.fetch_cake_jd(_job())
    assert out["jd_lines"] == [out["jd_text"]]
    assert len(out["jd_lines"]) == 1


def test_403_falls_back_to_the_list_description(monkeypatch):
    _install(monkeypatch, [_FakeResponse(status_code=403, text="<html>Forbidden</html>")])
    out = M.fetch_cake_jd(_job())
    assert out["jd_source"] == "list_description (HTTP 403)"
    assert out["jd_text"] == ("We are hiring a senior product manager to own the roadmap. Apply now.")
    assert out["jd_html"] is None
    assert out["error"] is None


def test_fallback_jd_lines_keep_original_line_breaks(monkeypatch):
    _install(monkeypatch, [_FakeResponse(status_code=403, text="nope")])
    out = M.fetch_cake_jd(_job())
    assert out["jd_lines"] == [
        "We are hiring a senior product manager to own the roadmap.",
        "Apply now.",
    ]


def test_cloudflare_interstitial_falls_back(monkeypatch):
    """A 200 that is really a Cloudflare challenge page falls back too."""
    challenge = "<html><body>Just a moment... Please enable JavaScript to continue.</body></html>"
    _install(monkeypatch, [_FakeResponse(status_code=200, text=challenge)])
    out = M.fetch_cake_jd(_job())
    assert out["jd_source"] == "list_description (HTTP 200)"
    assert out["jd_text"].startswith("We are hiring a senior product manager")


def test_short_html_falls_back(monkeypatch):
    """HTML shorter than 60 chars is not trusted as a JD."""
    _install(monkeypatch, [_FakeResponse(status_code=200, text="<html>tiny</html>")])
    out = M.fetch_cake_jd(_job())
    assert out["jd_source"] == "list_description (HTTP 200)"
    assert out["jd_text"].startswith("We are hiring a senior product manager")


def test_network_exception_falls_back(monkeypatch):
    _install(monkeypatch, [ConnectionError("boom")])
    out = M.fetch_cake_jd(_job())
    assert out["jd_source"] == "list_description (ConnectionError: boom)"
    assert out["jd_text"].startswith("We are hiring a senior product manager")


def test_no_description_and_blocked_html_returns_error(monkeypatch):
    _install(monkeypatch, [_FakeResponse(status_code=403, text="nope")])
    out = M.fetch_cake_jd(_job(description=""))
    assert out["jd_source"] == "none"
    assert out["jd_text"] is None
    assert out["jd_lines"] is None
    assert out["jd_html"] is None
    assert out["error"] == "HTTP 403"


def test_highlighted_description_is_used_when_description_missing(monkeypatch):
    _install(monkeypatch, [_FakeResponse(status_code=403, text="nope")])
    out = M.fetch_cake_jd(_job(description="", highlighted_description="Highlighted JD body from the search API."))
    assert out["jd_source"] == "list_description (HTTP 403)"
    assert out["jd_text"] == "Highlighted JD body from the search API."


def test_string_job_without_page_path_has_no_detail_url(monkeypatch):
    session = _install(monkeypatch, [])
    out = M.fetch_cake_jd("some/job/path")
    assert session.calls == []
    assert out["jd_source"] == "none"
    assert out["jd_text"] is None
    assert out["error"] == "no detail url"


def test_page_path_argument_overrides_the_job(monkeypatch):
    session = _install(monkeypatch, [_FakeResponse(text=LONG_JD)])
    M.fetch_cake_jd(_job(page_path=""), page_path="other-corp")
    assert session.calls[0]["url"] == ("https://www.cake.me/companies/other-corp/jobs/senior-product-manager-1234")


def test_job_id_is_used_when_path_is_missing(monkeypatch):
    session = _install(monkeypatch, [_FakeResponse(text=LONG_JD)])
    job = _job()
    del job["path"]
    M.fetch_cake_jd(job)
    assert session.calls[0]["url"].endswith("/jobs/senior-product-manager-1234")
