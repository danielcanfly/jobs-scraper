"""v1.8.0: per-source sleep 預算。

2026-11-24 實測: 抓取慢的主因是固定 sleep, 不是網路 ——
純網路 JobStreet list 0.80s / JobStreet JD 0.29s / LinkedIn list 0.92s,
但每次請求後都睡 3-10s → 整體 wall time 有 80% 是 sleep。

所以 v1.8.0 讓每個 source 有自己的請求節奏:
  - JobStreet 0.5-1.0s (壓力測試 0.5s / 200 reqs = 0 fail)
  - LinkedIn  1.5-3.0s (Guest API 會 429, 保守一點; 30/60/90 backoff 仍在)
  - Cake      維持 3-10s (2-5s 就 429)

這支測試把「節奏是 per-source 的」跟「env 可以覆寫」釘死,
免得後來又有人把所有 source 調回同一組。
"""

from __future__ import annotations

import importlib
import random

import pytest

import sg_product_jobs as M
from jobs_scraper.sources import jobstreet as JS
from jobs_scraper.sources import linkedin as LI


# ── 預設值 ────────────────────────────────────────────────────────────────────
def test_jobstreet_uses_a_much_tighter_budget_than_the_global_one():
    """JobStreet 的公開 API 對壓力很寬鬆 → 3-10s 是過度保守。"""
    assert JS.SLEEP_MIN == 0.5
    assert JS.SLEEP_MAX == 1.0
    assert JS.SLEEP_MAX < M.SLEEP_MIN


def test_linkedin_is_tighter_than_the_global_but_not_as_tight_as_jobstreet():
    """LinkedIn Guest API 會真的 429 → 只降到 1.5-3.0s, 不跟 JobStreet 一樣。"""
    assert LI.SLEEP_MIN == 1.5
    assert LI.SLEEP_MAX == 3.0
    # 上限已經落在全域的下緣, 平均更小
    assert LI.SLEEP_MAX <= M.SLEEP_MIN
    assert (LI.SLEEP_MIN + LI.SLEEP_MAX) / 2 < (M.SLEEP_MIN + M.SLEEP_MAX) / 2
    assert LI.SLEEP_MIN > JS.SLEEP_MIN


def test_cake_keeps_the_conservative_budget():
    """Cake 實測 2-5s 就 429 → 不能跟著降。"""
    assert M.CAKE_SLEEP_MIN == 3.0
    assert M.CAKE_SLEEP_MAX == 10.0


# ── env 覆寫 ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "module,prefix,default",
    [(JS, "JOBSTREET", (0.5, 1.0)), (LI, "LINKEDIN", (1.5, 3.0))],
)
def test_the_budget_can_be_overridden_from_the_environment(monkeypatch, module, prefix, default):
    monkeypatch.setenv(f"JOBS_SCRAPER_{prefix}_SLEEP_MIN", "0.25")
    monkeypatch.setenv(f"JOBS_SCRAPER_{prefix}_SLEEP_MAX", "0.75")
    reloaded = importlib.reload(module)
    try:
        assert (reloaded.SLEEP_MIN, reloaded.SLEEP_MAX) == (0.25, 0.75)
    finally:
        monkeypatch.undo()
        importlib.reload(module)


def test_a_malformed_environment_value_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_JOBSTREET_SLEEP_MIN", "not-a-number")
    reloaded = importlib.reload(JS)
    try:
        assert reloaded.SLEEP_MIN == 0.5
    finally:
        monkeypatch.undo()
        importlib.reload(JS)


def test_an_inverted_environment_range_is_swapped_not_rejected(monkeypatch):
    monkeypatch.setenv("JOBS_SCRAPER_JOBSTREET_SLEEP_MIN", "2.0")
    monkeypatch.setenv("JOBS_SCRAPER_JOBSTREET_SLEEP_MAX", "0.5")
    reloaded = importlib.reload(JS)
    try:
        assert (reloaded.SLEEP_MIN, reloaded.SLEEP_MAX) == (0.5, 2.0)
    finally:
        monkeypatch.undo()
        importlib.reload(JS)


# ── 引擎層: contextvar 決定節奏 ─────────────────────────────────────────────
def _sample_sleep(monkeypatch, source, label="list"):
    """攔截 human_sleep 實際算出來��秒數 (不真的睡)。"""
    got: list[float] = []
    real_uniform = random.uniform

    def fake_uniform(a, b):
        value = real_uniform(a, b)
        got.append(value)
        return value

    monkeypatch.setattr(M.random, "uniform", fake_uniform)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)
    token = M.use_source_sleep(source)
    try:
        M.human_sleep(label)
    finally:
        M._SLEEP_SOURCE.reset(token)
    return got[-1]


