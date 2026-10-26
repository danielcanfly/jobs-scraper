"""Characterization tests: 104 (onezerofour) detail / JD fetch.

Locks the current behaviour of ``hit_onezerofour_detail`` (URL assembly,
JSON payload shape, 404 fail-closed, 30/60/90s retry ladder) and of the
``fetch_onezerofour_jd`` wrapper around it.

All HTTP is faked: ``sg_product_jobs._cc_session`` is replaced with a stub and
``sg_product_jobs.time`` with a sleep recorder, so no request ever leaves the
process and no test waits on a real backoff.
"""

from __future__ import annotations

import sys
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
            raise ValueError("response has no JSON body")
        return self._payload


class _FakeSession:
    """Stands in for curl_cffi's Session; records every .get() call."""

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


class _FakeTime:
    """Replaces the ``time`` module reference used by the retry ladders."""

    def __init__(self):
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def time(self):
        return 0.0

    def monotonic(self):
        return 0.0


def _install(monkeypatch, responses):
    session = _FakeSession(responses)
    fake_time = _FakeTime()
    monkeypatch.setattr(M, "_cc_session", session)
    monkeypatch.setattr(M, "time", fake_time)
    return session, fake_time


def _detail_payload(description="Line one\nLine two\n\nLine three"):
    return {"data": {"jobDetail": {"jobDescription": description}}}


def test_detail_url_assembly(monkeypatch):
    session, _ = _install(monkeypatch, [_FakeResponse(payload=_detail_payload())])
    M.hit_onezerofour_detail("abcde")
    assert session.calls[0]["url"] == "https://www.104.com.tw/job/ajax/content/abcde"


def test_detail_request_referer_points_at_the_job_page(monkeypatch):
    session, _ = _install(monkeypatch, [_FakeResponse(payload=_detail_payload())])
    M.hit_onezerofour_detail("abcde")
    headers = session.calls[0]["headers"]
    assert headers["Referer"] == "https://www.104.com.tw/job/abcde"
    assert headers["Accept"] == "application/json, text/plain, */*"
    assert "Mozilla/5.0" in headers["User-Agent"]


def test_detail_returns_raw_job_description(monkeypatch):
    _install(monkeypatch, [_FakeResponse(payload=_detail_payload())])
    assert M.hit_onezerofour_detail("abcde") == "Line one\nLine two\n\nLine three"


def test_detail_missing_job_description_returns_empty_string(monkeypatch):
    _install(monkeypatch, [_FakeResponse(payload={"data": {"jobDetail": {}}})])
    assert M.hit_onezerofour_detail("abcde") == ""


def test_detail_missing_data_key_returns_empty_string(monkeypatch):
    _install(monkeypatch, [_FakeResponse(payload={})])
    assert M.hit_onezerofour_detail("abcde") == ""


def test_detail_404_raises_immediately_without_retry(monkeypatch):
    """404 is fail-closed (job delisted) — it must NOT be retried."""
    session, fake_time = _install(monkeypatch, [_FakeResponse(status_code=404)])
    try:
        M.hit_onezerofour_detail("abcde")
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert "104 detail 404 for slug=abcde" in msg
    assert "已下架" in msg
    assert len(session.calls) == 1  # no retry
    assert fake_time.sleeps == []  # no backoff


def test_detail_retries_with_30_60_90_backoff_then_raises(monkeypatch):
    session, fake_time = _install(monkeypatch, [_FakeResponse(status_code=500) for _ in range(4)])
    try:
        M.hit_onezerofour_detail("abcde")
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert msg == "104 detail API fail after 4 attempts: http 500"
    assert len(session.calls) == 4
    assert fake_time.sleeps == [30, 60, 90]


def test_detail_network_error_is_retried_then_raises(monkeypatch):
    session, fake_time = _install(monkeypatch, [ConnectionError("boom") for _ in range(4)])
    try:
        M.hit_onezerofour_detail("abcde")
    except RuntimeError as e:
        msg = str(e)
    else:
        raise AssertionError("expected RuntimeError")
    assert msg.startswith("104 detail API fail after 4 attempts: ConnectionError: boom")
    assert len(session.calls) == 4
    assert fake_time.sleeps == [30, 60, 90]


def test_detail_retry_recovers_after_a_transient_500(monkeypatch):
    session, fake_time = _install(
        monkeypatch,
        [_FakeResponse(status_code=500), _FakeResponse(payload=_detail_payload("recovered"))],
    )
    assert M.hit_onezerofour_detail("abcde") == "recovered"
    assert len(session.calls) == 2
    assert fake_time.sleeps == [30]


def test_fetch_jd_success_shape(monkeypatch):
    _install(monkeypatch, [_FakeResponse(payload=_detail_payload("  A line  \n\n  B line  "))])
    out = M.fetch_onezerofour_jd("abcde")
    assert out["jd_text"] == "  A line  \n\n  B line  "
    assert out["jd_lines"] == ["A line", "B line"]
    assert out["jd_html"] is None
    assert out["company"] == ""  # 104 list stage already has it
    assert out["location"] == ""
    assert out["title"] == ""
    assert out["error"] is None


def test_fetch_jd_on_404_returns_error_dict(monkeypatch):
    _install(monkeypatch, [_FakeResponse(status_code=404)])
    out = M.fetch_onezerofour_jd("abcde")
    assert out["jd_text"] is None
    assert out["jd_lines"] is None
    assert out["jd_html"] is None
    assert "104 detail 404 for slug=abcde" in out["error"]


def test_fetch_jd_on_empty_description_returns_empty_jd_error(monkeypatch):
    _install(monkeypatch, [_FakeResponse(payload=_detail_payload(""))])
    out = M.fetch_onezerofour_jd("abcde")
    assert out["jd_text"] is None
    assert out["error"] == "empty JD"


def test_fetch_jd_lines_drop_blank_lines(monkeypatch):
    _install(monkeypatch, [_FakeResponse(payload=_detail_payload("one\n\n\ntwo\nthree"))])
    out = M.fetch_onezerofour_jd("abcde")
    assert out["jd_lines"] == ["one", "two", "three"]
