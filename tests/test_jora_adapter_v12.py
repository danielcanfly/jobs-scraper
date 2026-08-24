from __future__ import annotations

import inspect

import sg_product_jobs as S


def test_jora_root_wrappers_delegate_to_adapter(monkeypatch):
    calls = {}

    def fake_build_list_url(jora_tpr, page, keyword, location):
        calls["build"] = (jora_tpr, page, keyword, location)
        return "URL"

    def fake_parse_list_page(html, *, location):
        calls["parse"] = (html, location)
        return [{"job_id": "abc"}]

    def fake_fetch_jd(session, url, *, sleep_fn):
        calls["fetch"] = (session, url, sleep_fn)
        return {"jd_text": "JD", "error": None}

    def fake_crawl_list(session, tpr, max_pages, *, tpr_map, keyword, location, sleep_fn):
        calls["crawl"] = (session, tpr, max_pages, tpr_map, keyword, location, sleep_fn)
        return [{"job_id": "def"}]

    monkeypatch.setattr(S.jora_source, "build_list_url", fake_build_list_url)
    monkeypatch.setattr(S.jora_source, "parse_list_page", fake_parse_list_page)
    monkeypatch.setattr(S.jora_source, "fetch_jd", fake_fetch_jd)
    monkeypatch.setattr(S.jora_source, "crawl_list", fake_crawl_list)

    assert S.build_jora_list_url("7d", 3, keyword="pm", location="Singapore") == "URL"
    assert calls["build"] == ("7d", 3, "pm", "Singapore")

    assert S.parse_jora_list_page("<html/>", location="Singapore") == [{"job_id": "abc"}]
    assert calls["parse"] == ("<html/>", "Singapore")

    url = "https://sg.jora.com/job/example"
    assert S.fetch_jora_jd(url) == {"jd_text": "JD", "error": None}
    assert calls["fetch"][0] is S._cc_session
    assert calls["fetch"][1] == url
    assert calls["fetch"][2] is S.time.sleep

    assert S.crawl_jora_list("7d", 2, keyword="pm", location="Singapore") == [{"job_id": "def"}]
    assert calls["crawl"][0] is S._cc_session
    assert calls["crawl"][1] == "7d"
    assert calls["crawl"][2] == 2
    assert calls["crawl"][3] is S.JORA_TPR
    assert calls["crawl"][4] == "pm"
    assert calls["crawl"][5] == "Singapore"
    assert calls["crawl"][6] is S.human_sleep


def test_jora_adapter_preserves_url_and_list_parse_shape():
    url = S.jora_source.build_list_url("7d", 4, "product manager", "Singapore")
    assert url == "https://sg.jora.com/j?a=7d&l=Singapore&q=product+manager&p=4"

    html = (
        "<main>"
        "<a href='/job/Senior-Product-Manager-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=1'>one</a>"
        "<a href='/job/Senior-Product-Manager-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=2'>dup</a>"
        "<a href='https://sg.jora.com/job/Product-Lead-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb?x=1'>two</a>"
        "</main>"
    )

    assert S.jora_source.parse_list_page(html, location="Singapore") == [
        {
            "job_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "title": "Senior Product Manager",
            "company": "",
            "location": "Singapore",
            "posted_at": "",
            "posted_ago": "",
            "url": "https://sg.jora.com/job/Senior-Product-Manager-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa?x=1",
            "source": "jora",
        },
        {
            "job_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "title": "Product Lead",
            "company": "",
            "location": "Singapore",
            "posted_at": "",
            "posted_ago": "",
            "url": "https://sg.jora.com/job/Product-Lead-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb?x=1",
            "source": "jora",
        },
    ]


def test_jora_adapter_uses_injected_session_and_sleep_boundaries():
    fetch_sig = inspect.signature(S.jora_source.fetch_jd)
    assert "session" in fetch_sig.parameters
    assert "sleep_fn" in fetch_sig.parameters

    crawl_sig = inspect.signature(S.jora_source.crawl_list)
    assert "session" in crawl_sig.parameters
    assert "sleep_fn" in crawl_sig.parameters
    assert "tpr_map" in crawl_sig.parameters


def test_jora_fetch_jd_preserves_403_backoff_and_error_shape():
    class FakeResponse:
        status_code = 403
        text = ""

    class FakeSession:
        def __init__(self):
            self.calls = 0

        def get(self, url, timeout, impersonate):
            self.calls += 1
            return FakeResponse()

    sleeps = []
    session = FakeSession()

    result = S.jora_source.fetch_jd(
        session,
        "https://sg.jora.com/job/example",
        sleep_fn=sleeps.append,
    )

    assert session.calls == 3
    assert sleeps == [30, 60, 90]
    assert result == {
        "jd_text": None,
        "jd_lines": None,
        "jd_html": None,
        "company": "",
        "location": "",
        "title": "",
        "error": "HTTP 403 重試失敗",
    }


def test_jora_crawl_uses_injected_sleep_for_list_pagination(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = "<html/>"

    class FakeSession:
        def __init__(self):
            self.calls = []

        def get(self, url, timeout, impersonate):
            self.calls.append((url, timeout, impersonate))
            return FakeResponse()

    first_page = [{"job_id": f"{i:032x}"} for i in range(10)]
    pages = [first_page, []]
    sleeps = []
    session = FakeSession()

    def fake_parse_list_page(html, *, location):
        return pages.pop(0)

    monkeypatch.setattr(S.jora_source, "parse_list_page", fake_parse_list_page)

    result = S.jora_source.crawl_list(
        session,
        "7d",
        2,
        tpr_map={"7d": "7d"},
        keyword="product manager",
        location="Singapore",
        sleep_fn=sleeps.append,
    )

    assert result == first_page
    assert len(session.calls) == 2
    assert session.calls[0][0] == "https://sg.jora.com/j?a=7d&l=Singapore&q=product+manager&p=1"
    assert session.calls[1][0] == "https://sg.jora.com/j?a=7d&l=Singapore&q=product+manager&p=2"
    assert sleeps == ["list"]
