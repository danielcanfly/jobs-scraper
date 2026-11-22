"""v1.6.6: a range's page budget must cover its measured pool.

Before v1.6.6 the LinkedIn range table gave 30d a 25-page budget (250
jobs) while Shanghai's 30d pool holds ~700 postings, so the crawl simply
stopped at the budget: the run reported success and the postings past the
budget were never seen at all. The same held for 1h, 24h, 3d and 7d.

The budgets are pinned to the pool depths measured against the live Guest
API on 2026-11-22 by walking the list API until it answered with an empty
page (Shanghai, geoId 107388191). The measurements are a floor, not a
ceiling: pools grow as postings are published, so every budget keeps
headroom.

The budget is a ceiling, not a target. `crawl_list` ends a crawl after two
consecutive pages with no new posting, so a city with a small pool still
stops early — a wider budget costs a small pool nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402
from jobs_scraper.sources import linkedin as LI  # noqa: E402

# range -> (LinkedIn time filter, measured pool depth in pages, measured pool in jobs)
# Measured 2026-11-22 against the live Guest API, Shanghai geoId 107388191.
MEASURED = {
    "1h": ("r3600", 5, 50),
    "24h": ("r86400", 10, 100),
    "3d": ("r259200", 25, 250),
    "7d": ("r604800", 40, 400),
    "14d": ("r1209600", 29, 290),
    "21d": ("r1814400", 30, 300),
    "30d": ("r2592000", 70, 700),
}


def test_every_range_covers_its_measured_pool():
    for range_name, (_tpr, pages, _jobs) in MEASURED.items():
        budget = LI.TIME_RANGES[range_name][1]
        assert budget >= pages, f"{range_name}: budget {budget} < measured {pages} pages"


def test_the_30d_budget_covers_the_measured_shanghai_pool():
    assert LI.TIME_RANGES["30d"][1] >= MEASURED["30d"][1]


def test_the_budget_never_shrank():
    """v1.6.5 budgets: 1h=1, 24h=4, 3d=7, 7d=15, 14d=30, 21d=30, 30d=25."""
    old = {"1h": 1, "24h": 4, "3d": 7, "7d": 15, "14d": 30, "21d": 30, "30d": 25}
    for range_name, old_budget in old.items():
        assert LI.TIME_RANGES[range_name][1] >= old_budget, range_name


def test_the_time_filters_are_unchanged():
    for range_name, (tpr, _pages, _jobs) in MEASURED.items():
        assert LI.TIME_RANGES[range_name][0] == tpr, range_name


def test_the_engine_uses_the_adapter_table():
    assert M.TIME_RANGES is LI.TIME_RANGES
    assert M.LINKEDIN_TIME_RANGES is LI.TIME_RANGES


def test_the_cli_still_exposes_every_range():
    parser = M.build_arg_parser()
    for range_name in MEASURED:
        args = parser.parse_args([range_name])
        assert args.range == range_name


def test_an_explicit_max_pages_still_wins():
    parser = M.build_arg_parser()
    args = parser.parse_args(["30d", "--max-pages", "7"])
    assert args.max_pages == 7
