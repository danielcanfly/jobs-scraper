"""v1.6.8: every JobStreet keyword is crawled to the end of its own pool.

The JobStreet list API takes one keyword per request, so the crawl runs the
keyword set one after another and de-duplicates by `job_id` across them. The
soft stop that ends a keyword used to count the postings that were new to the
**whole crawl**: after the first keyword had filled the shared `seen` set, every
later keyword saw almost nothing "new" on its first page and stopped there. A
five-keyword crawl really crawled one keyword — the 7d run produced ~250
postings where the API's own totals promise ~2,600.

The signal now measures the postings that are new to **that keyword**, so each
keyword runs to the end of its own pool and the cross-keyword de-duplication
still returns a posting matched by two keywords only once.

The page budget has to follow: once every keyword crawls its own pool, the
budget is sized for the *largest* keyword's pool, not for the first one. The
1h / 24h / 3d budgets were below even that.

Two more guarantees are pinned here:

* a keyword that fails after its retries does not throw away the other
  keywords' postings — the failure stays visible, but it no longer costs the
  whole run (per-keyword crawling multiplies the request count by five, and a
  single failure aborting everything would be a regression the change itself
  introduces);
* the budget still covers the largest measured pool, and never shrank.

No test touches the network: the list pages are faked.
"""

from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from jobs_scraper.sources import jobstreet as JS  # noqa: E402

#: range -> (JobStreet daterange in days, largest totalCount the API reported)
#: Measured 2026-11-23 in Singapore, one list request per keyword per range:
#: product manager 520 / product director 382 / director of product 394 /
#: head of product 184 / product lead 1109 for 7d, and the same shape scaled
#: up for the longer ranges. The one-day window accumulates through the day —
#: it answered 2 postings in the morning and 181 by midday — so the short
#: ranges get a budget that covers a whole day rather than a morning's worth.
JOBSTREET_MEASURED = {
    "1h": ("1", 181),
    "24h": ("1", 181),
    "3d": ("3", 448),
    "7d": ("7", 1109),
    "14d": ("14", 1837),
    "21d": ("21", 2564),
    "30d": ("30", 3369),
}

#: v1.6.7 budgets — a budget may only grow.
V167_BUDGETS = {"1h": 2, "24h": 4, "3d": 20, "7d": 62, "14d": 109, "21d": 155, "30d": 210}


def _job(job_id: str) -> dict:
    return {
        "id": job_id,
        "title": f"Product Manager {job_id}",
        "employer": {"name": "Acme"},
        "locations": [{"label": "Singapore"}],
        "listingDate": "2026-11-20",
        "listingDateDisplay": "1d ago",
    }


def _page(*job_ids: str) -> dict:
    return {"data": [_job(i) for i in job_ids], "totalCount": len(job_ids)}


def _ids(prefix: str, count: int, start: int = 1) -> list[str]:
    return [f"{prefix}{i}" for i in range(start, start + count)]


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"data": [], "totalCount": 0}

    def json(self):
        return self._payload


class _FakeSession:
    """Serves scripted list pages per (keyword, page); records every request."""

    def __init__(self, pages: dict[tuple[str, int], object]):
        self.pages = pages
        self.calls: list[tuple[str, int]] = []

    def get(self, url, **kwargs):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        keyword = query["keywords"][0]
        page = int(query["page"][0])
        self.calls.append((keyword, page))
        scripted = self.pages.get((keyword, page))
        if scripted is None:
            return _FakeResponse(200, _page())
        if isinstance(scripted, Exception):
            raise scripted
        return _FakeResponse(200, scripted)


def _crawl(session, keywords, max_pages=6, daterange="7"):
    return JS.crawl_list(
        daterange,
        max_pages,
        keywords,
        session=session,
        sleep=lambda label: None,
        sleep_seconds=lambda seconds: None,
    )


