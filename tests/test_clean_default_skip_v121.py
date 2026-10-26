"""Default skip-profile contract for the current release (v1.4.0 / skip filter v8.5).

The v1.2.x "clean default" contract (an empty default profile plus the
`ACTIVE_DEFAULT_SKIP_KEYWORDS` / `resolve_skip_words` helpers) was superseded.
The current release ships:

  * `DEFAULT_SKIP_KEYWORDS` — the curated, non-empty keyword profile constant;
  * `_make_skip_pattern(skip_words)` — the profile -> regex helper;
  * `match_skip_reason(title, skip_pat=None, *, source=None)` — the v8.5 filter
    entry point (semantic groups; it ignores the deprecated `skip_pat`);
  * `enrich_with_jd(jobs, skip_pat=None, ..., no_skip=False)` — the JD-stage
    filter, where `skip_pat` is an *extra* keyword layer and `no_skip=True`
    disables every title filter.

`SKIP.md` is the semantics authority (§18.5 for the shipped surface, §18.6 for the
CLI wiring); the implementation lives in `sg_product_jobs.py`.
"""

from __future__ import annotations

import re

import sg_product_jobs as S


def _fake_fetch(calls: list[str]):
    def fake_fetch_jd(job_id: str) -> dict:
        calls.append(job_id)
        return {"jd_text": "Full job description", "jd_lines": ["Full job description"]}

    return fake_fetch_jd


def test_default_skip_profile_is_the_documented_non_empty_default():
    assert isinstance(S.DEFAULT_SKIP_KEYWORDS, list)
    assert S.DEFAULT_SKIP_KEYWORDS, "the default skip profile must not be empty"
    assert len(S.DEFAULT_SKIP_KEYWORDS) == 59
    assert "junior" in S.DEFAULT_SKIP_KEYWORDS
    assert "assistant" in S.DEFAULT_SKIP_KEYWORDS
    # The superseded v1.2.x clean-default helpers are gone; DEFAULT_SKIP_KEYWORDS is shipped.
    assert not hasattr(S, "ACTIVE_DEFAULT_SKIP_KEYWORDS")
    assert not hasattr(S, "resolve_skip_words")


def test_cli_default_applies_the_v85_profile_without_an_extra_keyword_layer():
    parser = S.build_arg_parser()
    args = parser.parse_args(["7d"])
    # No operator override -> only the v8.5 semantic-group profile applies.
    assert args.skip_keywords is None
    assert args.no_skip is False
    # ... and that profile still skips a junior title.
    assert S.match_skip_reason("Junior Product Manager") == "entry_level"


def test_empty_skip_pattern_never_matches():
    """An empty keyword profile must not match anything.

    v1.4.0 fixed this: the empty profile used to compile to
    ``(?<![a-z])()(?![a-z])``, a zero-width pattern that matches at every
    position — so an empty profile skipped *every* title with the reason
    ``custom_skip_keywords``. That is reachable from the CLI, because
    ``--skip-keywords`` takes ``nargs="*"`` and therefore accepts an empty
    list.
    """
    pattern = S._make_skip_pattern([])
    assert isinstance(pattern, re.Pattern)
    for title in ("Junior Product Manager", "Assistant to CEO, Product", "Product Manager"):
        assert pattern.search(title) is None
        assert list(pattern.finditer(title)) == []


def test_empty_profile_does_not_change_the_v85_decision():
    # v8.5 ignores the deprecated skip_pat (SKIP.md §11.1 / §18.6): the outcome comes
    # from the semantic groups, so an empty profile is a no-op for the decision.
    empty = S._make_skip_pattern([])
    default = S._make_skip_pattern(S.DEFAULT_SKIP_KEYWORDS)
    for title in ("Junior Product Manager", "Assistant to CEO, Product", "Senior Product Manager"):
        assert S.match_skip_reason(title, empty) == S.match_skip_reason(title, default)


def test_custom_skip_keywords_still_enable_skip_behavior():
    pattern = S._make_skip_pattern(["junior", "assistant"])

    assert S.match_skip_reason("Junior Product Manager", pattern) == "entry_level"
    assert S.match_skip_reason("Assistant to CEO, Product", pattern) == "assistant"


def test_custom_skip_keywords_are_honoured_and_reach_the_filter(monkeypatch):
    parser = S.build_arg_parser()
    args = parser.parse_args(["7d", "--skip-keywords", "senior"])
    assert args.skip_keywords == ["senior"]

    pattern = S._make_skip_pattern(args.skip_keywords)
    assert pattern.search("Senior Product Manager").group(0).lower() == "senior"

    calls: list[str] = []
    monkeypatch.setattr(S, "fetch_jd", _fake_fetch(calls))
    monkeypatch.setattr(S, "append_seen", lambda *args, **kwargs: None)
    monkeypatch.setattr(S, "human_sleep", lambda *args, **kwargs: None)

    jobs, stats = S.enrich_with_jd(
        [{"source": "linkedin", "job_id": "123", "title": "Senior Product Manager", "company": "Example"}],
        skip_pat=pattern,
    )

    # The v8.5 profile keeps this title; the operator override is what skips it.
    assert S.match_skip_reason("Senior Product Manager") is None
    assert calls == []
    assert stats["skipped"] == 1
    assert jobs[0]["jd_skipped"] == "custom_skip_keywords"


def test_no_skip_flag_is_accepted_and_disables_skipping(monkeypatch):
    parser = S.build_arg_parser()
    args = parser.parse_args(["7d", "--no-skip"])
    assert args.no_skip is True
    assert args.skip_keywords is None

    calls: list[str] = []
    monkeypatch.setattr(S, "fetch_jd", _fake_fetch(calls))
    monkeypatch.setattr(S, "append_seen", lambda *args, **kwargs: None)
    monkeypatch.setattr(S, "human_sleep", lambda *args, **kwargs: None)

    jobs, stats = S.enrich_with_jd(
        [{"source": "linkedin", "job_id": "123", "title": "Junior Product Manager", "company": "Example"}],
        skip_pat=None,
        no_skip=args.no_skip,
    )

    assert calls == ["123"]
    assert stats["skipped"] == 0
    assert stats["fetched"] == 1
    assert jobs[0]["jd_text"] == "Full job description"


def test_junior_title_is_skipped_with_the_entry_level_reason():
    assert S.match_skip_reason("Junior Product Manager") == "entry_level"
    assert S.match_skip_reason("Junior Product Manager", S._make_skip_pattern(S.DEFAULT_SKIP_KEYWORDS)) == "entry_level"


def test_default_enrichment_path_skips_the_junior_title(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(S, "fetch_jd", _fake_fetch(calls))
    monkeypatch.setattr(S, "append_seen", lambda *args, **kwargs: None)
    monkeypatch.setattr(S, "human_sleep", lambda *args, **kwargs: None)

    jobs, stats = S.enrich_with_jd(
        [{"source": "linkedin", "job_id": "123", "title": "Junior Product Manager", "company": "Example"}],
        skip_pat=None,
    )

    assert calls == []
    assert stats["skipped"] == 1
    assert stats["fetched"] == 0
    assert jobs[0]["jd_skipped"] == "entry_level"