def test_the_engine_sleep_follows_the_source_being_crawled(monkeypatch):
    """同一個注入點, source 不同 → 節奏不同。"""
    js = _sample_sleep(monkeypatch, "jobstreet")
    li = _sample_sleep(monkeypatch, "linkedin")
    assert JS.SLEEP_MIN <= js <= JS.SLEEP_MAX
    assert LI.SLEEP_MIN <= li <= LI.SLEEP_MAX


def test_an_unknown_source_falls_back_to_the_global_budget(monkeypatch):
    got = _sample_sleep(monkeypatch, None)
    assert M.SLEEP_MIN <= got <= M.SLEEP_MAX


def test_the_engine_wrappers_delegate_to_their_adapter():
    """等價性契約: engine 的 *_jobstreet_* / *_linkedin_* 只能是薄包裝。"""
    assert M.jobstreet_human_sleep.__module__ == M.__name__
    assert M.linkedin_human_sleep.__module__ == M.__name__
    # 真正的實作住在 adapter
    assert hasattr(JS, "human_sleep")
    assert hasattr(LI, "human_sleep")


# ── crawl 真的會設定 source ──────────────────────────────────────────────────
def test_the_jobstreet_crawl_sets_the_jobstreet_budget(monkeypatch):
    seen: list[str] = []

    def fake_crawl(*args, **kwargs):
        seen.append(M._SLEEP_SOURCE.get())
        return []

    monkeypatch.setattr(M._jobstreet, "crawl_list", fake_crawl)
    M.crawl_jobstreet_list("30", 5, keywords=["product manager"])
    assert seen == ["jobstreet"]


def test_the_linkedin_crawl_sets_the_linkedin_budget(monkeypatch):
    seen: list[str] = []

    def fake_fetch(tpr, start, location, geo_id):
        seen.append(M._SLEEP_SOURCE.get())
        return '<div class="base-card"></div>'

    monkeypatch.setattr(M, "fetch_list_page", fake_fetch)
    monkeypatch.setattr(M, "parse_list_page", lambda html: [])
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M.time, "sleep", lambda _s: None)
    M.crawl_list("r2592000", 1)
    assert seen == ["linkedin"]


# ── 104 (TW) ────────────────────────────────────────────────────────────────
def test_the_104_source_has_its_own_budget():
    """104 的 detail API 很耐打 (2026-11-24 實測 59 筆 @0.3s 零失敗),
    但它的 list API 在密集 burst 之後會 403 → 用一組保守但比全域快的區間。"""
    from jobs_scraper.sources import onezerofour as OO

    assert OO.SLEEP_MIN == 1.0
    assert OO.SLEEP_MAX == 2.0
    assert OO.SLEEP_MAX < M.SLEEP_MIN
    # 104 比 JobStreet 更容易被 rate limit → 節奏不比 JobStreet 快
    assert OO.SLEEP_MIN >= JS.SLEEP_MAX
    assert OO.SLEEP_MAX > JS.SLEEP_MAX


def test_the_104_budget_can_be_overridden_from_the_environment(monkeypatch):
    from jobs_scraper.sources import onezerofour as OO

    monkeypatch.setenv("JOBS_SCRAPER_ONEZEROFOUR_SLEEP_MIN", "0.4")
    monkeypatch.setenv("JOBS_SCRAPER_ONEZEROFOUR_SLEEP_MAX", "0.9")
    reloaded = importlib.reload(OO)
    try:
        assert (reloaded.SLEEP_MIN, reloaded.SLEEP_MAX) == (0.4, 0.9)
    finally:
        monkeypatch.undo()
        importlib.reload(OO)


def test_the_engine_sleep_follows_the_104_source(monkeypatch):
    from jobs_scraper.sources import onezerofour as OO

    got = _sample_sleep(monkeypatch, "onezerofour")
    assert OO.SLEEP_MIN <= got <= OO.SLEEP_MAX


def test_the_104_crawl_sets_the_104_budget(monkeypatch):
    seen: list[str | None] = []

    def fake_crawl(*args, **kwargs):
        seen.append(M._SLEEP_SOURCE.get())
        return []

    monkeypatch.setattr(M._onezerofour, "crawl_list", fake_crawl)
    M.crawl_onezerofour_list("7d", 5, keywords=["PM"])
    assert seen == ["onezerofour"]
