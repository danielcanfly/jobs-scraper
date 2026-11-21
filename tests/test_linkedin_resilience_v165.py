"""LinkedIn Guest API resilience (2026-11-21).

Two failures hit the China run on 2026-11-21, and both of them are generic —
they have nothing to do with China and would hit Singapore or Taiwan the same way.

**1. A legitimately empty list page crashed the whole crawl.**
LinkedIn's empty page is 26 bytes: ``<!DOCTYPE html>\\n\\n<!---->``. Scrapling
builds no root element for that body, so ``page.css(...)`` raised
``AttributeError: 'NoneType' object has no attribute 'xpath'`` — inside the
list parser, outside the crawl's own try/except. One empty page killed the
page loop, the chunk, and all three chunks of the Hangzhou run: zero rows
reached the Sheet, while the run reported a clean exit.

The fix treats a body with no root as **zero jobs**, so the crawl's own
empty-streak rule decides that the results are exhausted and moves on. An empty
page is a legitimate answer, so it is **not** retried — that stays true for the
list fetch, and this fix does not change it.

**2. A throttled JD fetch dropped the job silently.**
``fetch_jd`` gave up on the first HTTP 429. A job whose JD never arrived has no
JD text, and the Sheet writer skips such a row entirely — so a rate-limited
request did not fail the run, it just made a posting disappear (4 of the first
10 Shanghai jobs). The JD fetch now uses the same 30/60/90s ladder as the list
fetch: 429 / 5xx / connection errors are retried (four attempts), any other
4xx is still a caller bug and is not retried.

All HTTP is faked; no request leaves the process.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402
from jobs_scraper.sources import linkedin as LI  # noqa: E402

#: The 26-byte body LinkedIn returns for a page with no results.
EMPTY_GUEST_PAGE = "<!DOCTYPE html>\n\n<!---->  "

JD_HTML = '<div class="description__text"><p>Build products</p><li>Ship safely</li></div>'

CARD_HTML = """
<div class="base-card" data-entity-urn="urn:li:jobPosting:4430572342">
  <h3 class="base-search-card__title">Principal Product Manager</h3>
  <a class="hidden-nested-link">Acme AI</a>
  <span class="job-search-card__location">Singapore</span>
  <time datetime="2026-08-20">3 days ago</time>
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/4430572342"></a>
</div>
"""


class _FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    """Replays a scripted list of responses / exceptions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {url}")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


# ── 1. the empty list page ───────────────────────────────────────────────────


def test_empty_guest_page_parses_to_zero_jobs():
    """The body that used to raise must parse to zero jobs."""
    assert LI.parse_list_page(EMPTY_GUEST_PAGE) == []


def test_empty_string_parses_to_zero_jobs():
    assert LI.parse_list_page("") == []
    assert LI.parse_list_page("   \n  ") == []


def test_a_valid_page_still_parses_the_same_way():
    jobs = LI.parse_list_page(CARD_HTML)
    assert len(jobs) == 1
    assert jobs[0]["job_id"] == "4430572342"
    assert jobs[0]["title"] == "Principal Product Manager"
    assert jobs[0]["company"] == "Acme AI"
    assert jobs[0]["location"] == "Singapore"
    assert jobs[0]["source"] == "linkedin"


def test_crawl_list_keeps_going_after_an_empty_page(monkeypatch):
    """The bug that killed the Hangzhou run: an empty page ended the crawl."""
    session = _FakeSession(
        [
            _FakeResponse(200, EMPTY_GUEST_PAGE),
            _FakeResponse(200, CARD_HTML),
            _FakeResponse(200, EMPTY_GUEST_PAGE),
        ]
    )
    monkeypatch.setattr(M, "_cc_session", session)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)

    jobs = M.crawl_list("r604800", 3, location="Hangzhou", geo_id="101821877")

    # the empty page is skipped, the next page is still crawled
    assert [j["job_id"] for j in jobs] == ["4430572342"]
    assert len(session.calls) == 3


def test_an_empty_page_is_not_retried(monkeypatch):
    """An empty page is a legitimate answer — it must not burn a retry ladder."""
    session = _FakeSession([_FakeResponse(200, EMPTY_GUEST_PAGE)])
    monkeypatch.setattr(M, "_cc_session", session)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    slept: list[float] = []
    monkeypatch.setattr(M.time, "sleep", slept.append)

    M.crawl_list("r604800", 1, location="Hangzhou", geo_id="101821877")

    assert len(session.calls) == 1
    assert slept == []


# ── 2. the JD retry ladder ───────────────────────────────────────────────────


def test_jd_429_is_retried_then_succeeds():
    session = _FakeSession([_FakeResponse(429), _FakeResponse(200, JD_HTML)])
    slept: list[float] = []

    result = LI.fetch_jd("4430572342", session=session, sleep=slept.append)

    assert "Build products" in (result["jd_text"] or "")
    assert result["error"] is None
    assert len(session.calls) == 2
    assert slept == [30]


def test_jd_429_exhausts_the_ladder_and_reports_the_rate_limit():
    session = _FakeSession([_FakeResponse(429)] * 4)
    slept: list[float] = []

    result = LI.fetch_jd("4430572342", session=session, sleep=slept.append)

    assert result["jd_text"] is None
    assert result["error"] == "429 rate limited"
    assert len(session.calls) == 4
    assert slept == [30, 60, 90]


def test_jd_5xx_is_retried():
    session = _FakeSession([_FakeResponse(503), _FakeResponse(200, JD_HTML)])
    slept: list[float] = []

    result = LI.fetch_jd("4430572342", session=session, sleep=slept.append)

    assert "Ship safely" in (result["jd_text"] or "")
    assert len(session.calls) == 2
    assert slept == [30]


def test_jd_connection_error_is_retried():
    session = _FakeSession([ConnectionError("curl 56"), _FakeResponse(200, JD_HTML)])
    slept: list[float] = []

    result = LI.fetch_jd("4430572342", session=session, sleep=slept.append)

    assert "Build products" in (result["jd_text"] or "")
    assert len(session.calls) == 2
    assert slept == [30]


def test_a_successful_jd_is_not_retried():
    session = _FakeSession([_FakeResponse(200, JD_HTML)])
    slept: list[float] = []

    result = LI.fetch_jd("4430572342", session=session, sleep=slept.append)

    assert result["error"] is None
    assert len(session.calls) == 1
    assert slept == []


def test_a_non_429_4xx_is_not_retried():
    """A 404 is a caller bug, not a transient failure."""
    session = _FakeSession([_FakeResponse(404)])
    slept: list[float] = []

    result = LI.fetch_jd("4430572342", session=session, sleep=slept.append)

    assert result["jd_text"] is None
    assert result["error"] == "HTTP 404"
    assert len(session.calls) == 1
    assert slept == []


def test_engine_wrapper_passes_the_sleep_hook(monkeypatch):
    """The engine stays a thin wrapper, but the ladder's waits are injectable."""
    session = _FakeSession([_FakeResponse(429), _FakeResponse(200, JD_HTML)])
    monkeypatch.setattr(M, "_cc_session", session)
    slept: list[float] = []
    monkeypatch.setattr(M.time, "sleep", slept.append)

    result = M.fetch_jd("4430572342")

    assert "Build products" in (result["jd_text"] or "")
    assert len(session.calls) == 2
    assert slept == [30]
