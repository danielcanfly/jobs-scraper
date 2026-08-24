from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlsplit

import sg_product_jobs as S


def _normalized_query_sha(query: str) -> str:
    return hashlib.sha256(" ".join(query.split()).encode("utf-8")).hexdigest()


def _parsed_url(url: str) -> tuple[str, dict[str, str]]:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}{parts.path}", dict(parse_qsl(parts.query))


def _job(job_id: int, *, title: str | None = None) -> dict:
    return {
        "id": job_id,
        "title": title or f"Product Role {job_id}",
        "employer": {"name": f"Company {job_id}"},
        "locations": [{"label": "Singapore"}],
        "workArrangements": {"data": [{"label": {"text": "On-site"}}]},
        "listingDate": "2026-08-20",
        "listingDateDisplay": "3d ago",
        "teaser": f"Build {job_id}",
    }


def test_jobstreet_root_wrappers_delegate_to_adapter(monkeypatch):
    calls = {}

    def fake_build_list_url(keyword, page, daterange, *, worktype, where, page_size, list_api):
        calls["build"] = (keyword, page, daterange, worktype, where, page_size, list_api)
        return "URL"

    def fake_parse_list_page(data, keyword):
        calls["parse"] = (data, keyword)
        return [{"job_id": "94145676"}]

    def fake_fetch_jd(session, job_id, *, graphql_url, query):
        calls["fetch"] = (session, job_id, graphql_url, query)
        return {"jd_text": "JD", "error": None}

    def fake_crawl_list(
        session, daterange, max_pages, *, keywords, worktype, where, page_size, list_api, sleep_fn
    ):
        calls["crawl"] = (
            session, daterange, max_pages, keywords, worktype, where, page_size, list_api, sleep_fn
        )
        return [{"job_id": "94145677"}]

    monkeypatch.setattr(S.jobstreet_source, "build_list_url", fake_build_list_url)
    monkeypatch.setattr(S.jobstreet_source, "parse_list_page", fake_parse_list_page)
    monkeypatch.setattr(S.jobstreet_source, "fetch_jd", fake_fetch_jd)
    monkeypatch.setattr(S.jobstreet_source, "crawl_list", fake_crawl_list)

    assert S.build_jobstreet_list_url("pm", 2, "7", worktype="242", where="Singapore") == "URL"
    assert calls["build"] == (
        "pm", 2, "7", "242", "Singapore", 20, S.JOBSTREET_LIST_API,
    )

    payload = {"data": []}
    assert S.parse_jobstreet_list_page(payload, "pm") == [{"job_id": "94145676"}]
    assert calls["parse"] == (payload, "pm")

    assert S.fetch_jobstreet_jd("94145676") == {"jd_text": "JD", "error": None}
    assert calls["fetch"][0] is S._cc_session
    assert calls["fetch"][1] == "94145676"
    assert calls["fetch"][2] == S.JOBSTREET_GRAPHQL
    assert calls["fetch"][3] == S.JOBSTREET_DETAIL_QUERY

    assert S.crawl_jobstreet_list("7", 2, keywords=["pm"]) == [{"job_id": "94145677"}]
    assert calls["crawl"][0] is S._cc_session
    assert calls["crawl"][1] == "7"
    assert calls["crawl"][2] == 2
    assert calls["crawl"][3] == ["pm"]
    assert calls["crawl"][4] == S.JOBSTREET_WORKTYPE_FT
    assert calls["crawl"][5] == S.JOBSTREET_LOCATION
    assert calls["crawl"][6] == 20
    assert calls["crawl"][7] == S.JOBSTREET_LIST_API
    assert calls["crawl"][8] is S.human_sleep


def test_jobstreet_root_constants_alias_adapter_constants():
    assert S.JOBSTREET_TPR is S.jobstreet_source.TPR
    assert S.JOBSTREET_MAX_PAGES is S.jobstreet_source.MAX_PAGES
    assert S.JOBSTREET_LIST_API == S.jobstreet_source.LIST_API
    assert S.JOBSTREET_GRAPHQL == S.jobstreet_source.GRAPHQL
    assert S.JOBSTREET_BASE == S.jobstreet_source.BASE_URL
    assert S.JOBSTREET_WORKTYPE_FT == S.jobstreet_source.WORKTYPE_FT
    assert S.JOBSTREET_DETAIL_QUERY == S.jobstreet_source.JOBSTREET_DETAIL_QUERY


def test_jobstreet_adapter_preserves_list_url_shape_and_params():
    url = S.jobstreet_source.build_list_url(
        "product manager",
        2,
        "7",
        worktype="242",
        where="Singapore",
        page_size=20,
    )
    base, params = _parsed_url(url)
    assert base == "https://sg.jobstreet.com/api/jobsearch/v5/search"
    assert params == {
        "siteKey": "SG-Main",
        "keywords": "product manager",
        "where": "Singapore",
        "worktype": "242",
        "daterange": "7",
        "page": "2",
        "pageSize": "20",
    }
    assert url == (
        "https://sg.jobstreet.com/api/jobsearch/v5/search?"
        "siteKey=SG-Main&keywords=product+manager&where=Singapore&"
        "worktype=242&daterange=7&page=2&pageSize=20"
    )