# ── the regression ───────────────────────────────────────────────────────────
def test_a_later_keyword_is_not_stopped_by_the_earlier_keyword():
    """The old soft stop counted the crawl's new postings, so the second
    keyword stopped on its first page whenever the first keyword had already
    claimed those postings."""
    first = _ids("a", 20)
    second_page_one = list(first)  # the same postings the first keyword returned
    second_page_two = _ids("b", 20, 21)
    second_page_three = _ids("b", 20, 41)

    session = _FakeSession(
        {
            ("product manager", 1): _page(*first),
            ("product manager", 2): _page(*_ids("a", 20, 21)),
            ("product manager", 3): _page(*_ids("a", 20, 41)),
            ("product lead", 1): _page(*second_page_one),
            ("product lead", 2): _page(*second_page_two),
            ("product lead", 3): _page(*second_page_three),
        }
    )

    jobs = _crawl(session, ["product manager", "product lead"])

    ids = [j["job_id"] for j in jobs]
    # the second keyword was crawled past its first page
    assert ("product lead", 2) in session.calls
    assert ("product lead", 3) in session.calls
    # ... and its later postings are in the result
    assert set(second_page_two) | set(second_page_three) <= set(ids)
    # ... while the postings both keywords match are still returned once
    assert len(ids) == len(set(ids)) == 60 + 40


def test_the_soft_stop_is_measured_per_keyword():
    """A keyword whose page is nearly empty stops there, no matter how many
    postings the earlier keywords already returned."""
    session = _FakeSession(
        {
            ("product manager", 1): _page(*_ids("a", 20)),
            ("head of product", 1): _page(*_ids("h", 5)),
        }
    )

    jobs = _crawl(session, ["product manager", "head of product"])

    ids = [j["job_id"] for j in jobs]
    assert len(ids) == 25
    # five postings for the second keyword, one page only
    assert [c for c in session.calls if c[0] == "head of product"] == [("head of product", 1)]


def test_a_keyword_runs_to_its_own_pool_end():
    """A keyword keeps paging while its own pages are full."""
    pages: dict[tuple[str, int], object] = {}
    for p in range(1, 4):
        pages[("product lead", p)] = _page(*_ids("p", 20, (p - 1) * 20 + 1))
    session = _FakeSession(pages)

    jobs = _crawl(session, ["product lead"], max_pages=6)

    assert len(jobs) == 60
    assert ("product lead", 4) in session.calls  # the empty page that ends the pool


# ── cross-keyword de-duplication is unchanged ───────────────────────────────
def test_a_posting_matched_by_two_keywords_is_returned_once():
    shared = _ids("s", 20)
    session = _FakeSession(
        {
            ("product manager", 1): _page(*shared),
            ("product lead", 1): _page(*shared),
        }
    )

    jobs = _crawl(session, ["product manager", "product lead"])

    ids = [j["job_id"] for j in jobs]
    assert len(ids) == 20
    assert len(set(ids)) == 20


# ── a failing keyword no longer costs the whole run ─────────────────────────
def test_a_failed_keyword_does_not_discard_the_other_keywords(capsys):
    session = _FakeSession(
        {
            ("product manager", 1): _page(*_ids("a", 20)),
            ("product director", 1): ConnectionError("curl 56"),
            ("product lead", 1): _page(*_ids("p", 20)),
        }
    )

    jobs = _crawl(session, ["product manager", "product director", "product lead"])

    ids = [j["job_id"] for j in jobs]
    assert set(_ids("a", 20)) <= set(ids)
    assert set(_ids("p", 20)) <= set(ids)
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "product director" in out


# ── the budget follows the largest keyword ──────────────────────────────────
def test_the_budget_covers_the_largest_measured_keyword_pool():
    for range_name, (_days, pool) in JOBSTREET_MEASURED.items():
        needed = -(-pool // JS.PAGE_SIZE) + 1  # + the empty page that ends the pool
        budget = JS.MAX_PAGES[range_name]
        assert budget >= needed, f"{range_name}: budget {budget} < needed {needed} pages"


def test_no_budget_shrank():
    for range_name, old in V167_BUDGETS.items():
        assert JS.MAX_PAGES[range_name] >= old, range_name


def test_the_time_filters_are_unchanged():
    for range_name, (days, _pool) in JOBSTREET_MEASURED.items():
        assert JS.TPR[range_name] == days, range_name
