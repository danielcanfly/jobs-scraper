"""Characterization tests: Cake time-window, coverage and retry semantics.

Pinned contracts:

* ``1h`` means **one hour**; every other range means N **days**.
* the aggregate ``coverage_state`` is one of COMPLETE / TRUNCATED /
  UNKNOWN_NO_CUTOFF / EMPTY (plus PARTIAL_ERROR when a keyword worker fails —
  an extra state the aggregator can also return).
* ``max_pages`` is really threaded through to the per-keyword Cake crawler.
* the list API has a 30/60/90s retry ladder (429 / 5xx), while other 4xx are
  non-retryable.

Offline only: the Cake list API is faked, human sleeps are disabled.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise AssertionError(f"unexpected extra request: {url}")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeTime:
    def __init__(self):
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def time(self):
        return 0.0

    def monotonic(self):
        return 0.0


def _job(path="job-a", updated=None, title="Product Manager"):
    return {
        "path": path,
        "page": {"path": "acme-corp", "name": "Acme Corp", "geo": {"state_name": "Taipei City"}},
        "title": title,
        "description": "A description long enough to look like a JD body.",
        "content_updated_at": updated or datetime.now(timezone.utc).isoformat(),
    }


def _page(jobs, total_pages=1):
    return {
        "data": jobs,
        "total_pages": total_pages,
        "total_entries": len(jobs),
    }


def _install_list_fake(monkeypatch, pages_by_call=None, response=None):
    """Fake M._cake_list_with_retry; records (keyword, page) calls."""
    calls: list[tuple[str, int]] = []

    def fake(kw, page, payload, max_retries=3):
        calls.append((kw, page))
        if pages_by_call is not None:
            return pages_by_call(len(calls) - 1)
        return response

    monkeypatch.setattr(M, "_cake_list_with_retry", fake)
    monkeypatch.setattr(M, "cake_human_sleep", lambda *a, **k: None)
    return calls


# ── time window ─────────────────────────────────────────────────────────────
def test_time_filter_table():
    assert M.CAKE_TIME_FILTER == {
        "1h": ("hours", 1),
        "24h": ("days", 1),
        "3d": ("days", 3),
        "7d": ("days", 7),
        "14d": ("days", 14),
        "21d": ("days", 21),
        "30d": ("days", 30),
    }


def test_1h_cutoff_is_one_hour(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()]))
    before = datetime.now(timezone.utc)
    out = M.crawl_cake_list("1h", max_pages=1, keywords=["PM"])
    after = datetime.now(timezone.utc)
    cutoff = datetime.fromisoformat(out["cutoff"])
    assert before - timedelta(hours=1) <= cutoff <= after - timedelta(hours=1)
    assert timedelta(minutes=55) <= (before - cutoff) <= timedelta(hours=1, minutes=5)


def test_24h_cutoff_is_one_day(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()]))
    before = datetime.now(timezone.utc)
    out = M.crawl_cake_list("24h", max_pages=1, keywords=["PM"])
    cutoff = datetime.fromisoformat(out["cutoff"])
    assert before - timedelta(days=1) <= cutoff <= before - timedelta(days=1) + timedelta(seconds=30)


def test_7d_cutoff_is_seven_days(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()]))
    before = datetime.now(timezone.utc)
    out = M.crawl_cake_list("7d", max_pages=1, keywords=["PM"])
    cutoff = datetime.fromisoformat(out["cutoff"])
    assert before - timedelta(days=7) <= cutoff <= before - timedelta(days=7) + timedelta(seconds=30)


def test_30d_cutoff_is_thirty_days(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()]))
    before = datetime.now(timezone.utc)
    out = M.crawl_cake_list("30d", max_pages=1, keywords=["PM"])
    cutoff = datetime.fromisoformat(out["cutoff"])
    assert before - timedelta(days=30) <= cutoff <= before - timedelta(days=30) + timedelta(seconds=30)


def test_no_daterange_means_no_cutoff(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()]))
    out = M.crawl_cake_list(None, max_pages=1, keywords=["PM"])
    assert out["cutoff"] is None
    assert out["coverage_state"] == "UNKNOWN_NO_CUTOFF"


# ── coverage state ──────────────────────────────────────────────────────────
def test_coverage_state_constants_are_the_documented_set():
    """The aggregator can only return these five states."""
    states = set()
    cutoff = datetime.now(timezone.utc).isoformat()
    for kw_states in (
        [],
        [{"coverage_state": "COMPLETE"}],
        [{"coverage_state": "TRUNCATED"}],
        [{"coverage_state": "ERROR"}],
        [{"coverage_state": "COMPLETE"}, {"coverage_state": "TRUNCATED"}],
        [{"coverage_state": "COMPLETE"}, {"coverage_state": "ERROR"}],
    ):
        states.add(M._aggregate_cake_coverage(kw_states, cutoff, 1))
        states.add(M._aggregate_cake_coverage(kw_states, None, 1))
    assert states == {"COMPLETE", "TRUNCATED", "EMPTY", "UNKNOWN_NO_CUTOFF", "PARTIAL_ERROR"}


def test_aggregate_complete_when_every_worker_completed(monkeypatch):
    cutoff = datetime.now(timezone.utc).isoformat()
    assert M._aggregate_cake_coverage([{"coverage_state": "COMPLETE"}], cutoff, 3) == "COMPLETE"


def test_aggregate_empty_when_no_jobs_at_all(monkeypatch):
    cutoff = datetime.now(timezone.utc).isoformat()
    assert M._aggregate_cake_coverage([{"coverage_state": "COMPLETE"}], cutoff, 0) == "EMPTY"


def test_aggregate_truncated_when_any_worker_truncated(monkeypatch):
    cutoff = datetime.now(timezone.utc).isoformat()
    res = M._aggregate_cake_coverage([{"coverage_state": "COMPLETE"}, {"coverage_state": "TRUNCATED"}], cutoff, 3)
    assert res == "TRUNCATED"


def test_aggregate_unknown_without_cutoff(monkeypatch):
    assert M._aggregate_cake_coverage([{"coverage_state": "COMPLETE"}], None, 3) == "UNKNOWN_NO_CUTOFF"


def test_aggregate_empty_without_any_keyword(monkeypatch):
    cutoff = datetime.now(timezone.utc).isoformat()
    assert M._aggregate_cake_coverage([], cutoff, 0) == "EMPTY"


def test_aggregate_partial_error_wins_over_everything(monkeypatch):
    cutoff = datetime.now(timezone.utc).isoformat()
    res = M._aggregate_cake_coverage([{"coverage_state": "COMPLETE"}, {"coverage_state": "ERROR"}], cutoff, 3)
    assert res == "PARTIAL_ERROR"


def test_crawl_reports_complete_when_the_server_is_exhausted(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()], total_pages=1))
    out = M.crawl_cake_list("7d", max_pages=5, keywords=["PM"])
    assert out["coverage_state"] == "COMPLETE"
    assert out["keyword_results"][0]["server_exhausted"] is True
    assert out["keyword_results"][0]["coverage_state"] == "COMPLETE"


def test_crawl_reports_truncated_when_max_pages_is_hit_first(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()], total_pages=99))
    out = M.crawl_cake_list("7d", max_pages=2, keywords=["PM"])
    assert out["coverage_state"] == "TRUNCATED"
    assert out["keyword_results"][0]["server_exhausted"] is False
    assert out["keyword_results"][0]["coverage_state"] == "TRUNCATED"


def test_crawl_reports_empty_when_the_search_returns_nothing(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([], total_pages=1))
    out = M.crawl_cake_list("7d", max_pages=3, keywords=["PM"])
    assert out["coverage_state"] == "EMPTY"
    assert out["jobs"] == []


def test_boundary_job_is_proof_but_is_never_returned(monkeypatch):
    """A job older than the cutoff proves the boundary and is dropped."""
    old = (_job(path="old-job", updated="2020-01-01T00:00:00+00:00"),)
    _install_list_fake(monkeypatch, response=_page(list(old), total_pages=1))
    out = M.crawl_cake_list("7d", max_pages=3, keywords=["PM"])
    assert out["jobs"] == []
    assert out["keyword_results"][0]["boundary_reached"] is True
    assert out["keyword_results"][0]["coverage_state"] == "COMPLETE"
    # The aggregate reports EMPTY (not COMPLETE) because zero jobs survived
    # the boundary filter — the worker proved completeness, the run had
    # nothing to show for it.
    assert out["coverage_state"] == "EMPTY"


def test_unknown_timestamp_is_counted_and_never_proves_the_boundary(monkeypatch):
    bad = _job(path="bad-ts", updated="not-a-timestamp")
    _install_list_fake(monkeypatch, response=_page([bad], total_pages=99))
    out = M.crawl_cake_list("7d", max_pages=1, keywords=["PM"])
    assert out["keyword_results"][0]["unknown_timestamp_count"] == 1
    assert out["keyword_results"][0]["boundary_reached"] is False
    # the job is retained (unknown time cannot prove a boundary)
    assert [j["job_id"] for j in out["jobs"]] == ["bad-ts"]


def test_worker_failure_surfaces_as_partial_error(monkeypatch):
    def boom(kw, page, payload, max_retries=3):
        raise RuntimeError("api down")

    monkeypatch.setattr(M, "_cake_list_with_retry", boom)
    monkeypatch.setattr(M, "cake_human_sleep", lambda *a, **k: None)
    out = M.crawl_cake_list("7d", max_pages=1, keywords=["PM"])
    assert out["coverage_state"] == "PARTIAL_ERROR"
    assert out["keyword_results"][0]["coverage_state"] == "ERROR"


# ── max_pages threading ─────────────────────────────────────────────────────
def test_max_pages_is_threaded_to_the_crawler(monkeypatch):
    calls = _install_list_fake(monkeypatch, response=_page([_job()], total_pages=99))
    out = M.crawl_cake_list("7d", max_pages=3, keywords=["PM"])
    assert [p for _, p in calls] == [1, 2, 3]
    assert out["max_pages_used"] == 3
    assert out["keyword_results"][0]["max_pages"] == 3
    assert out["keyword_results"][0]["pages_scanned"] == 3


def test_max_pages_none_falls_back_to_the_range_table(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()], total_pages=1))
    out = M.crawl_cake_list("7d", max_pages=None, keywords=["PM"])
    assert out["max_pages_used"] == M.CAKE_MAX_PAGES["7d"] == 15


def test_max_pages_none_without_range_defaults_to_fifteen(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()], total_pages=1))
    out = M.crawl_cake_list(None, max_pages=None, keywords=["PM"])
    assert out["max_pages_used"] == 15


def test_each_keyword_gets_its_own_page_budget(monkeypatch):
    calls = _install_list_fake(monkeypatch, response=_page([_job()], total_pages=99))
    M.crawl_cake_list("7d", max_pages=2, keywords=["kw-a", "kw-b"])
    assert sorted(calls) == [("kw-a", 1), ("kw-a", 2), ("kw-b", 1), ("kw-b", 2)]


def test_duplicate_paths_across_keywords_are_deduped(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job(path="same-job")], total_pages=1))
    out = M.crawl_cake_list("7d", max_pages=1, keywords=["kw-a", "kw-b"])
    assert [j["job_id"] for j in out["jobs"]] == ["same-job"]


# ── sort_by invariant ───────────────────────────────────────────────────────
def test_effective_sort_by_forces_latest_when_a_cutoff_exists():
    assert M._effective_cake_sort_by("popularity", datetime.now(timezone.utc)) == "latest"


def test_effective_sort_by_keeps_the_request_without_a_cutoff():
    assert M._effective_cake_sort_by("popularity", None) == "popularity"
    assert M._effective_cake_sort_by(None, None) == "latest"


def test_ranged_crawl_reports_the_forced_sort_by(monkeypatch):
    _install_list_fake(monkeypatch, response=_page([_job()], total_pages=1))
    out = M.crawl_cake_list("7d", max_pages=1, keywords=["PM"], sort_by="popularity")
    assert out["requested_sort_by"] == "popularity"
    assert out["effective_sort_by"] == "latest"


# ── retry ladder ────────────────────────────────────────────────────────────
def _install_session(monkeypatch, responses):
    session = _FakeSession(responses)
    fake_time = _FakeTime()
    monkeypatch.setattr(M, "_cc_session", session)
    monkeypatch.setattr(M, "time", fake_time)
    return session, fake_time


def test_list_api_posts_to_the_search_endpoint(monkeypatch):
    session, _ = _install_session(monkeypatch, [_FakeResponse(payload=_page([_job()]))])
    payload = M.build_cake_search_payload("PM", 1)
    data = M._cake_list_with_retry("PM", 1, payload)
    assert data["total_pages"] == 1
    assert session.calls[0]["url"] == "https://api.cake.me/api/client/v2/jobs/search"
    assert session.calls[0]["json"] == payload


def test_list_api_retries_429_with_30_60_90(monkeypatch):
    session, fake_time = _install_session(monkeypatch, [_FakeResponse(status_code=429) for _ in range(4)])
    try:
        M._cake_list_with_retry("PM", 1, M.build_cake_search_payload("PM", 1))
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert msg == "cake list API fail after 4 attempts: http 429"
    assert len(session.calls) == 4
    assert fake_time.sleeps == [30, 60, 90]


def test_list_api_retries_500_with_30_60_90(monkeypatch):
    session, fake_time = _install_session(monkeypatch, [_FakeResponse(status_code=503) for _ in range(4)])
    try:
        M._cake_list_with_retry("PM", 1, M.build_cake_search_payload("PM", 1))
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert msg == "cake list API fail after 4 attempts: http 503"
    assert fake_time.sleeps == [30, 60, 90]


def test_list_api_recovers_after_a_429(monkeypatch):
    session, fake_time = _install_session(
        monkeypatch,
        [_FakeResponse(status_code=429), _FakeResponse(payload=_page([_job()]))],
    )
    data = M._cake_list_with_retry("PM", 1, M.build_cake_search_payload("PM", 1))
    assert data["total_pages"] == 1
    assert len(session.calls) == 2
    assert fake_time.sleeps == [30]


def test_list_api_does_not_retry_a_400(monkeypatch):
    session, fake_time = _install_session(monkeypatch, [_FakeResponse(status_code=400, text="bad request")])
    try:
        M._cake_list_with_retry("PM", 1, M.build_cake_search_payload("PM", 1))
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert "non-retryable HTTP 400" in msg
    assert len(session.calls) == 1
    assert fake_time.sleeps == []


def test_list_api_retries_connection_errors(monkeypatch):
    session, fake_time = _install_session(monkeypatch, [ConnectionError("boom") for _ in range(4)])
    try:
        M._cake_list_with_retry("PM", 1, M.build_cake_search_payload("PM", 1))
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert msg.startswith("cake list API fail after 4 attempts: ConnectionError: boom")
    assert fake_time.sleeps == [30, 60, 90]
