"""v1.8.1: 節奏的 source 要傳到真正跑 pacing 的 thread。

v1.8.0 的缺口 (2026-11-24 跑 TW 7d 才抓到):

  104 的 list paging 跑在 adapter 自己的 ThreadPoolExecutor worker 裡, 而
  Python 3.11 的新 thread **不繼承主執行緒的 contextvars** → 引擎在主執行緒
  set 的 _SLEEP_SOURCE, 在 worker 裡讀不到 → v1.8.0 宣稱的 104 1.0-2.0s
  從來沒生效過, 104 的 list 一直落回全域 3-10s。

  實測 (TW 7d chunk 1): list 的 sleep 是 4.8 / 6.8 / 9.4 / 4.9 / 3.2 秒 →
  全域 3-10s, 不是 104 的 1.0-2.0s。而同一輪的 JD sleep 是 1.5-1.7 秒
  → 104 的值 (JD worker 自己 set 了 source)。

  v1.8.0 的單元測試 (test_the_104_crawl_sets_the_104_budget) 把 crawl_list
  整個 stub 掉 → 讀到的是**主執行緒**的 contextvar → 測試過關但行為是錯的。
  這支測試就是補那個缺口: 直接走 adapter 的真實 worker 路徑。

另外, 104 的 list API 對「同時併發的請求數」敏感, 不是對單一請求的間隔:

  8 workers × 1.0-2.0s = 聚合 2.1 req/s → 開頭就 403 (靠 30/60/90 backoff 救回)
  1 worker  × 1.0-2.0s = 聚合 0.5-1.0 req/s → 50 頁 1,010 筆 0 失敗

所以區間要按「總請求率」選: 單 keyword 用 104 自己的 1.0-2.0s,
多 keyword 平行維持全域 3-10s (聚合 ~1.2 req/s, 104 一直以來跑得動的速率)。
"""

from __future__ import annotations

import threading

import sg_product_jobs as M
from jobs_scraper.sources import onezerofour as OO


def _capture_sleeps(monkeypatch) -> list[tuple[float, bool]]:
    """攔 M.time.sleep, 回傳 [(秒數, 是否在主執行緒)]。"""
    seen: list[tuple[float, bool]] = []

    def fake_sleep(seconds: float) -> None:
        seen.append((seconds, threading.current_thread() is threading.main_thread()))

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    return seen


def _fake_hit(monkeypatch) -> None:
    """讓 adapter 的 hit 回空清單 — 只為了讓 worker 有東西跑、pacing 有被觸發。"""

    def fake_hit(*args, **kwargs):
        return []

    monkeypatch.setattr(M, "hit_onezerofour_list", fake_hit)


# ── 單 keyword (supervisor 每個塊只跑一個 keyword) ───────────────────────────
def test_the_104_list_worker_uses_the_104_budget(monkeypatch):
    """單 keyword → worker 裡的 pacing 必須落在 104 自己的 1.0-2.0s。"""
    seen = _capture_sleeps(monkeypatch)
    _fake_hit(monkeypatch)

    M.crawl_onezerofour_list("7d", 3, keywords=["PM"])

    assert seen, "adapter 應該在頁與頁之間至少睡一次"
    assert all(not in_main for _, in_main in seen), "pacing 必須發生在 worker thread 裡"
    for seconds, _ in seen:
        assert OO.SLEEP_MIN <= seconds <= OO.SLEEP_MAX


def test_the_sleep_source_is_set_inside_the_worker_thread(monkeypatch):
    """v1.8.0 的缺口本體: 主執行緒 set 了, worker 裡讀不到。"""
    observed: list[str | None] = []

    def fake_sleep(seconds: float) -> None:
        observed.append(M._SLEEP_SOURCE.get())

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    _fake_hit(monkeypatch)

    M.crawl_onezerofour_list("7d", 3, keywords=["PM"])

    assert observed, "pacing 應該有被觸發"
    assert all(src == "onezerofour" for src in observed), observed


def test_the_single_keyword_104_list_is_not_paced_at_the_global_rate(monkeypatch):
    """全域 3-10s 是 104 落回預設值時的樣子 → 單 keyword 不能長那樣。"""
    seen = _capture_sleeps(monkeypatch)
    _fake_hit(monkeypatch)

    M.crawl_onezerofour_list("7d", 3, keywords=["PM"])

    for seconds, _ in seen:
        assert not (M.SLEEP_MIN <= seconds <= M.SLEEP_MAX)


# ── 多 keyword 平行 (engine 預設 8 workers) ───────────────────────────────────
def test_the_parallel_104_list_keeps_the_conservative_global_budget(monkeypatch):
    """8 workers 同時打 → 聚合率要壓在 104 容忍的範圍 → 維持全域 3-10s。"""
    seen = _capture_sleeps(monkeypatch)
    _fake_hit(monkeypatch)

    M.crawl_onezerofour_list("7d", 3, keywords=["PM", "Product Manager"])

    assert seen
    for seconds, _ in seen:
        assert M.SLEEP_MIN <= seconds <= M.SLEEP_MAX


def test_the_parallel_104_list_does_not_claim_the_104_budget(monkeypatch):
    """平行路徑的 source 要是 None (→ 全域), 不是 onezerofour。"""
    observed: list[str | None] = []

    def fake_sleep(seconds: float) -> None:
        observed.append(M._SLEEP_SOURCE.get())

    monkeypatch.setattr(M.time, "sleep", fake_sleep)
    _fake_hit(monkeypatch)

    M.crawl_onezerofour_list("7d", 3, keywords=["PM", "Product Manager"])

    assert observed
    assert all(src is None for src in observed), observed


# ── 前提 ──────────────────────────────────────────────────────────────────────
def test_the_two_budgets_do_not_overlap():
    """兩個區間必須錯開 → 否則「用哪一個」這個判斷沒有意义。"""
    assert OO.SLEEP_MAX < M.SLEEP_MIN
