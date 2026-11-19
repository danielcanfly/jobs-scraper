"""Regression tests for the generated Sheet-write worker code.

2026-11-19: the worker templates embedded their arguments with ``json.dumps``,
which produces JSON syntax inside generated *Python* source. ``json.dumps(None)``
is the bare token ``null``, so a worker built with the default ``gid=None`` died
with ``NameError: name 'null' is not defined`` before it ever reached Google.

``push_to_sheet`` only falls back to the in-process path when the subprocess
returns ``None``, so every run silently lost the subprocess timeout guard that
was added on 2026-08-29 and wrote the Sheet in-process instead.

Later the same day the jobs payload moved out of the generated source into its
own JSON file. A 30-page run serialises to megabytes, and CPython had to pull
that whole string literal through its tokenizer while the machine was already
memory-starved — the peak landed exactly on the Sheet write.

The fix embeds the arguments as Python literals (``_py_literal``) and reads the
payload from a file. These tests pin that down without touching Google: the
generated code is compiled, then executed against a stubbed engine module so
the forwarded arguments can be inspected.
"""

from __future__ import annotations

import json
import sys
import types

import sg_product_jobs as M


def _write_jobs(tmp_path, jobs) -> str:
    """Write the jobs payload the way the push worker expects to find it."""
    path = tmp_path / "jobs.payload.json"
    path.write_text(json.dumps(jobs, ensure_ascii=False, default=str), encoding="utf-8")
    return str(path)


def _install_stub_engine(monkeypatch, calls):
    """Install a stub `sg_product_jobs` module for the generated worker to import."""
    fake = types.ModuleType("sg_product_jobs")

    def push_to_sheet(
        jobs,
        sheet_url,
        sa_key_path=None,
        source=None,
        dry_run=False,
        timeout_s=0,
        gid=None,
        location=None,
    ):
        calls["push"] = {
            "jobs": jobs,
            "sheet_url": sheet_url,
            "sa_key_path": sa_key_path,
            "source": source,
            "timeout_s": timeout_s,
            "gid": gid,
            "location": location,
        }
        return {"written": len(jobs)}

    def _load_sheet_keys_for_source(sheet_source_label, sa_key_path="", sheet_id=""):
        calls["pre_dedup"] = {
            "sheet_source_label": sheet_source_label,
            "sa_key_path": sa_key_path,
        }
        return {("linkedin", "1")}, 2

    fake.push_to_sheet = push_to_sheet
    fake._load_sheet_keys_for_source = _load_sheet_keys_for_source
    monkeypatch.setitem(sys.modules, "sg_product_jobs", fake)
    return fake


def _run_worker(code: str, out_path):
    """Execute a generated worker and return the JSON it wrote to `out_path`."""
    saved_path = list(sys.path)
    try:
        namespace = {"__name__": "__generated_worker__"}
        exec(compile(code, "<generated-worker>", "exec"), namespace)
    finally:
        sys.path[:] = saved_path
    return json.loads(out_path.read_text(encoding="utf-8"))


def test_py_literal_emits_python_syntax_not_json():
    assert M._py_literal(None) == "None"
    assert M._py_literal(True) == "True"
    assert M._py_literal(False) == "False"
    assert M._py_literal(123) == "123"
    assert M._py_literal("linkedin") == "'linkedin'"


def test_py_literal_never_emits_a_json_only_token():
    """`null` / `true` / `false` are valid JSON but undefined names in Python."""
    for value in (None, True, False):
        assert M._py_literal(value) not in {"null", "true", "false"}


def test_push_worker_code_compiles_with_the_default_gid(tmp_path):
    """`--gid` defaults to None, so this is the shape every run actually built."""
    jobs_path = _write_jobs(tmp_path, [])
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", "/tmp/out.json"
    )
    compile(code, "<generated-worker>", "exec")


def test_push_worker_code_compiles_with_a_none_location(tmp_path):
    jobs_path = _write_jobs(tmp_path, [])
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", None, None, "/tmp/out.json"
    )
    compile(code, "<generated-worker>", "exec")


def test_push_worker_code_never_embeds_a_bare_json_null(tmp_path):
    jobs_path = _write_jobs(tmp_path, [])
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", "/tmp/out.json"
    )
    assert "gid=None" in code
    assert "gid=null" not in code


def test_push_worker_code_stays_small_for_a_large_payload(tmp_path):
    """The jobs payload must not be embedded in the generated source any more.

    A 30-page run serialises to megabytes; CPython used to pull that whole
    string literal through its tokenizer, which is a memory spike landing on
    the Sheet write of an already memory-starved machine.
    """
    jobs = [{"job_id": str(i), "title": "Product Manager", "jd_text": "x" * 5000} for i in range(500)]
    jobs_path = _write_jobs(tmp_path, jobs)
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", "/tmp/out.json"
    )
    assert len(code) < 4096, f"generated worker source is {len(code)} bytes; the payload leaked back in"


def test_push_worker_runs_and_forwards_the_default_gid(monkeypatch, tmp_path):
    calls: dict = {}
    _install_stub_engine(monkeypatch, calls)
    out_path = tmp_path / "push.out"
    jobs_path = _write_jobs(tmp_path, [{"job_id": "1", "title": "Product Manager"}])
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", str(out_path)
    )
    result = _run_worker(code, out_path)
    assert result["ok"] is True, result
    assert calls["push"]["gid"] is None
    assert calls["push"]["location"] == "Singapore"
    assert calls["push"]["jobs"] == [{"job_id": "1", "title": "Product Manager"}]


def test_push_worker_runs_with_an_explicit_gid(monkeypatch, tmp_path):
    calls: dict = {}
    _install_stub_engine(monkeypatch, calls)
    out_path = tmp_path / "push.out"
    jobs_path = _write_jobs(tmp_path, [])
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", 424242, "Singapore", str(out_path)
    )
    result = _run_worker(code, out_path)
    assert result["ok"] is True, result
    assert calls["push"]["gid"] == 424242


def test_push_worker_survives_a_title_with_quotes_and_newlines(monkeypatch, tmp_path):
    """A JD text with quotes must not break out of the generated literal."""
    calls: dict = {}
    _install_stub_engine(monkeypatch, calls)
    out_path = tmp_path / "push.out"
    tricky = 'Ship "it"\\safely\nnow'
    jobs_path = _write_jobs(tmp_path, [{"job_id": "1", "title": tricky}])
    code = M._build_push_worker_code(
        jobs_path, "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", str(out_path)
    )
    result = _run_worker(code, out_path)
    assert result["ok"] is True, result
    assert calls["push"]["jobs"][0]["title"] == tricky


def test_pre_dedup_worker_code_compiles_and_runs(monkeypatch, tmp_path):
    calls: dict = {}
    _install_stub_engine(monkeypatch, calls)
    out_path = tmp_path / "pre_dedup.out"
    code = M._build_pre_dedup_worker_code("LinkedIn / Minimax", "/tmp/sa.json", str(out_path))
    result = _run_worker(code, out_path)
    assert result["ok"] is True, result
    assert calls["pre_dedup"]["sheet_source_label"] == "LinkedIn / Minimax"
    assert calls["pre_dedup"]["sa_key_path"] == "/tmp/sa.json"
