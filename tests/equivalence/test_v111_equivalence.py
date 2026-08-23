from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import job_tracker as JT
import server
import server_v1_1
import sg_product_jobs as M

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "v111_golden.json").read_text(encoding="utf-8"))


def _normalized_query_sha(query: str) -> str:
    normalized = " ".join(query.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _parsed_url(url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(url)
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    return base, dict(parse_qsl(parts.query, keep_blank_values=True))


def test_baseline_identity_is_explicit():
    assert GOLDEN["baseline"] == {
        "tag": "v1.1.1",
        "commit": "8fbf32484418c2d5edd1fc1e0e451232515dadd8",
        "tree": "f0ba649aa4d989fceffa51b14c49a1f4b7e311c4",
    }


def test_source_url_and_graphql_contract():
    linkedin = M.build_list_url("r604800", 20, "Taiwan", "104187078")
    li_base, li_query = _parsed_url(linkedin)
    assert li_base == GOLDEN["urls"]["linkedin_list_base"]
    assert li_query == GOLDEN["urls"]["linkedin_list_query"]
    assert M.build_jd_url("4430572342") == GOLDEN["urls"]["linkedin_jd"]
    assert M.build_jora_list_url("7d", 3, "product manager", "Singapore") == GOLDEN["urls"]["jora_list"]
    assert M.build_jobstreet_list_url("product manager", 2, "7") == GOLDEN["urls"]["jobstreet_list"]
    assert M.JOBSTREET_GRAPHQL == GOLDEN["urls"]["jobstreet_graphql_endpoint"]
    assert _normalized_query_sha(M.JOBSTREET_DETAIL_QUERY) == GOLDEN["urls"]["jobstreet_graphql_normalized_sha256"]


def test_linkedin_list_parser_characterization():
    html = """
    <div class="base-card" data-entity-urn="urn:li:jobPosting:4430572342">
      <h3 class="base-search-card__title">Principal Product Manager</h3>
      <a class="hidden-nested-link">Acme AI</a>
      <span class="job-search-card__location">Singapore</span>
      <time datetime="2026-08-20">3 days ago</time>
      <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/4430572342"></a>
    </div>
    """
    assert M.parse_list_page(html) == GOLDEN["parsers"]["linkedin"]


def test_jora_list_parser_characterization():
    href = "/job/Senior-Product-Manager-3edbbb646574ed2a0a926fee537b0e7c?tracking=abc"
    html = f"""
    <html><body>
      <a href="{href}">Senior Product Manager</a>
      <a href="{href}">duplicate render</a>
    </body></html>
    """
    assert M.parse_jora_list_page(html, "Singapore") == GOLDEN["parsers"]["jora"]


def test_jobstreet_list_parser_characterization():
    payload = {
        "data": [
            {
                "id": 94145676,
                "title": "AI Product Manager",
                "employer": {"name": "Tech Co"},
                "advertiser": {"description": "Fallback Co"},
                "locations": [{"label": "Singapore"}],
                "workArrangements": {"data": [{"label": {"text": "On-site"}}]},
                "listingDate": "2026-08-20",
                "listingDateDisplay": "3d ago",
                "teaser": "Build AI",
            }
        ]
    }
    assert M.parse_jobstreet_list_page(payload, "product manager") == GOLDEN["parsers"]["jobstreet"]


class _FakeResponse:
    def __init__(self, *, text: str = "", data: dict | None = None, status_code: int = 200):
        self.text = text
        self._data = data
        self.status_code = status_code

    def json(self):
        if self._data is None:
            raise ValueError("no JSON payload")
        return self._data


class _GetSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class _PostSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_linkedin_jd_fetch_and_parse_characterization(monkeypatch):
    html = '<div class="description__text"><p>Build products</p><li>Ship safely</li></div>'
    fake = _GetSession(_FakeResponse(text=html))
    monkeypatch.setattr(M, "_cc_session", fake)
    result = M.fetch_jd("4430572342")
    assert fake.calls[0][0] == GOLDEN["urls"]["linkedin_jd"]
    assert fake.calls[0][1]["timeout"] == 20
    assert result == GOLDEN["parsers"]["linkedin_jd"]


def test_jora_jd_fetch_and_parse_characterization(monkeypatch):
    html = """
    <main>
      <h1>Senior Product Manager</h1>
      <div><span>Acme Jora</span><span>–</span><span>Singapore</span></div>
      <div class="job-detail"><p>Build products</p><p>Lead team</p></div>
    </main>
    """
    fake = _GetSession(_FakeResponse(text=html))
    monkeypatch.setattr(M, "_cc_session", fake)
    url = "https://sg.jora.com/job/Senior-Product-Manager-3edbbb646574ed2a0a926fee537b0e7c"
    result = M.fetch_jora_jd(url)
    assert fake.calls[0][0] == url
    assert fake.calls[0][1]["timeout"] == 20
    assert result == GOLDEN["parsers"]["jora_jd"]


def test_jobstreet_graphql_payload_and_parse_characterization(monkeypatch):
    content = "<div><p>Build AI products.</p><ul><li>Ship safely.</li></ul></div>"
    response = _FakeResponse(data={
        "data": {
            "jobDetails": {
                "job": {
                    "id": "94145676",
                    "title": "AI Product Manager",
                    "content": content,
                    "advertiser": {"id": "1", "name": "GraphQL Co"},
                    "location": {"label": "Singapore"},
                    "workTypes": [{"label": "Full time"}],
                }
            }
        }
    })
    fake = _PostSession(response)
    monkeypatch.setattr(M, "_cc_session", fake)
    result = M.fetch_jobstreet_jd("94145676")
    url, kwargs = fake.calls[0]
    assert url == GOLDEN["urls"]["jobstreet_graphql_endpoint"]
    assert kwargs["json"]["variables"] == {"jobId": "94145676"}
    assert _normalized_query_sha(kwargs["json"]["query"]) == GOLDEN["urls"]["jobstreet_graphql_normalized_sha256"]
    assert kwargs["timeout"] == 30
    assert kwargs["impersonate"] == "chrome"
    assert result == GOLDEN["parsers"]["jobstreet_jd"]


def test_title_filter_characterization():
    pattern = M._make_skip_pattern(M.DEFAULT_SKIP_KEYWORDS)
    observed = {title: M.match_skip_reason(title, pattern) for title in GOLDEN["title_filter"]}
    assert observed == GOLDEN["title_filter"]


def test_work_mode_characterization():
    observed = {
        "title_remote": M.extract_work_mode("", "Remote - Product Manager"),
        "jd_hybrid": M.extract_work_mode("Location: Singapore (hybrid) work model", ""),
        "jd_in_office": M.extract_work_mode("WORK OPTION: In Office. About the role", ""),
        "jd_chinese_remote": M.extract_work_mode("支持远程办公，可跨城市协作", ""),
        "jd_fallback_hybrid": M.extract_work_mode("This is a hybrid working arrangement.", ""),
        "none": M.extract_work_mode("random text without any mode", "Title"),
    }
    assert observed == GOLDEN["work_mode"]


def test_visa_characterization():
    observed = {
        "hard": M.detect_visa_signal("Applicants must be Singapore citizens only."),
        "soft": M.detect_visa_signal("We do not require visa sponsorship for this role."),
        "positive": M.detect_visa_signal("Visa sponsorship is available for exceptional candidates."),
        "none": M.detect_visa_signal("We welcome applicants from diverse backgrounds."),
    }
    assert observed == GOLDEN["visa"]


def test_cross_source_dedup_characterization(tmp_path):
    seen = tmp_path / "seen.jsonl"
    seen.write_text(
        '\n'.join([
            json.dumps({"job_id": "4430572342"}),
            json.dumps({"job_id": "3edbbb646574ed2a0a926fee537b0e7c"}),
            json.dumps({"source": "jobstreet", "job_id": "4430572342"}),
            "{bad-json",
        ]) + "\n",
        encoding="utf-8",
    )
    observed_seen = [list(x) for x in sorted(M.load_seen_ids(seen))]
    assert observed_seen == GOLDEN["dedup"]["seen_keys"]

    existing = [
        ["Status", "Priority", "Date", "Source", "URL"],
        ["New", "", "2026-08-22", "JobStreet / Minimax", "https://sg.jobstreet.com/job/94145676"],
        ["New", "", "2026-08-22", "LinkedIn / Minimax", "4430572342"],
        ["", "", "", "", ""],
    ]
    keys, next_row = M._load_sheet_keys(existing)
    assert [list(x) for x in sorted(keys)] == GOLDEN["dedup"]["sheet_keys"]
    assert next_row == GOLDEN["dedup"]["sheet_next_row"]


class _RecordingWS:
    def __init__(self):
        self.row_count = 100
        self.calls: list[tuple[str, str]] = []

    def add_rows(self, n: int):
        self.row_count += n

    def update(self, *, range_name, values, value_input_option):
        self.calls.append((range_name, value_input_option))


def test_sheet_row_and_write_order_characterization():
    job = {
        "job_id": "94145676",
        "title": "AI Product Manager",
        "company": "Tech Co",
        "location": "Singapore",
        "source": "jobstreet",
        "jd_text": "Location: Singapore (hybrid). We do not require visa sponsorship for this role.",
        "url": "https://sg.jobstreet.com/job/94145676",
    }
    row = M._build_sheet_row(job, "JobStreet / Minimax", "Singapore", set())
    assert row is not None
    normalized = list(row)
    normalized[2] = "<TODAY>"
    assert normalized == GOLDEN["sheet"]["normalized_row"]

    ws = _RecordingWS()
    result = M._write_rows_to_sheet(ws, 2, [row], skipped_dup=2, skipped_no_jd=3)
    assert [list(x) for x in ws.calls] == GOLDEN["sheet"]["write_calls"]
    assert result == GOLDEN["sheet"]["write_result"]


def test_machine_summary_characterization():
    observed = {
        "parsed": server._parse_machine_summary('noise\nJOBS_SCRAPER_SUMMARY={"jobs_found":7,"written":3}'),
        "missing": server._parse_machine_summary("human prose only"),
    }
    assert observed == GOLDEN["machine_summary"]


def test_mcp_public_contract_characterization():
    legacy = asyncio.run(server.mcp.list_tools())
    v11 = asyncio.run(server_v1_1.mcp.list_tools())
    legacy_by_name = {t.name: t for t in legacy}
    v11_by_name = {t.name: t for t in v11}

    assert sorted(legacy_by_name) == GOLDEN["mcp"]["legacy_tools"]
    assert sorted(v11_by_name) == GOLDEN["mcp"]["v11_tools"]

    crawl = legacy_by_name["crawl_jobs"]
    assert crawl.input_schema["properties"]["source"]["enum"] == GOLDEN["mcp"]["source_enum"]
    assert crawl.input_schema["properties"]["range"]["enum"] == GOLDEN["mcp"]["range_enum"]
    assert crawl.annotations.read_only_hint is False
    assert crawl.annotations.open_world_hint is True
    assert crawl.annotations.destructive_hint is False
    assert crawl.annotations.idempotent_hint is False

    sync = v11_by_name["sync_jobs_to_sheet"]
    assert sync.input_schema["properties"]["region"]["enum"] == GOLDEN["mcp"]["region_enum"]
    assert "gid" not in sync.input_schema["properties"]
    assert "sheet_gid" not in sync.input_schema["properties"]
    assert sync.annotations.read_only_hint is False

    initializer = v11_by_name["initialize_job_tracker"]
    assert initializer.input_schema["properties"]["dry_run"]["default"] is GOLDEN["mcp"]["initializer_dry_run_default"]
    assert initializer.annotations.idempotent_hint is True


def test_job_tracker_schema_and_region_routing_characterization():
    assert JT.SCHEMA_VERSION == GOLDEN["tracker"]["schema_version"]
    assert len(JT.HEADERS) == GOLDEN["tracker"]["column_count"]
    assert JT.SCHEMA_COLUMNS == GOLDEN["tracker"]["column_count"]
    assert JT.HEADER_HEIGHT_PX == GOLDEN["tracker"]["header_height_px"]
    assert JT.expected_tabs() == GOLDEN["tracker"]["default_tabs"]
    assert sorted(JT.VALIDATIONS) == GOLDEN["tracker"]["validation_columns"]
    observed = {value: JT.canonical_region(value) for value in GOLDEN["tracker"]["canonical_regions"]}
    assert observed == GOLDEN["tracker"]["canonical_regions"]
    assert JT.raw_tab("singapore") == "SG-Raw"
    assert JT.selected_tab("台灣") == "TW-Selected"
    assert JT.raw_tab("Shanghai") == "China-Raw"
