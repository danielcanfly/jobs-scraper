from __future__ import annotations

import asyncio
import json
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


def test_authorized_baseline_identity():
    assert GOLDEN["baseline"]["release"] == "v1.3.0"
    assert GOLDEN["baseline"]["authorized_delta"] == "retire-jora-jobstreet-active-sources"
    assert GOLDEN["baseline"]["parent_main"] == "2bd40f0f169cc17b0cf57b166b11759e69790278"


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


def test_retired_network_adapters_are_absent():
    assert not (ROOT / "jobs_scraper/sources/jora.py").exists()
    assert not (ROOT / "jobs_scraper/sources/jobstreet.py").exists()
    for symbol in (
        "build_jora_list_url",
        "parse_jora_list_page",
        "fetch_jora_jd",
        "crawl_jora_list",
        "build_jobstreet_list_url",
        "parse_jobstreet_list_page",
        "fetch_jobstreet_jd",
        "crawl_jobstreet_list",
    ):
        assert not hasattr(M, symbol), symbol


@pytest.mark.parametrize("source", ["jora", "jobstreet", "unknown"])
def test_retired_sources_fail_closed(source):
    ok, reason = RP.source_region_supported(source, "SG")
    assert ok is False
    assert reason == f"source={source!r} is not supported; supported source: linkedin"
    with pytest.raises(ValueError, match="supported source: linkedin"):
        M.build_e_formula(source, "123", "")


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


def test_mcp_source_contract_is_linkedin_only():
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


def test_source_type_and_labels_are_linkedin_only():
    assert RT.Source.__args__ == ("linkedin",)
    assert RP.SOURCE_LABELS == {"linkedin": "LinkedIn / jobs-scraper"}
    assert all(policy.supported_sources == frozenset({"linkedin"}) for policy in RP.REGION_POLICIES.values())


def test_no_retired_source_network_text_in_current_entrypoints():
    for path in (ROOT / "server.py", ROOT / "server_v1_1.py", ROOT / "jobs_scraper/mcp_services/crawl.py"):
        src = path.read_text(encoding="utf-8").lower()
        assert "sg.jora.com" not in src
        assert "sg.jobstreet.com" not in src
