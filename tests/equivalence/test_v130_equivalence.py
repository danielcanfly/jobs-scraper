"""Behaviour-equivalence freeze gate for the v1.4.0 five-source contract.

The file name stays `test_v130_equivalence.py` because CI pins this exact path
(`.github/workflows/ci.yml`); the frozen baseline asserted below is v1.4.0.

v1.4.0 restored the five active sources (`linkedin`, `jobstreet`, `cake`,
`104` / `onezerofour`) and retired `jora` from active crawling while keeping
its read-only dedup helpers for historical rows.
"""

from __future__ import annotations

import ast
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest

import region_policy as RP
import runtime_core as RT
import server
import server_v1_1
import sg_product_jobs as M

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GOLDEN = json.loads((HERE / "v130_golden.json").read_text(encoding="utf-8"))

SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}


def _run(coro):
    try:
        previous = asyncio.get_event_loop()
    except RuntimeError:
        previous = None
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        if previous is not None and not previous.is_closed():
            asyncio.set_event_loop(previous)


def _parsed_url(url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}", dict(parse_qsl(parts.query, keep_blank_values=True))


def _tool_by_name(tools, name: str):
    return next(tool for tool in tools if tool.name == name)


def _repo_python_files() -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(".py"):
                found.append(Path(dirpath) / name)
    return sorted(found)


def _imports_removed_adapter_layer(path: Path) -> bool:
    """True when the file imports the removed `jobs_scraper/sources/` package."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        # A file that does not parse cannot import anything.
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "jobs_scraper.sources" or alias.name.startswith("jobs_scraper.sources."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "jobs_scraper.sources" or module.startswith("jobs_scraper.sources."):
                return True
            if module == "jobs_scraper" and any(alias.name == "sources" for alias in node.names):
                return True
    return False


def test_authorized_baseline_identity():
    assert GOLDEN["baseline"]["release"] == "v1.4.0"
    assert GOLDEN["baseline"]["authorized_delta"] == "restore-five-active-sources-keep-jora-retired"
    assert GOLDEN["baseline"]["parent_main"] == "2a240be6ae94b2d8de03bf7ddc7415f1ccb5d688"


def test_linkedin_url_contract():
    base, query = _parsed_url(M.build_list_url("r604800", 20, "Taiwan", "104187078"))
    assert base == GOLDEN["urls"]["linkedin_list_base"]
    assert query == GOLDEN["urls"]["linkedin_list_query"]
    assert M.build_jd_url("4430572342") == GOLDEN["urls"]["linkedin_jd"]


def test_linkedin_list_parser_contract():
    html = """
    <div class="base-card" data-entity-urn="urn:li:jobPosting:4430572342">
      <h3 class="base-search-card__title">Principal Product Manager</h3>
      <a class="hidden-nested-link">Acme AI</a>
      <span class="job-search-card__location">Singapore</span>
      <time datetime="2026-08-20">3 days ago</time>
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/4430572342"></a>
    </div>
    """
    jobs = M.parse_list_page(html)
    assert jobs == [
        {
            "job_id": "4430572342",
            "title": "Principal Product Manager",
            "company": "Acme AI",
            "location": "Singapore",
            "posted_at": "2026-08-20",
            "posted_ago": "3 days ago",
            "url": "https://www.linkedin.com/jobs/view/4430572342",
            "source": "linkedin",
        }
    ]


class _Response:
    status_code = 200
    text = '<div class="description__text"><p>Build products</p><li>Ship safely</li></div>'


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response()


def test_linkedin_jd_contract(monkeypatch):
    fake = _Session()
    monkeypatch.setattr(M, "_cc_session", fake)
    result = M.fetch_jd("4430572342")
    assert fake.calls[0][0] == GOLDEN["urls"]["linkedin_jd"]
    assert fake.calls[0][1]["timeout"] == 20
    assert result["error"] is None
    assert "Build products" in (result["jd_text"] or "")
    assert "Ship safely" in (result["jd_text"] or "")


def test_all_five_sources_are_active_cli_choices():
    parser = M.build_arg_parser()
    for source in GOLDEN["cli"]["source_choices"]:
        args = parser.parse_args(["7d", "--source", source])
        assert args.source == source


@pytest.mark.parametrize("source", ["jora", "unknown"])
def test_cli_rejects_non_active_sources(capsys, source):
    """`jora` is retired (site closed); unknown sources stay rejected."""
    parser = M.build_arg_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["7d", "--source", source])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert GOLDEN["cli"]["invalid_source_messages"][source] in err


def test_source_layer_duplication_is_gone():
    """The unused `jobs_scraper/sources/` adapter package was removed in v1.4.0."""
    assert not (ROOT / "jobs_scraper" / "sources").exists()
    for path in _repo_python_files():
        assert not _imports_removed_adapter_layer(path), path


@pytest.mark.parametrize(
    "symbol",
    [
        "build_jobstreet_list_url",
        "parse_jobstreet_list_page",
        "fetch_jobstreet_jd",
        "crawl_jobstreet_list",
        "build_cake_search_payload",
        "parse_cake_search_page",
        "fetch_cake_jd",
        "crawl_cake_list",
        "build_onezerofour_list_url",
        "parse_onezerofour_list_page",
        "fetch_onezerofour_jd",
        "crawl_onezerofour_list",
    ],
)
def test_restored_sources_are_owned_by_the_engine(symbol):
    """Every active source's URL building / list parsing / JD fetch lives in sg_product_jobs.py."""
    assert hasattr(M, symbol), symbol


