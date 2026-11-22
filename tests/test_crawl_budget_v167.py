"""v1.6.7: the crawl budgets cover the pools they actually have.

v1.6.6 pinned the LinkedIn page budgets to Shanghai's pool depths and left
JobStreet's budgets at numbers that were never measured. Singapore's pools
are deeper than Shanghai's, and the JobStreet API states its own totals —
every one of those budgets sat below the pool, so every range was silently
truncated while the run reported success.

Three guarantees are pinned here:

* a range's budget covers the measured pool of the deepest known city for
  that range, and never exceeds what the Guest API can actually paginate;
* a non-429 4xx on a LinkedIn list page raises immediately instead of
  burning the retry ladder — the documented contract, and what the JobStreet
  adapter already did;
* the Guest API's pagination ceiling is an end, not a failure: a crawl that
  reaches it ends with what it collected instead of aborting the chunk.

No test touches the network: the list pages are faked.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402
from jobs_scraper.sources import jobstreet as JS  # noqa: E402
from jobs_scraper.sources import linkedin as LI  # noqa: E402

#: range -> (LinkedIn time filter, pages needed for the deepest measured pool)
#: Measured by walking the list API until it answered with an empty page.
#: Shanghai geoId 107388191 on 2026-11-22, Singapore geoId 102454443 on
#: 2026-11-23. Singapore is the deeper of the two for every long range.
LINKEDIN_MEASURED = {
    "1h": ("r3600", 5),
    "24h": ("r86400", 10),
    "3d": ("r259200", 25),
    "7d": ("r604800", 60),
    "14d": ("r1209600", 98),
    "21d": ("r1814400", 98),
    "30d": ("r2592000", 98),
}

#: range -> (JobStreet daterange in days, largest totalCount the API reported)
#: Measured 2026-11-23 in Singapore: one list request per keyword per range,
#: reading the totalCount the API returns.
JOBSTREET_MEASURED = {
    "1h": ("1", 8),
    "24h": ("1", 8),
    "3d": ("3", 292),
    "7d": ("7", 955),
    "14d": ("14", 1670),
    "21d": ("21", 2403),
    "30d": ("30", 3251),
}


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


# ── budgets ──────────────────────────────────────────────────────────────────
def test_linkedin_budget_covers_the_measured_pool():
    for range_name, (_tpr, pages) in LINKEDIN_MEASURED.items():
        budget = LI.TIME_RANGES[range_name][1]
        assert budget >= pages, f"{range_name}: budget {budget} < measured {pages} pages"


def test_linkedin_budget_never_exceeds_the_api_pagination_ceiling():
    """The Guest API refuses to paginate past start=1000, so a budget beyond
    that buys nothing and can only walk into a 400."""
    max_pages = LI.PAGINATION_CEILING // LI.PAGE_SIZE
    for range_name, (_tpr, _pages) in LINKEDIN_MEASURED.items():
        assert LI.TIME_RANGES[range_name][1] <= max_pages, range_name


def test_linkedin_time_filters_are_unchanged():
    for range_name, (tpr, _pages) in LINKEDIN_MEASURED.items():
        assert LI.TIME_RANGES[range_name][0] == tpr, range_name


def test_jobstreet_budget_covers_the_measured_total():
    for range_name, (_days, total) in JOBSTREET_MEASURED.items():
        needed = -(-total // JS.PAGE_SIZE)
        budget = JS.MAX_PAGES[range_name]
        assert budget >= needed, f"{range_name}: budget {budget} < needed {needed} pages"


def test_jobstreet_time_filters_are_unchanged():
    for range_name, (days, _total) in JOBSTREET_MEASURED.items():
        assert JS.TPR[range_name] == days, range_name


def test_no_budget_shrank():
    """v1.6.5 → v1.6.6 → v1.6.7 budgets, per source."""
    old_linkedin = {"1h": 1, "24h": 4, "3d": 7, "7d": 15, "14d": 30, "21d": 30, "30d": 25}
    for range_name, old in old_linkedin.items():
        assert LI.TIME_RANGES[range_name][1] >= old, range_name
    old_jobstreet = {"1h": 1, "24h": 4, "3d": 7, "7d": 15, "14d": 30, "21d": 30, "30d": 25}
    for range_name, old in old_jobstreet.items():
        assert JS.MAX_PAGES[range_name] >= old, range_name


def test_the_engine_uses_the_adapter_tables():
    assert M.TIME_RANGES is LI.TIME_RANGES
    assert M.JOBSTREET_MAX_PAGES is JS.MAX_PAGES


# ── a non-429 4xx must not burn the retry ladder ─────────────────────────────
def test_a_non_429_4xx_on_a_list_page_is_not_retried():
    """The contract says a 4xx other than 429 is a caller bug and is raised
    without retrying. The LinkedIn adapter used to catch its own
    raise_for_status() and spend 30+60+90s on it before giving up."""
    session = _FakeSession([_FakeResponse(400)])
    slept: list[float] = []
    try:
        LI.fetch_list_page("r604800", 0, "Singapore", "102454443", session=session, sleep=slept.append)
    except LI.FatalListPageError:
        pass
    else:
        raise AssertionError("expected FatalListPageError")
    assert len(session.calls) == 1
    assert slept == []


def test_a_429_is_still_retried():
    session = _FakeSession([_FakeResponse(429), _FakeResponse(200, "<html></html>")])
    slept: list[float] = []
    html = LI.fetch_list_page("r604800", 0, "Singapore", "102454443", session=session, sleep=slept.append)
    assert html == "<html></html>"
    assert len(session.calls) == 2
    assert slept == [30]


# ── the pagination ceiling is an end, not a failure ──────────────────────────
def test_the_pagination_ceiling_is_recognised():
    assert LI.PAGINATION_CEILING == 1000
    assert M._is_pagination_ceiling(1000, LI.FatalListPageError("http 400")) is True
    assert M._is_pagination_ceiling(990, LI.FatalListPageError("http 400")) is False
    assert M._is_pagination_ceiling(1000, RuntimeError("http 400")) is False


def test_a_crawl_that_reaches_the_ceiling_ends_with_what_it_collected(monkeypatch, tmp_path, capsys):
    """A pool deeper than the API's pagination window used to abort the whole
    chunk: the 400 was retried for three minutes and then raised, and the
    supervisor read the FAIL as a coverage gap."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)

    calls: list[int] = []

    def fake_fetch(tpr, start, location, geo_id):
        calls.append(start)
        if start >= LI.PAGINATION_CEILING:
            raise LI.FatalListPageError("linkedin list fetch failed: http 400")
        # one fresh posting per page, so the crawl keeps going instead of
        # hitting the empty-streak end after two pages
        return (
            f'<div class="base-card" data-entity-urn="urn:li:jobPosting:{start + 1}">'
            f'<h3 class="base-search-card__title">Product Manager</h3>'
            f'<a class="hidden-nested-link">Acme AI</a>'
            f'<span class="job-search-card__location">Singapore</span>'
            f'<time datetime="2026-08-20">3 days ago</time>'
            f'<a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/{start + 1}"></a>'
            f"</div>"
        )

    monkeypatch.setattr(M, "fetch_list_page", fake_fetch)

    jobs = M.crawl_list("r604800", 120, location="Singapore", geo_id="102454443")

    assert calls[-1] == LI.PAGINATION_CEILING
    assert len(jobs) == LI.PAGINATION_CEILING // LI.PAGE_SIZE
    out = capsys.readouterr().out
    assert "FAIL:" not in out
    assert "分頁天花板" in out
