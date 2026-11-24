"""v1.8.0: 平行抓 JD。

2026-11-24 實測: 抓 JD 原本是 `for` 迴圈逐筆抓, 完全串行 →
每筆的固定 sleep 會全部疊成 wall time。
改成 ThreadPoolExecutor 後, 網路 I/O 釋放 GIL, threads 真的能疊請求。

執行緒安全的邊界是這支測試的重點:
  - worker 只做「網路 I/O + 印進度」
  - append_seen (seen_jds.jsonl)、stats、out 全部在主線程處理
    → seen file 不會 interleaving, out 的順序 == 輸入順序 (Sheet row 順序不會亂)
"""

from __future__ import annotations

import threading
import time

import sg_product_jobs as M


def _jobs(n: int, source: str = "linkedin") -> list[dict]:
    return [
        {
            "source": source,
            "job_id": f"{source}-{i}",
            "title": "Product Manager",
            "company": "Example",
        }
        for i in range(n)
    ]


def _fake_fetch_jd(calls: list[str], delay: float = 0.0, fail_ids: set[str] | None = None):
    fail_ids = fail_ids or set()

    def fetch(job_id: str) -> dict:
        calls.append(job_id)
        if delay:
            time.sleep(delay)
        if job_id in fail_ids:
            return {"jd_text": None, "jd_lines": None, "error": "boom"}
        return {
            "jd_text": f"JD for {job_id}",
            "jd_lines": ["line"],
            "company": "Example",
            "location": "Singapore",
            "error": None,
        }

    return fetch


# ── 平行 vs 串行 ─────────────────────────────────────────────────────────────
def test_the_parallel_path_keeps_the_input_order(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(M, "fetch_jd", _fake_fetch_jd(calls))
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 3)

    jobs = [{"source": "linkedin", "job_id": f"j{i}", "title": "PM"} for i in range(12)]
    results = M._fetch_jds(jobs)

    assert len(results) == 12
    assert [r["jd_text"] for r in results] == [f"JD for j{i}" for i in range(12)]


def test_the_workers_actually_overlap(monkeypatch):
    """平行是真的平行, 不是假裝。"""
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 4)

    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_fetch(job_id: str) -> dict:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"jd_text": "x", "jd_lines": ["l"], "error": None}

    monkeypatch.setattr(M, "fetch_jd", fake_fetch)
    M._fetch_jds([{"source": "linkedin", "job_id": f"j{i}", "title": "PM"} for i in range(8)])
    assert peak > 1


def test_one_worker_stays_sequential(monkeypatch):
    """JD_FETCH_WORKERS=1 → 完全串行 (舊行為, 保守模式)。"""
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 1)

    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_fetch(job_id: str) -> dict:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {"jd_text": "x", "jd_lines": ["l"], "error": None}

    monkeypatch.setattr(M, "fetch_jd", fake_fetch)
    M._fetch_jds([{"source": "linkedin", "job_id": f"j{i}", "title": "PM"} for i in range(4)])
    assert peak == 1


def test_an_empty_batch_makes_no_call(monkeypatch):
    monkeypatch.setattr(M, "fetch_jd", _fake_fetch_jd([]))
    assert M._fetch_jds([]) == []


def test_the_worker_inherits_the_source_pacing(monkeypatch):
    """worker 是在新 thread → contextvar 必須自己設, 否則會用全域節奏。"""
    seen: list[str | None] = []

    def fake_fetch(job_id: str) -> dict:
        seen.append(M._SLEEP_SOURCE.get())
        return {"jd_text": "x", "jd_lines": ["l"], "error": None}

    monkeypatch.setattr(M, "fetch_jobstreet_jd", fake_fetch)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 2)
    # 至少 2 筆才會走平行路徑 (workers = min(JD_FETCH_WORKERS, n_total))
    M._fetch_jds(
        [
            {"source": "jobstreet", "job_id": "j0", "title": "PM"},
            {"source": "jobstreet", "job_id": "j1", "title": "PM"},
        ]
    )
    assert seen == ["jobstreet", "jobstreet"]


# ── enrich_with_jd: 狀態寫入仍在主線程 ───────────────────────────────────────
def test_the_seen_file_is_only_written_from_the_main_thread(monkeypatch):
    """seen_jds.jsonl 是 dedup 的命脈 → 不能讓多個 thread 同時 append。"""
    threads: list[int] = []
    monkeypatch.setattr(M, "fetch_jd", _fake_fetch_jd([]))
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 3)

    def fake_append(*args, **kwargs):
        threads.append(threading.get_ident())

    monkeypatch.setattr(M, "append_seen", fake_append)
    M.enrich_with_jd(_jobs(6), seen_ids=set())

    assert len(threads) == 6
    assert set(threads) == {threading.get_ident()}


def test_the_output_order_matches_the_input_order(monkeypatch):
    monkeypatch.setattr(M, "fetch_jd", _fake_fetch_jd([]))
    monkeypatch.setattr(M, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 4)

    jobs = _jobs(10)
    out, stats = M.enrich_with_jd(jobs, seen_ids=set())
    assert [j["job_id"] for j in out] == [j["job_id"] for j in jobs]
    assert stats["fetched"] == 10
    assert stats["failed"] == 0


def test_a_failed_fetch_is_recorded_not_raised(monkeypatch):
    monkeypatch.setattr(M, "fetch_jd", _fake_fetch_jd([], fail_ids={"linkedin-2"}))
    monkeypatch.setattr(M, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 2)

    out, stats = M.enrich_with_jd(_jobs(4), seen_ids=set())
    assert stats["fetched"] == 3
    assert stats["failed"] == 1
    failed = [j for j in out if j.get("jd_error")]
    assert len(failed) == 1
    assert failed[0]["job_id"] == "linkedin-2"


def test_skipped_and_cached_jobs_are_never_fetched(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(M, "fetch_jd", _fake_fetch_jd(calls))
    monkeypatch.setattr(M, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(M, "human_sleep", lambda label: None)
    monkeypatch.setattr(M, "JD_FETCH_WORKERS", 3)

    jobs = [
        {"source": "linkedin", "job_id": "skip-me", "title": "Account Manager"},
        {"source": "linkedin", "job_id": "cached", "title": "Product Manager", "jd_text": "in memory"},
        {"source": "linkedin", "job_id": "fetch-me", "title": "Product Manager"},
    ]
    json_cache = {("linkedin", "json-cached"): {"jd_text": "from json", "jd_lines": ["l"], "jd_hash": "h"}}
    jobs.append({"source": "linkedin", "job_id": "json-cached", "title": "Product Manager"})

    out, stats = M.enrich_with_jd(jobs, seen_ids=set(), json_cache=json_cache)

    assert calls == ["fetch-me"]
    assert stats["skipped"] == 1
    assert stats["cached"] == 2
    assert stats["fetched"] == 1
    assert [j["job_id"] for j in out] == [j["job_id"] for j in jobs]


def test_the_default_worker_count_is_not_one():
    """預設要是平行, 否則這個改動等於沒做。"""
    assert M.JD_FETCH_WORKERS >= 2
