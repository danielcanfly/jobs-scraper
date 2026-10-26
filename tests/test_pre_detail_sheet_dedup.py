"""Characterization tests: pre-detail sheet dedup.

``pre_dedup_jobs_against_sheet`` reads the (source, job_id) keys already in the
Sheet *before* the detail fetch, so a re-run does not pay for jobs that are
already written.

Two invariants are pinned:

* **fail-safe** — any Sheet read failure (network / auth / timeout) must let
  the whole job list through; the run must not be blocked.
* **skipped under --refetch** — main() only calls the helper when
  ``--with-jd`` is given and ``--refetch`` is *not*.

No test touches the real Google Sheet: the gspread loader is replaced by a
fake, and main() is driven with every I/O boundary faked out.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402


def _job(job_id, source="onezerofour", **overrides):
    job = {
        "job_id": job_id,
        "title": "Product Manager",
        "company": "Acme Ltd",
        "location": "台北市信義區",
        "source": source,
        "url": f"https://www.104.com.tw/job/{job_id}",
        "jd_text": "JD body",
    }
    job.update(overrides)
    return job


def _jobs():
    return [_job("aaa11"), _job("bbb22"), _job("ccc33")]


# ── filtering ───────────────────────────────────────────────────────────────
def test_jobs_already_in_the_sheet_are_dropped(monkeypatch):
    monkeypatch.setattr(
        M,
        "_load_sheet_keys_for_source",
        lambda label, sa_key_path="", sheet_id="": ({("onezerofour", "bbb22")}, 10),
    )
    out = M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=0)
    assert [j["job_id"] for j in out] == ["aaa11", "ccc33"]


def test_order_is_preserved(monkeypatch):
    monkeypatch.setattr(
        M,
        "_load_sheet_keys_for_source",
        lambda label, sa_key_path="", sheet_id="": ({("onezerofour", "aaa11")}, 10),
    )
    out = M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=0)
    assert [j["job_id"] for j in out] == ["bbb22", "ccc33"]


def test_source_is_part_of_the_key(monkeypatch):
    """Same job_id under a different source is NOT a duplicate."""
    monkeypatch.setattr(
        M,
        "_load_sheet_keys_for_source",
        lambda label, sa_key_path="", sheet_id="": ({("jobstreet", "aaa11")}, 10),
    )
    out = M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=0)
    assert [j["job_id"] for j in out] == ["aaa11", "bbb22", "ccc33"]


def test_job_id_is_stringified_before_matching(monkeypatch):
    monkeypatch.setattr(
        M,
        "_load_sheet_keys_for_source",
        lambda label, sa_key_path="", sheet_id="": ({("jobstreet", "94145676")}, 10),
    )
    jobs = [_job(94145676, source="jobstreet")]
    out = M.pre_dedup_jobs_against_sheet(jobs, "JobStreet / Minimax", timeout_s=0)
    assert out == []


def test_the_sheet_source_label_is_forwarded_to_the_loader(monkeypatch):
    seen: list[str] = []

    def fake_loader(label, sa_key_path="", sheet_id=""):
        seen.append(label)
        return set(), 2

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", fake_loader)
    M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=0)
    assert seen == ["104 / Minimax"]


# ── fail-safe ───────────────────────────────────────────────────────────────
def test_sheet_read_failure_does_not_block_the_run(monkeypatch):
    """In-process read error => every job passes through untouched."""

    def boom(label, sa_key_path="", sheet_id=""):
        raise RuntimeError("google sheets unreachable")

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", boom)
    jobs = _jobs()
    out = M.pre_dedup_jobs_against_sheet(jobs, "104 / Minimax", timeout_s=0)
    assert out == jobs
    assert len(out) == 3


def test_sheet_read_failure_is_reported_but_not_raised(monkeypatch, capsys):
    def boom(label, sa_key_path="", sheet_id=""):
        raise RuntimeError("boom")

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", boom)
    M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=0)
    assert "PRE-DEDUP WARN" in capsys.readouterr().out


def test_subprocess_read_failure_does_not_block_the_run(monkeypatch):
    """The production path (subprocess) must be fail-safe too."""
    monkeypatch.setattr(M, "_pre_dedup_load_with_subprocess", lambda label, key, timeout: (set(), False))
    jobs = _jobs()
    out = M.pre_dedup_jobs_against_sheet(jobs, "104 / Minimax", timeout_s=60)
    assert out == jobs


def test_subprocess_timeout_is_fail_safe(monkeypatch):
    """A timed-out subprocess read returns an empty key set, not an exception."""
    monkeypatch.setattr(M, "_pre_dedup_load_with_subprocess", lambda label, key, timeout: (set(), False))
    out = M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=1)
    assert len(out) == 3


def test_subprocess_path_is_used_when_timeout_is_positive(monkeypatch):
    calls: list[tuple] = []

    def fake_loader(label, key, timeout):
        calls.append((label, key, timeout))
        return {("onezerofour", "aaa11")}, 5

    monkeypatch.setattr(M, "_pre_dedup_load_with_subprocess", fake_loader)
    out = M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", sa_key_path="fake-key.json", timeout_s=60)
    assert calls == [("104 / Minimax", "fake-key.json", 60)]
    assert [j["job_id"] for j in out] == ["bbb22", "ccc33"]


def test_in_process_path_is_used_when_timeout_is_zero(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(M, "_pre_dedup_load_with_subprocess", lambda *a: calls.append(a) or (set(), True))
    monkeypatch.setattr(M, "_load_sheet_keys_for_source", lambda label, sa_key_path="", sheet_id="": (set(), 2))
    M.pre_dedup_jobs_against_sheet(_jobs(), "104 / Minimax", timeout_s=0)
    assert calls == []


# ── trivial short-circuits ──────────────────────────────────────────────────
def test_dry_run_never_reads_the_sheet(monkeypatch):
    def boom(label, sa_key_path="", sheet_id=""):
        raise AssertionError("dry run must not read the sheet")

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", boom)
    monkeypatch.setattr(
        M,
        "_pre_dedup_load_with_subprocess",
        lambda *a: (_ for _ in ()).throw(AssertionError("dry run must not read the sheet")),
    )
    jobs = _jobs()
    assert M.pre_dedup_jobs_against_sheet(jobs, "104 / Minimax", dry_run=True) == jobs


def test_empty_job_list_short_circuits(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not read the sheet for an empty list")

    monkeypatch.setattr(M, "_load_sheet_keys_for_source", boom)
    monkeypatch.setattr(M, "_pre_dedup_load_with_subprocess", boom)
    assert M.pre_dedup_jobs_against_sheet([], "104 / Minimax") == []


# ── main() integration: skipped under --refetch ─────────────────────────────
def _run_main(monkeypatch, tmp_path, extra_argv, with_jd=True):
    """Drive main() with the crawl / JD / sheet layers faked out."""
    calls: list[dict] = []

    def fake_crawl(daterange, max_pages, keywords=None):
        return [_job("aaa11")]

    def fake_pre_dedup(jobs, sheet_source_label, **kwargs):
        calls.append({"jobs": list(jobs), "label": sheet_source_label, **kwargs})
        return jobs

    def fake_enrich(jobs, **kwargs):
        return jobs, {"total": len(jobs), "skipped": 0, "cached": 0, "fetched": 0, "failed": 0}

    def unreachable(*a, **k):
        # Any other source crawler reaching main() means the routing regressed;
        # fail loudly instead of letting a real request escape.
        raise AssertionError("a non-104 crawler was dispatched")

    monkeypatch.setattr(M, "crawl_onezerofour_list", fake_crawl)
    monkeypatch.setattr(M, "pre_dedup_jobs_against_sheet", fake_pre_dedup)
    monkeypatch.setattr(M, "enrich_with_jd", fake_enrich)
    monkeypatch.setattr(M, "load_jd_cache_from_jsons", lambda **kw: {})
    monkeypatch.setattr(M, "load_seen_ids", lambda *a, **k: set())
    monkeypatch.setattr(M, "crawl_list", unreachable)
    monkeypatch.setattr(M, "crawl_jobstreet_list", unreachable)
    monkeypatch.setattr(M, "crawl_cake_list", unreachable)
    monkeypatch.chdir(tmp_path)
    argv = ["sg_product_jobs.py", "1h", "--source", "104"]
    if with_jd:
        argv.append("--with-jd")
    monkeypatch.setattr(sys, "argv", argv + extra_argv)
    M.main()
    return calls


def test_pre_dedup_runs_without_refetch(monkeypatch, tmp_path):
    calls = _run_main(monkeypatch, tmp_path, [])
    assert len(calls) == 1
    assert calls[0]["label"] == "104 / Minimax"
    assert calls[0]["dry_run"] is False
    assert [j["job_id"] for j in calls[0]["jobs"]] == ["aaa11"]


def test_pre_dedup_is_skipped_under_refetch(monkeypatch, tmp_path):
    calls = _run_main(monkeypatch, tmp_path, ["--refetch"])
    assert calls == []


def test_pre_dedup_is_skipped_without_with_jd(monkeypatch, tmp_path):
    calls = _run_main(monkeypatch, tmp_path, [], with_jd=False)
    assert calls == []
