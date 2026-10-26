"""Skip-keyword expansion / custom-override contract suite.

Covers the *keyword* side of the skip filter: the retained-but-deprecated
``DEFAULT_SKIP_KEYWORDS`` profile (SKIP.md §11.1), the ``_make_skip_pattern``
helper (SKIP.md §14 / implementation), and the CLI switches ``--no-skip`` /
``--skip-keywords``.

The v8.5 semantic filter itself is covered by ``tests/test_v85_hostile.py``.
This file only covers the keyword-profile surface and — importantly — documents
how that surface actually behaves in the qualified implementation:

* ``match_skip_reason`` IGNORES ``skip_pat`` (SKIP.md §11.1), so neither
  ``--no-skip`` nor ``--skip-keywords`` changes *which* titles are skipped.
  The v8.5 semantic groups always decide.
* The v1.2.1 "skip profile" API (``ACTIVE_DEFAULT_SKIP_KEYWORDS`` /
  ``resolve_skip_words``) referenced by the pre-existing upstream contract test
  ``tests/test_clean_default_skip_v121.py`` is NOT implemented in the qualified
  v8.5 module.  That upstream test is a known pre-existing failure and is out
  of scope here; ``test_v121_skip_profile_api_is_absent`` documents the gap
  without asserting it as a v8.5 requirement.
"""

from __future__ import annotations

import importlib
import os

import pytest

import sg_product_jobs as S


# ---------------------------------------------------------------------------
# §11.1 — DEFAULT_SKIP_KEYWORDS is retained (deprecated) but not consulted
# ---------------------------------------------------------------------------
def test_default_skip_keywords_is_retained_with_59_entries():
    """SKIP.md §11.1 — the v8.4 keyword profile is kept for backward compat and
    still holds its 59 entries; v8.5 just does not use it."""
    assert len(S.DEFAULT_SKIP_KEYWORDS) == 59


@pytest.mark.parametrize(
    "word",
    [
        "intern",
        "internship",
        "trainee",
        "graduate",
        "grad",
        "entry",
        "entry level",
        "entry-level",
        "junior",
        "jr",
        "assistant",
        "support",
        "coordinator",
        "administrator",
        "clerk",
        "secretary",
        "product marketing",
        "product analyst",
        "product designer",
        "product designers",
        "product validation",
        "product certification",
        "qa",
        "test",
        "quality assurance",
        "quality",
        "account manager",
        "account managers",
        "key account manager",
        "key account managers",
        "client manager",
        "client managers",
        "relationship manager",
        "relationship managers",
        "account executive",
        "sales",
        "business development",
        "accounting",
        "accountant",
        "accountants",
        "audit",
        "auditor",
        "auditors",
        "human resources",
        "recruiting",
        "recruiter",
        "recruiters",
        "procurement",
        "purchasing",
        "purchaser",
        "purchasers",
        "buyer",
        "buyers",
        "merchandiser",
        "merchandisers",
        "specialist",
        "temp",
        "temporary",
        "contract",
    ],
)
def test_default_skip_keywords_contains_the_documented_v84_profile(word):
    """SKIP.md §11.1 + §16 (2026-08-29 v0.4: 24 → 28 → 59 words) — every
    documented legacy keyword is still present in the retained profile."""
    assert word in S.DEFAULT_SKIP_KEYWORDS


def test_default_skip_keywords_has_no_duplicates():
    """Characterization case — the retained v8.4 profile has no duplicate
    entries (so the compiled alternation is stable)."""
    assert len(S.DEFAULT_SKIP_KEYWORDS) == len(set(S.DEFAULT_SKIP_KEYWORDS))


def test_match_skip_reason_does_not_consult_the_keyword_profile():
    """SKIP.md §11.1 — the keyword profile is not consulted by the v8.5 filter:
    a title that the legacy profile would kill is still decided by the
    semantic groups."""
    pattern = S._make_skip_pattern(S.DEFAULT_SKIP_KEYWORDS)
    assert pattern.search("Junior Product Manager") is not None
    # ... but the v8.5 reason is the semantic-group reason, not a keyword hit.
    assert S.match_skip_reason("Junior Product Manager", pattern) == "entry_level"


