"""v1.8.0: 頁面區間式切塊 (取代「累計頁數」切塊)。

2026-11-24 實測: 舊的 supervisor 切塊是「累計式」——
第 N 塊爬第 1..N 頁 → 前面 N-1 頁每跑一塊就重爬一遍。
30d 的 JobStreet 因此爬了 2,179 頁, 但池子只需要 ~406 頁 = 5.4× 重複
(product lead 一個 keyword 就 1,260 頁 vs 169 頁 = 7.5×)。

改成「區間式」(chunk k 只爬自己那一段) 後每頁只抓一次。
跨 chunk 的去重本來就有 (seen_jds.jsonl + sheet pre-dedup) → 不會重抓 JD。

這支測試把「區間不重疊、不漏頁」釘死。
"""

from __future__ import annotations

import pytest

import sg_product_jobs as M
from jobs_scraper.sources import jobstreet as JS


# ── 假的 list API ─────────────────────────────────────────────────────────────
class _FakeResponse:
    def __init__(self, payload: dict):
        self.status_code = 200
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    """session.get(url) → 回 {"page": <url 最後一段的頁碼>}。"""

    def __init__(self, calls: list[int]):
        self.calls = calls

    def get(self, url, **_kwargs):
        page = int(url.rsplit("/", 1)[-1])
        self.calls.append(page)
        return _FakeResponse({"page": page})


def _build_url(keyword: str, page: int, daterange: str, *args, **kwargs) -> str:
    return f"https://example.invalid/{page}"


def _parse_page(page_size: int):
    def parse_page(data: dict, keyword: str) -> list[dict]:
        page = int(data["page"])
        return [
            {
                "job_id": f"{keyword}-{page}-{i}",
                "title": "Product Manager",
                "source": "jobstreet",
            }
            for i in range(page_size)
        ]

    return parse_page


def _run_crawl(start_page: int, max_pages: int, calls: list[int], page_size: int = 20) -> list[dict]:
    return JS.crawl_list(
        "30",
        max_pages,
        ["product manager"],
        session=_FakeSession(calls),
        sleep=lambda label: None,
        sleep_seconds=lambda _s: None,
        build_url=_build_url,
        parse_page=_parse_page(page_size),
        start_page=start_page,
    )


# ── JobStreet adapter ────────────────────────────────────────────────────────
def test_a_range_crawl_only_touches_its_own_pages():
    calls: list[int] = []
    jobs = _run_crawl(start_page=3, max_pages=5, calls=calls)
    assert calls == [3, 4, 5]
    assert len(jobs) == 60  # 3 頁 × 20 筆


def test_the_default_still_crawls_from_page_one():
    """向後相容: 不給 start_page 就跟舊的一樣從頭爬。"""
    calls: list[int] = []
    _run_crawl(start_page=1, max_pages=4, calls=calls)
    assert calls == [1, 2, 3, 4]


def test_an_empty_range_makes_no_request():
    calls: list[int] = []
    jobs = _run_crawl(start_page=9, max_pages=4, calls=calls)
    assert calls == []
    assert jobs == []


def test_a_start_page_below_one_is_clamped_to_page_one():
    calls: list[int] = []
    _run_crawl(start_page=0, max_pages=2, calls=calls)
    assert calls == [1, 2]


def test_consecutive_ranges_cover_every_page_exactly_once():
    """這是整個修法的核心: 區間式切塊不能重疊, 也不能漏頁。"""
    calls: list[int] = []
    for start, end in ((1, 12), (13, 24), (25, 36)):
        _run_crawl(start_page=start, max_pages=end, calls=calls)
    assert calls == list(range(1, 37))
    assert len(calls) == len(set(calls))  # 沒有重複


def test_the_cumulative_style_would_have_re_crawled_everything():
    """對照組: 舊的累計式切塊會把前面的頁重爬一遍。"""
    calls: list[int] = []
    for end in (12, 24, 36):
        _run_crawl(start_page=1, max_pages=end, calls=calls)
    assert calls == list(range(1, 13)) + list(range(1, 25)) + list(range(1, 37))
    assert len(calls) > 36  # 真的重爬了


def test_the_per_keyword_soft_stop_still_fires_at_the_end_of_the_pool():
    """區間式模式下 kw_seen 只有這一塊的 → 軟停訊號要在池底才觸發。"""
    calls: list[int] = []

    def parse_page(data: dict, keyword: str) -> list[dict]:
        page = int(data["page"])
        # 第 4 頁之後就沒資料了 → 池底
        if page > 3:
            return []
        return [{"job_id": f"{keyword}-{page}-{i}", "title": "PM", "source": "jobstreet"} for i in range(20)]

    jobs = JS.crawl_list(
        "30",
        10,
        ["product manager"],
        session=_FakeSession(calls),
        sleep=lambda label: None,
        sleep_seconds=lambda _s: None,
        build_url=_build_url,
        parse_page=parse_page,
        start_page=1,
    )
    # 每頁 20 筆 (高於 SOFT_STOP_MIN_FRESH) → 一路爬到池底 (第 4 頁回空) 才軟停
    assert calls == [1, 2, 3, 4]
    assert len(jobs) == 60


