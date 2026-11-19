"""Regression tests for the generated Sheet-write worker code.

2026-11-19: the worker templates embedded their arguments with ``json.dumps``,
which produces JSON syntax inside generated *Python* source. ``json.dumps(None)``
is the bare token ``null``, so a worker built with the default ``gid=None`` died
with ``NameError: name 'null' is not defined`` before it ever reached Google.

``push_to_sheet`` only falls back to the in-process path when the subprocess
returns ``None``, so every run silently lost the subprocess timeout guard that
was added on 2026-08-29 and wrote the Sheet in-process instead.

The fix embeds the arguments as Python literals (``_py_literal``). These tests
pin that down without touching Google: the generated code is compiled, and then
executed against a stubbed engine module so the forwarded arguments can be
inspected.
"""

from __future__ import annotations

import json
import sys
import types

import sg_product_jobs as M


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


def test_push_worker_code_compiles_with_the_default_gid():
    """`--gid` defaults to None, so this is the shape every run actually built."""
    code = M._build_push_worker_code(
        [], "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", "/tmp/out.json"
    )
    compile(code, "<generated-worker>", "exec")


def test_push_worker_code_compiles_with_a_none_location():
    code = M._build_push_worker_code([], "https://example", "/tmp/sa.json", "linkedin", None, None, "/tmp/out.json")
    compile(code, "<generated-worker>", "exec")


def test_push_worker_code_never_embeds_a_bare_json_null():
    code = M._build_push_worker_code(
        [], "https://example", "/tmp/sa.json", "linkedin", None, "Singapore", "/tmp/out.json"
    )
    assert "gid=None" in code
    assert "gid=null" not in code


def test_push_worker_runs_and_forwards_the_default_gid(monkeypatch, tmp_path):
    calls: dict = {}
    _install_stub_engine(monkeypatch, calls)
    out_path = tmp_path / "push.out"
    code = M._build_push_worker_code(
        [{"job_id": "1", "title": "Product Manager"}],
        "https://example",
        "/tmp/sa.json",
        "linkedin",
        None,
        "Singapore",
        str(out_path),
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
    code = M._build_push_worker_code(
        [], "https://example", "/tmp/sa.json", "linkedin", 424242, "Singapore", str(out_path)
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
    code = M._build_push_worker_code(
        [{"job_id": "1", "title": tricky}],
        "https://example",
        "/tmp/sa.json",
        "linkedin",
        None,
        "Singapore",
        str(out_path),
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