# ---------------------------------------------------------------------------
# _make_skip_pattern (implementation helper, SKIP.md §11 / §14)
# ---------------------------------------------------------------------------
def test_make_skip_pattern_is_case_insensitive():
    """SKIP.md §11.1 — the retained profile helper compiles an IGNORECASE
    pattern."""
    pattern = S._make_skip_pattern(["intern"])
    assert pattern.search("INTERN")
    assert pattern.search("Intern")


@pytest.mark.parametrize(
    "word,text,matches",
    [
        ("intern", "Internship", False),
        ("intern", "Intern", True),
        ("qa", "QATest", False),
        ("sales", "Salesman", False),
        ("qa", "QA Engineer", True),
    ],
)
def test_make_skip_pattern_uses_word_boundaries(word, text, matches):
    """Characterization case (behaviour locked from the qualified Repair7
    implementation) — the helper uses the ``(?<![a-z])...(?![a-z])`` guard, so a
    keyword only matches as a whole word."""
    pattern = S._make_skip_pattern([word])
    assert bool(pattern.search(text)) is matches


def test_make_skip_pattern_handles_hyphenated_keywords():
    """Characterization case — ``\\b`` breaks on hyphens, so the helper uses the
    look-around guard instead; "entry-level" still matches as a unit."""
    pattern = S._make_skip_pattern(["entry-level"])
    assert pattern.search("Entry-Level Product Manager")


def test_make_skip_pattern_escapes_regex_metacharacters():
    """Characterization case — keywords are escaped, so a dot is a literal."""
    pattern = S._make_skip_pattern(["a.b"])
    assert pattern.search("a.b")
    assert not pattern.search("axb")


def test_make_skip_pattern_with_empty_list_matches_nothing():
    """Characterization case — an empty profile compiles to a pattern that can
    never match (this is what ``enrich_with_jd`` falls back to)."""
    pattern = S._make_skip_pattern([])
    assert not pattern.search("Junior Product Manager")
    assert not pattern.search("Sales Manager")


def test_make_skip_pattern_defaults_profile_matches_documented_titles():
    """Characterization case — the retained default profile still fires on the
    legacy v8.4 kill list (independent of the v8.5 filter)."""
    pattern = S._make_skip_pattern(S.DEFAULT_SKIP_KEYWORDS)
    for title in [
        "Junior Product Manager",
        "Product Designer",
        "Sales Manager",
        "QA Engineer",
        "Business Development Manager",
        "Entry-Level Analyst",
        "Account Manager",
    ]:
        assert pattern.search(title), title


# ---------------------------------------------------------------------------
# CLI: --no-skip / --skip-keywords
# ---------------------------------------------------------------------------
def test_cli_defaults_leave_skip_profile_untouched():
    """SKIP.md §11.1 + implementation ``build_arg_parser`` — with no CLI switch
    the keyword profile is left at its default (None means "use
    DEFAULT_SKIP_KEYWORDS")."""
    args = S.build_arg_parser().parse_args([])
    assert args.skip_keywords is None
    assert args.no_skip is False


def test_cli_no_skip_flag_is_parsed():
    """SKIP.md §11.1 — ``--no-skip`` is accepted and flips the flag."""
    args = S.build_arg_parser().parse_args(["--no-skip"])
    assert args.no_skip is True
    assert args.skip_keywords is None


def test_cli_skip_keywords_override_is_parsed():
    """SKIP.md §11.1 — ``--skip-keywords`` replaces the keyword profile."""
    args = S.build_arg_parser().parse_args(["--skip-keywords", "intern", "junior"])
    assert args.skip_keywords == ["intern", "junior"]
    assert args.no_skip is False


def test_cli_skip_keywords_with_no_values_is_an_empty_list():
    """SKIP.md §11.1 — ``--skip-keywords`` with no values yields an empty list
    (not None), which is the "custom profile" branch of the selection rule."""
    args = S.build_arg_parser().parse_args(["--skip-keywords"])
    assert args.skip_keywords == []


def test_cli_effective_profile_selection_rule():
    """SKIP.md §11.1 — the effective keyword profile follows the documented
    rule: custom keywords are an *additional* match layered on the v8.5
    semantic groups, the default run layers nothing on top, and ``--no-skip``
    disables every title filter."""
    parser = S.build_arg_parser()

    # Default run: no legacy pattern is layered on top of the v8.5 groups.
    default_args = parser.parse_args([])
    assert default_args.skip_keywords is None
    assert default_args.no_skip is False

    # Custom keywords become an additional pattern.
    custom_args = parser.parse_args(["--skip-keywords", "robotics"])
    assert custom_args.skip_keywords == ["robotics"]
    assert custom_args.no_skip is False

    # --no-skip disables filtering entirely.
    no_skip_args = parser.parse_args(["--no-skip"])
    assert no_skip_args.no_skip is True