# ── 引擎層 ────────────────────────────────────────────────────────────────────
def test_the_cli_exposes_a_start_page():
    args = M.build_arg_parser().parse_args(["30d", "--source", "jobstreet", "--start-page", "13", "--max-pages", "24"])
    assert args.start_page == 13
    assert args.max_pages == 24


def test_the_cli_defaults_to_page_one():
    args = M.build_arg_parser().parse_args(["30d"])
    assert args.start_page == 1


def test_the_linkedin_crawl_starts_at_the_right_offset(monkeypatch):
    """LinkedIn 用 start offset 分頁 → 區間式的第 N 塊要從對應的 offset 開始。"""
    starts: list[int] = []

    def fake_fetch(tpr, start, location, geo_id):
        starts.append(start)
        return '<div class="base-card"></div>'

    monkeypatch.setattr(M, "fetch_list_page", fake_fetch)
    monkeypatch.setattr(M, "parse_list_page", lambda html: [])
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)

    M.crawl_list("r2592000", 3, location="Singapore", geo_id="102454443", start_page=2)
    assert starts == [M.PAGE_SIZE, 2 * M.PAGE_SIZE]


def test_the_linkedin_ranges_do_not_overlap(monkeypatch):
    """同樣的驗證, 換 LinkedIn。"""
    starts: list[int] = []

    def fake_fetch(tpr, start, location, geo_id):
        starts.append(start)
        return '<div class="base-card"></div>'

    monkeypatch.setattr(M, "fetch_list_page", fake_fetch)
    monkeypatch.setattr(M, "parse_list_page", lambda html: [])
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)

    for start, end in ((1, 2), (3, 4)):
        M.crawl_list("r2592000", end, location="Singapore", geo_id="102454443", start_page=start)
    assert starts == [0, M.PAGE_SIZE, 2 * M.PAGE_SIZE, 3 * M.PAGE_SIZE]
    assert len(starts) == len(set(starts))


@pytest.mark.parametrize("source", ["linkedin", "jobstreet"])
def test_every_active_source_accepts_the_page_span(source):
    """CLI 的 --start-page 對每個 source 都要能走 (不是只有 linkedin)。"""
    args = M.build_arg_parser().parse_args(["30d", "--source", source, "--start-page", "5"])
    assert args.start_page == 5


# ── 104 (TW) ────────────────────────────────────────────────────────────────
def test_the_104_crawl_honours_a_page_span():
    """104 的 adapter 也要支援區間式切塊 (v1.8.0)。"""
    from jobs_scraper.sources import onezerofour as OO

    pages: list[tuple[str, int]] = []

    def fake_hit(kw, p, isnew):
        pages.append((kw, p))
        return [{"jobNo": f"{kw}-{p}", "link": {"job": f"/job/x{p}"}, "title": "PM"}]

    OO.crawl_list("7d", 5, ["PM"], hit=fake_hit, start_page=3)
    assert [p for _, p in pages] == [3, 4, 5]


def test_the_104_crawl_paces_between_pages():
    """104 的 list API 之前完全沒有一般性的節奏 → 密集 burst 之後會 403。"""
    from jobs_scraper.sources import onezerofour as OO

    slept: list[str] = []

    def fake_hit(kw, p, isnew):
        return [{"jobNo": f"{kw}-{p}", "link": {"job": f"/job/x{p}"}, "title": "PM"}]

    OO.crawl_list("7d", 4, ["PM"], hit=fake_hit, sleep=slept.append)
    assert slept == ["list"] * 3  # 最後一頁之後不再睡


def test_the_104_crawl_still_crawls_from_page_one_by_default():
    from jobs_scraper.sources import onezerofour as OO

    pages: list[int] = []

    def fake_hit(kw, p, isnew):
        pages.append(p)
        return [{"jobNo": f"{kw}-{p}", "link": {"job": f"/job/x{p}"}, "title": "PM"}]

    OO.crawl_list("7d", 3, ["PM"], hit=fake_hit)
    assert pages == [1, 2, 3]


def test_the_engine_passes_the_page_span_to_the_104_crawl(monkeypatch):
    """CLI 的 --start-page 要真的送到 104 的 crawl。"""
    seen: list[int] = []

    def fake_crawl(daterange, max_pages, keywords=None, *, hit, sleep=None, start_page=1):
        seen.append(start_page)
        return []

    monkeypatch.setattr(M._onezerofour, "crawl_list", fake_crawl)
    M.crawl_onezerofour_list("7d", 5, keywords=["PM"], start_page=4)
    assert seen == [4]