def test_jobstreet_graphql_payload_query_and_session_injection(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "jobDetails": {
                        "job": {
                            "title": "AI Product Manager",
                            "content": "<p>Build AI products.</p><ul><li>Ship safely.</li></ul>",
                            "advertiser": {"name": "GraphQL Co"},
                            "location": {"label": "Singapore"},
                        }
                    }
                }
            }

    class FakeSession:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return FakeResponse()

    fake = FakeSession()
    monkeypatch.setattr(S, "_cc_session", fake)

    result = S.fetch_jobstreet_jd("94145676")
    url, kwargs = fake.calls[0]
    assert url == "https://sg.jobstreet.com/graphql"
    assert kwargs["json"]["variables"] == {"jobId": "94145676"}
    assert _normalized_query_sha(kwargs["json"]["query"]) == (
        "b5e35f913134f45917fba9b0309125d2173f899f7a763c8672e79ba6ca31018b"
    )
    assert kwargs["headers"] == {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    assert kwargs["timeout"] == 30
    assert kwargs["impersonate"] == "chrome"
    assert result == {
        "jd_text": "Build AI products. Ship safely.",
        "jd_lines": ["Build AI products.", "Ship safely."],
        "jd_html": "<p>Build AI products.</p><ul><li>Ship safely.</li></ul>",
        "company": "GraphQL Co",
        "location": "Singapore",
        "title": "AI Product Manager",
        "error": None,
    }


def test_jobstreet_list_parser_preserves_shape_and_empty_defaults():
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
            },
            {
                "id": 94145677,
                "title": "Product Lead",
                "advertiser": {"description": "Fallback Only"},
                "companyName": "Company Fallback",
            },
            {"title": "Missing id"},
        ]
    }

    assert S.jobstreet_source.parse_list_page(payload, "product manager") == [
        {
            "job_id": "94145676",
            "title": "AI Product Manager",
            "company": "Tech Co",
            "location": "Singapore",
            "posted_at": "2026-08-20",
            "posted_ago": "3d ago",
            "work_mode": "Onsite",
            "teaser": "Build AI",
            "url": "",
            "keyword_used": "product manager",
            "source": "jobstreet",
        },
        {
            "job_id": "94145677",
            "title": "Product Lead",
            "company": "Fallback Only",
            "location": "",
            "posted_at": "",
            "posted_ago": "",
            "work_mode": "",
            "teaser": "",
            "url": "",
            "keyword_used": "product manager",
            "source": "jobstreet",
        },
    ]


def test_jobstreet_fetch_jd_preserves_error_shapes():
    class Response:
        def __init__(self, status_code=200, data=None, json_exc=None):
            self.status_code = status_code
            self._data = data
            self._json_exc = json_exc

        def json(self):
            if self._json_exc:
                raise self._json_exc
            return self._data

    class Session:
        def __init__(self, response=None, exc=None):
            self.response = response
            self.exc = exc

        def post(self, *args, **kwargs):
            if self.exc:
                raise self.exc
            return self.response

    assert S.jobstreet_source.fetch_jd(Session(exc=RuntimeError("boom")), "1") == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "boom",
    }
    assert S.jobstreet_source.fetch_jd(Session(Response(status_code=500)), "1") == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "HTTP 500",
    }
    assert S.jobstreet_source.fetch_jd(Session(Response(json_exc=ValueError("bad json"))), "1") == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "JSON fail: bad json",
    }
    assert S.jobstreet_source.fetch_jd(Session(Response(data={"errors": [{"message": "x"}]})), "1") == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "[{'message': 'x'}]",
    }
    assert S.jobstreet_source.fetch_jd(Session(Response(data={"data": {"jobDetails": {}}})), "1") == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "no job in response",
    }
    assert S.jobstreet_source.fetch_jd(
        Session(Response(data={"data": {"jobDetails": {"job": {"content": ""}}}})),
        "1",
    ) == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "empty JD",
    }


def test_jobstreet_crawl_preserves_keyword_order_dedup_soft_stop_and_sleep():
    class Response:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def json(self):
            return self.payload

    class Session:
        def __init__(self, payloads):
            self.payloads = list(payloads)
            self.calls = []

        def get(self, url, timeout, impersonate):
            self.calls.append((url, timeout, impersonate))
            return Response(self.payloads.pop(0))

    first_page = [_job(i) for i in range(100, 110)]
    second_page = [_job(109), _job(110)]
    third_page = [_job(100), _job(200)]
    session = Session([
        {"data": first_page, "totalCount": 12},
        {"data": second_page, "totalCount": 12},
        {"data": third_page, "totalCount": 2},
    ])
    sleeps = []

    result = S.jobstreet_source.crawl_list(
        session,
        "7",
        2,
        keywords=["product manager", "product lead"],
        sleep_fn=sleeps.append,
    )

    assert [job["job_id"] for job in result] == [str(i) for i in range(100, 111)] + ["200"]
    assert [job["keyword_used"] for job in result[:11]] == ["product manager"] * 11
    assert result[-1]["keyword_used"] == "product lead"
    assert len(session.calls) == 3
    assert session.calls[0][1:] == (20, "chrome")
    assert _parsed_url(session.calls[0][0])[1]["keywords"] == "product manager"
    assert _parsed_url(session.calls[1][0])[1]["page"] == "2"
    assert _parsed_url(session.calls[2][0])[1]["keywords"] == "product lead"
    assert sleeps == ["list"]
