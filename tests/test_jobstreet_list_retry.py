"""JobStreet list-page retry ladder (2026-10-31).

Before this fix the JobStreet list page had **no** retry at all: any failure —
a connection error, a non-200 status, or a JSON decode error — returned from
``crawl_list`` immediately and aborted the whole keyword crawl. When the very
first page failed, the crawl produced zero jobs, ``main()`` printed
"無資料，結束" and exited 0, so the caller saw a *successful* run that had
silently collected nothing.

The real instance: on 2026-10-30 the 7d run's first JobStreet page hit curl
error 56 ("Connection closed abruptly"), the run wrote zero rows, and it still
exited 0 — a false success that the supervisor nearly accepted as a completed
chunk.

The ladder now mirrors LinkedIn's: 429 / 5xx / connection error / JSON decode
error sleep 30/60/90s and retry (4 attempts total); any other 4xx is a caller
bug and is raised without burning three minutes of backoff.

All HTTP is faked; no request leaves the process.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402
from jobs_scraper.sources import jobstreet as JS  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": [], "totalCount": 0}
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


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


def _job(job_id: str, title: str = "Product Manager") -> dict:
    return {
        "id": job_id,
        "title": title,
        "employer": {"name": "Acme"},
        "locations": [{"label": "Singapore"}],
        "listingDate": "2026-10-30",
        "listingDateDisplay": "1d ago",
    }


def _page(*jobs):
    return {"data": list(jobs), "totalCount": len(jobs)}


def _url(keyword, page, daterange, worktype=JS.WORKTYPE_FT):
    return f"https://sg.jobstreet.com/api/jobsearch/v5/search?kw={keyword}&page={page}&dr={daterange}&wt={worktype}"


# ── the ladder ────────────────────────────────────────────────────────────────


def test_connection_error_is_retried_then_succeeds():
    session = _FakeSession([ConnectionError("curl 56"), _FakeResponse(200, _page(_job("1")))])
    slept: list[float] = []

    data = JS.fetch_list_page(
        "product manager",
        1,
        "7d",
        session=session,
        sleep_seconds=slept.append,
        build_url=_url,
    )

    assert data["totalCount"] == 1
    assert len(session.calls) == 2
    assert slept == [30]


def test_429_is_retried_then_succeeds():
    session = _FakeSession([_FakeResponse(429), _FakeResponse(200, _page(_job("1")))])
    slept: list[float] = []

    JS.fetch_list_page("product manager", 1, "7d", session=session, sleep_seconds=slept.append, build_url=_url)

    assert len(session.calls) == 2
    assert slept == [30]


def test_5xx_is_retried_then_succeeds():
    session = _FakeSession([_FakeResponse(503), _FakeResponse(200, _page(_job("1")))])
    slept: list[float] = []

    JS.fetch_list_page("product manager", 1, "7d", session=session, sleep_seconds=slept.append, build_url=_url)

    assert len(session.calls) == 2
    assert slept == [30]


def test_json_decode_error_is_retried_then_succeeds():
    session = _FakeSession(
        [_FakeResponse(200, json_error=ValueError("not json")), _FakeResponse(200, _page(_job("1")))]
    )
    slept: list[float] = []

    JS.fetch_list_page("product manager", 1, "7d", session=session, sleep_seconds=slept.append, build_url=_url)

    assert len(session.calls) == 2
    assert slept == [30]


def test_backoff_sequence_is_30_60_90_and_attempts_stop_at_four():
    session = _FakeSession([_FakeResponse(500)] * 4)
    slept: list[float] = []

    with pytest.raises(RuntimeError, match="after 4 attempts"):
        JS.fetch_list_page(
            "product manager", 1, "7d", session=session, sleep_seconds=slept.append, build_url=_url
        )

    assert len(session.calls) == 4
    assert slept == [30, 60, 90]


def test_non_429_4xx_is_not_retried():
    session = _FakeSession([_FakeResponse(403)])
    slept: list[float] = []

    with pytest.raises(JS.FatalListPageError):
        JS.fetch_list_page(
            "product manager", 1, "7d", session=session, sleep_seconds=slept.append, build_url=_url
        )

    assert len(session.calls) == 1
    assert slept == []


def test_legitimate_empty_page_does_not_retry():
    """A 200 with zero jobs is a real answer, not a failure — it must not retry."""
    session = _FakeSession([_FakeResponse(200, _page())])
    slept: list[float] = []

    data = JS.fetch_list_page(
        "product manager", 1, "7d", session=session, sleep_seconds=slept.append, build_url=_url
    )

    assert data["totalCount"] == 0
    assert len(session.calls) == 1
    assert slept == []


# ── the crawl keeps its coverage when a page recovers ────────────────────────


def test_crawl_list_keeps_jobs_when_the_first_page_recovers():
    """The false-success bug: a flaky first page used to yield zero jobs."""
    session = _FakeSession([ConnectionError("curl 56"), _FakeResponse(200, _page(_job("1")))])

    jobs = JS.crawl_list(
        "7d",
        1,
        ["product manager"],
        session=session,
        sleep=lambda label: None,
        sleep_seconds=lambda seconds: None,
        build_url=_url,
    )

    assert [j["job_id"] for j in jobs] == ["1"]
    assert len(session.calls) == 2


def test_crawl_list_returns_partial_results_when_retries_are_exhausted():
    session = _FakeSession([_FakeResponse(200, _page(_job("1"))), _FakeResponse(500)] * 4)

    jobs = JS.crawl_list(
        "7d",
        2,
        ["product manager"],
        session=session,
        sleep=lambda label: None,
        sleep_seconds=lambda seconds: None,
        build_url=_url,
    )

    # page 1 succeeded, page 2 exhausted its retries → the crawl keeps what it has
    assert [j["job_id"] for j in jobs] == ["1"]


# ── the engine wrapper ───────────────────────────────────────────────────────


def test_engine_wrapper_delegates_to_the_adapter(monkeypatch):
    """The engine keeps only a thin wrapper; the behaviour lives in the adapter."""
    session = _FakeSession([ConnectionError("curl 56"), _FakeResponse(200, _page(_job("1")))])
    monkeypatch.setattr(M, "_cc_session", session)
    slept: list[float] = []
    monkeypatch.setattr(M.time, "sleep", slept.append)

    data = M.fetch_jobstreet_list_page("product manager", 1, "7d")

    assert data["totalCount"] == 1
    assert len(session.calls) == 2
    assert slept == [30]
