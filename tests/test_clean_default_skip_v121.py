from __future__ import annotations

import sg_product_jobs as S


def test_active_default_skip_profile_is_empty():
    assert S.ACTIVE_DEFAULT_SKIP_KEYWORDS == []
    assert S.resolve_skip_words(skip_keywords=None, no_skip=False) == []


def test_empty_skip_pattern_is_noop_for_formerly_skipped_title():
    pattern = S._make_skip_pattern(S.ACTIVE_DEFAULT_SKIP_KEYWORDS)

    assert S.match_skip_reason("Junior Product Manager", pattern) is None


def test_custom_skip_keywords_still_enable_skip_behavior():
    pattern = S._make_skip_pattern(["junior", "assistant"])

    assert S.match_skip_reason("Junior Product Manager", pattern) == "junior"
    assert S.match_skip_reason("Assistant to CEO, Product", pattern) == "assistant"


def test_resolve_skip_words_preserves_custom_keywords():
    assert S.resolve_skip_words(skip_keywords=["intern", "junior"], no_skip=False) == ["intern", "junior"]


def test_resolve_skip_words_no_skip_wins_for_back_compatibility():
    assert S.resolve_skip_words(skip_keywords=["junior"], no_skip=True) is None


def test_default_enrichment_path_does_not_skip_formerly_skipped_title(monkeypatch):
    calls: list[str] = []

    def fake_fetch_jd(job_id: str) -> dict:
        calls.append(job_id)
        return {"jd_text": "Full job description", "jd_lines": ["Full job description"]}

    monkeypatch.setattr(S, "fetch_jd", fake_fetch_jd)
    monkeypatch.setattr(S, "append_seen", lambda *args, **kwargs: None)
    monkeypatch.setattr(S, "human_sleep", lambda *_args, **_kwargs: None)

    jobs, stats = S.enrich_with_jd(
        [{"source": "linkedin", "job_id": "123", "title": "Junior Product Manager", "company": "Example"}],
        skip_pat=None,
    )

    assert calls == ["123"]
    assert stats["skipped"] == 0
    assert stats["fetched"] == 1
    assert jobs[0]["jd_text"] == "Full job description"