@pytest.mark.parametrize(
    "symbol",
    [
        "build_jora_list_url",
        "parse_jora_list_page",
        "fetch_jora_jd",
        "crawl_jora_list",
    ],
)
def test_retired_jora_network_adapters_are_absent(symbol):
    assert not hasattr(M, symbol), symbol


def test_jora_back_compat_dedup_helpers_remain():
    """Jora stays retired from active crawling but historical rows must stay readable."""
    assert M.JORA_BASE == "https://sg.jora.com"
    assert M.build_e_formula("jora", "3edbbb646574ed2a0a926fee537b0e7c") == GOLDEN["legacy_formulas"]["jora"]
    assert M._infer_source_from_job_id("3edbbb646574ed2a0a926fee537b0e7c") == "jora"


def test_restored_source_url_contracts():
    base, query = _parsed_url(M.build_jobstreet_list_url("product manager", 1, "7d"))
    assert base == GOLDEN["urls"]["jobstreet_list_base"]
    assert query == GOLDEN["urls"]["jobstreet_list_query"]

    assert M.build_cake_detail_url("acme", "product-manager-123") == GOLDEN["urls"]["cake_detail"]

    base, query = _parsed_url(M.build_onezerofour_list_url("產品經理", 1, 7))
    assert base == GOLDEN["urls"]["onezerofour_list_base"]
    assert query == GOLDEN["urls"]["onezerofour_list_query"]


def test_legacy_rows_remain_readable():
    jora = [
        "New",
        "",
        "2026-08-22",
        "Jora / Minimax",
        "https://sg.jora.com/job/Foo-3edbbb646574ed2a0a926fee537b0e7c?tracking=abc",
    ]
    jobstreet = [
        "New",
        "",
        "2026-08-22",
        "JobStreet / Minimax",
        "https://sg.jobstreet.com/job/94145676",
    ]
    assert list(M.parse_sheet_row_to_key(jora)) == GOLDEN["legacy_rows"]["jora"]
    assert list(M.parse_sheet_row_to_key(jobstreet)) == GOLDEN["legacy_rows"]["jobstreet"]


def test_mcp_source_contract_remains_linkedin_only():
    """The MCP / tracker layer is still LinkedIn-only; the CLI engine owns the other four."""
    legacy = _run(server.mcp.list_tools())
    v11 = _run(server_v1_1.mcp.list_tools())
    assert sorted(t.name for t in legacy) == GOLDEN["mcp"]["legacy_tools"]
    assert sorted(t.name for t in v11) == GOLDEN["mcp"]["v11_tools"]

    for tools in (legacy, v11):
        crawl = _tool_by_name(tools, "crawl_jobs")
        source_schema = crawl.input_schema["properties"]["source"]
        allowed = source_schema.get("enum") or ([source_schema["const"]] if "const" in source_schema else [])
        assert allowed == GOLDEN["mcp"]["source_enum"]
        assert crawl.input_schema["properties"]["range"]["enum"] == GOLDEN["mcp"]["range_enum"]

    sync = _tool_by_name(v11, "sync_jobs_to_sheet")
    source_schema = sync.input_schema["properties"]["source"]
    allowed = source_schema.get("enum") or ([source_schema["const"]] if "const" in source_schema else [])
    assert allowed == GOLDEN["mcp"]["source_enum"]
    assert sync.input_schema["properties"]["region"]["enum"] == GOLDEN["mcp"]["region_enum"]


def test_mcp_source_type_and_labels_remain_linkedin_only():
    assert RT.Source.__args__ == ("linkedin",)
    assert RP.SOURCE_LABELS == {"linkedin": "LinkedIn / jobs-scraper"}
    assert all(policy.supported_sources == frozenset({"linkedin"}) for policy in RP.REGION_POLICIES.values())


@pytest.mark.parametrize("source", ["jora", "jobstreet", "cake", "104", "onezerofour", "unknown"])
def test_mcp_region_gate_fails_closed_for_non_linkedin_sources(source):
    """The MCP region gate still fails closed for every non-LinkedIn source."""
    ok, reason = RP.source_region_supported(source, "SG")
    assert ok is False
    assert reason == f"source={source!r} is not supported; supported source: linkedin"


def test_only_the_engine_knows_the_restored_source_hosts():
    engine = (ROOT / "sg_product_jobs.py").read_text(encoding="utf-8").lower()
    assert "sg.jobstreet.com" in engine
    assert "www.cake.me" in engine
    assert "www.104.com.tw" in engine

    for path in (ROOT / "server.py", ROOT / "server_v1_1.py", ROOT / "jobs_scraper/mcp_services/crawl.py"):
        src = path.read_text(encoding="utf-8").lower()
        assert "sg.jora.com" not in src
        assert "sg.jobstreet.com" not in src