# ---------------------------------------------------------------------------
# The CLI switches do NOT change the v8.5 skip decision (SKIP.md §11.1)
# ---------------------------------------------------------------------------
def test_no_skip_does_not_disable_the_v85_semantic_filter(monkeypatch):
    """SKIP.md §11.1 — characterization case (behaviour locked from the
    qualified Repair7 implementation): ``--no-skip`` builds no keyword pattern,
    but ``enrich_with_jd`` still routes every title through
    ``match_skip_reason``, so the v8.5 semantic groups keep skipping
    entry-level / non-target titles.  The CLI help text ("完全跳過 skip 過濾")
    overstates what the flag does."""
    monkeypatch.setattr(S, "fetch_jd", lambda job_id: {"jd_text": "JD", "jd_lines": ["JD"]})
    monkeypatch.setattr(S, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(S, "human_sleep", lambda *a, **k: None)

    jobs = [{"source": "linkedin", "job_id": "1", "title": "Junior Product Manager", "company": "X"}]
    kept, stats = S.enrich_with_jd(jobs, skip_pat=None)

    assert stats["skipped"] == 1
    assert stats["fetched"] == 0
    assert kept[0]["jd_skipped"] == "entry_level"


def test_custom_skip_keywords_add_to_the_v85_decision(monkeypatch):
    """SKIP.md §11.1 — a custom keyword profile is an *additional* match on
    top of the v8.5 semantic groups, not a replacement for them.

    Before v1.4.0 the custom profile was passed to ``match_skip_reason``, which
    v8.5 deliberately ignores, so ``--skip-keywords`` had no effect on what got
    skipped and the CLI help text overstated the flag. v1.4.0 applies the custom
    pattern alongside the semantic groups: a title hit by either is skipped.
    """
    monkeypatch.setattr(S, "fetch_jd", lambda job_id: {"jd_text": "JD", "jd_lines": ["JD"]})
    monkeypatch.setattr(S, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(S, "human_sleep", lambda *a, **k: None)

    pattern = S._make_skip_pattern(["robotics"])
    assert pattern.search("Robotics Product Manager")

    jobs = [{"source": "linkedin", "job_id": "2", "title": "Robotics Product Manager", "company": "X"}]
    kept, stats = S.enrich_with_jd(jobs, skip_pat=pattern)

    assert stats["skipped"] == 1
    assert stats["fetched"] == 0
    assert kept[0].get("jd_skipped") == "custom_skip_keywords"


def test_no_skip_disables_every_title_filter(monkeypatch):
    """SKIP.md §11.1 — ``--no-skip`` means no title filter at all, not just
    "no custom profile". The v8.5 semantic groups are bypassed as well."""
    monkeypatch.setattr(S, "fetch_jd", lambda job_id: {"jd_text": "JD", "jd_lines": ["JD"]})
    monkeypatch.setattr(S, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(S, "human_sleep", lambda *a, **k: None)

    jobs = [
        {"source": "linkedin", "job_id": "1", "title": "Junior Product Manager", "company": "X"},
        {"source": "linkedin", "job_id": "2", "title": "Robotics Product Manager", "company": "X"},
    ]
    kept, stats = S.enrich_with_jd(jobs, no_skip=True)

    assert stats["skipped"] == 0
    assert stats["fetched"] == 2
    assert all(j.get("jd_skipped") is None for j in kept)


def test_default_profile_is_the_v85_semantic_groups_only(monkeypatch):
    """SKIP.md §11.1 — with no CLI override the shipped behaviour is the v8.5
    semantic groups, and no legacy keyword pattern is layered on top."""
    monkeypatch.setattr(S, "fetch_jd", lambda job_id: {"jd_text": "JD", "jd_lines": ["JD"]})
    monkeypatch.setattr(S, "append_seen", lambda *a, **k: None)
    monkeypatch.setattr(S, "human_sleep", lambda *a, **k: None)

    jobs = [
        {"source": "linkedin", "job_id": "1", "title": "Junior Product Manager", "company": "X"},
        {"source": "linkedin", "job_id": "2", "title": "Robotics Product Manager", "company": "X"},
    ]
    kept, stats = S.enrich_with_jd(jobs)

    # Junior is killed by the v8.5 entry-level gate.
    assert stats["skipped"] == 1
    assert kept[0].get("jd_skipped") == "entry_level"
    # A title the legacy profile happened to contain is not killed by it.
    assert kept[1].get("jd_skipped") is None


# ---------------------------------------------------------------------------
# §12 — employment-type words are in the retained profile but do not skip
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Product Manager (Contract)",
        "AI Product Manager - Temporary",
        "Technical Product Manager - Temp Assignment",
        "Temp Product Manager",
        "Temporary Product Manager",
        "Contract Product Manager",
    ],
)
def test_employment_type_words_no_longer_skip(title):
    """SKIP.md §12 (v8.4 → v8.5 table: "contract" / "temp" / "temporary" no
    longer unconditional skip) — the words are still in the retained v8.4
    profile but the v8.5 filter KEEPs these titles."""
    assert any(word in S.DEFAULT_SKIP_KEYWORDS for word in ("contract", "temp", "temporary"))
    assert S.match_skip_reason(title) is None


def test_contract_recruiter_skips_on_role_not_on_the_contract_word():
    """SKIP.md §12 + the ``match_skip_reason`` docstring — "Contract
    Recruiter" still SKIPs, but because "recruiter" is a hard non-target role
    identity, not because of the employment-type word."""
    assert S.match_skip_reason("Contract Recruiter") == "hard_non_target"


# ---------------------------------------------------------------------------
# §14.6 — ONEZEROFOUR_EXTRA_SKIP env override
# ---------------------------------------------------------------------------
def test_onezerofour_extra_skip_env_override_replaces_the_pattern_list(monkeypatch):
    """SKIP.md §14.6 — ``ONEZEROFOUR_EXTRA_SKIP`` replaces the L6 pattern list;
    multiple regexes are separated by ``||``.  The module reads the env var at
    import time, so the override is exercised through an import reload that is
    undone in the teardown."""
    monkeypatch.setenv("ONEZEROFOUR_EXTRA_SKIP", "作業員|操作員||會計|財會")
    try:
        importlib.reload(S)
        assert S.ONEZEROFOUR_EXTRA_SKIP_PATTERNS == ["作業員|操作員", "會計|財會"]
        assert S.match_skip_reason("倉管主任", source="onezerofour") is None
        assert S.match_skip_reason("作業員", source="onezerofour") == "tw_extra_skip"
    finally:
        monkeypatch.delenv("ONEZEROFOUR_EXTRA_SKIP", raising=False)
        importlib.reload(S)

    assert len(S.ONEZEROFOUR_EXTRA_SKIP_PATTERNS) == 13
    assert S.match_skip_reason("倉管主任", source="onezerofour") == "tw_extra_skip"


def test_onezerofour_extra_skip_env_override_is_absent_by_default():
    """SKIP.md §14.6 — without the env var the 13 documented L6 groups are
    used."""
    assert not os.getenv("ONEZEROFOUR_EXTRA_SKIP")
    assert len(S.ONEZEROFOUR_EXTRA_SKIP_PATTERNS) == 13


# ---------------------------------------------------------------------------
# Known gap: the v1.2.1 skip-profile API is not implemented here
# ---------------------------------------------------------------------------
def test_v121_skip_profile_api_is_absent():
    """SKIP.md §11.1 — characterization case documenting a known gap: the
    v1.2.1 "skip profile" API (``ACTIVE_DEFAULT_SKIP_KEYWORDS`` /
    ``resolve_skip_words``) that the pre-existing upstream contract test
    ``tests/test_clean_default_skip_v121.py`` expects is NOT implemented in the
    qualified v8.5 Repair7 module.  That upstream test is a known
    pre-existing failure and is out of scope here; this test only records the
    current state."""
    if hasattr(S, "resolve_skip_words") or hasattr(S, "ACTIVE_DEFAULT_SKIP_KEYWORDS"):
        pytest.skip("v1.2.1 skip-profile API present; upstream contract test applies")
    assert not hasattr(S, "ACTIVE_DEFAULT_SKIP_KEYWORDS")
    assert not hasattr(S, "resolve_skip_words")
