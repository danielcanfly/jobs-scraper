"""Rebuilt v8.5 Repair7 skip-filter contract suite.

PROVENANCE
----------
The original ``tests/test_v85_hostile.py`` (~163 cases) and its 405-row truth
table were lost (they lived under ``/tmp`` and were removed by macOS cleanup).
This file is the rebuilt equivalent.  The expectations were **not** written from
imagination: every case below was produced by calling the qualified
``sg_product_jobs.match_skip_reason`` (v8.5 Repair7) and dumping
``title -> reason`` to a CSV, after which the dump was checked line by line
against the written specification in ``SKIP.md``.

``SKIP.md`` is the canonical written spec.  Each test function's docstring
names the ``SKIP.md`` section it enforces.  Where a case is reconstructed from
the implementation rather than from explicit spec prose, the docstring says so
("characterization case").

The skip filter is a FROZEN, adjudicated contract (qualified 2026-08-30 after
7 rounds of repair).  This suite must never be "fixed" to match a changed
implementation: if the implementation and ``SKIP.md`` disagree, that is a
finding to escalate, not a test to rewrite.

REASON CODES returned by ``match_skip_reason``:
    None                -> KEEP
    "entry_level"       -> L1 entry-level gate
    "assistant"         -> assistant narrow rule (not rescued)
    "hard_non_target"   -> L2 hard non-target role identity
    "contextual_role"   -> L3 contextual role-shape (sales/quality/test/support)
    "specialist"        -> L5 specialist narrow rule (not rescued)
    "chinese_skip"      -> L4 Chinese general skip
    "tw_extra_skip"     -> L6 source-specific (104 / cake only)
"""

from __future__ import annotations

import pytest

import sg_product_jobs as S


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _reason(title: str, source: str | None = None) -> str | None:
    """Call the frozen entry point under test."""
    return S.match_skip_reason(title, source=source)


# ---------------------------------------------------------------------------
# §3.1 L0 target-role guard — English PM variants (KEEP)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Product Manager",
        "Senior Product Manager",
        "AI Product Manager",
        "Lead Product Manager",
        "Group Product Manager",
        "Product Director",
        "VP of Product",
        "Chief Product Officer",
        "Product Owner",
        "Head of Product",
        "Director of Product",
        "Technical Product Manager",
        "Principal Product Manager, Trust & Quality",
        "AI Product Manager - 12 Month Contract",
        "Product Lead",
        "Head of AI",
        "Director of AI",
        "Director of Product Engineering",
        "Director of Product, Quality Platform",
        "Senior Product Director",
    ],
)
def test_l0_target_role_guard_keeps_english_pm_variants(title):
    """SKIP.md §3.1 (TARGET_ROLE_PATTERNS) + §13.2 — every standard PM
    leadership/title variant is KEEP (match_skip_reason returns None)."""
    assert _reason(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "產品經理",
        "產品主管",
        "產品總監",
        "產品負責人",
        "產品長",
        "產品經理－銷售平台",
        "產品經理－品質與信任",
        "產品總監－銷售科技",
        "產品經理－客服自動化",
    ],
)
def test_l0_target_role_guard_keeps_chinese_pm_variants(title):
    """SKIP.md §3.2 — the 5 Chinese target substrings, plus the §13.2 Chinese
    PM examples that embed contextual words (銷售/品質/客服)."""
    assert _reason(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "Director of Product Marketing",
        "Director of Product Design",
        "VP of Product Marketing",
        "VP Product-Marketing",
        "VP of Product Support",
        "Head of Product-Marketing",
        "Head of Product\u2013Marketing",
        "Head of Product\u2011Marketing",
        "Product Marketing Manager",
        "Product Analyst",
        "Product Validation Engineer",
        "Product Certification Specialist",
    ],
)
def test_l0_negative_lookahead_rejects_non_target_product_suffixes(title):
    """SKIP.md §3.4 / §3.4.1 — the shared ``_V85_NON_TARGET_PRODUCT_SUFFIX_LOOKAHEAD``
    vetoes marketing/design/analyst/validation/certification/support suffixes, so
    these titles fall through to L2 and SKIP as ``hard_non_target``."""
    assert _reason(title) == "hard_non_target"


# ---------------------------------------------------------------------------
# §4 L1 entry-level gate
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Junior Product Manager",
        "Jr Product Manager",
        "Product Manager Intern",
        "Product Management Intern",
        "Graduate Product Manager",
        "Trainee Product Manager",
        "Entry Level Product Manager",
        "Product Manager Trainee",
        "Product Manager Internship",
        "產品經理實習生",
        "初階產品經理",
        "產品助理",
        "工讀生",
        "應屆畢業生產品經理",
        "實習生",
        "培訓專員",
        "訓練生",
    ],
)
def test_l1_entry_level_gate_skips_before_target_guard(title):
    """SKIP.md §4 + §13.3 — entry-level titles SKIP with reason ``entry_level``
    even though they contain a target role ("Junior Product Manager")."""
    assert _reason(title) == "entry_level"


def test_l1_entry_level_pattern_list_is_the_documented_set():
    """SKIP.md §4.1/§4.2 — ENTRY_LEVEL_PATTERNS still carries the documented
    English + Chinese entry-level words."""
    joined = " ".join(S.ENTRY_LEVEL_PATTERNS)
    for word in ["intern", "internship", "trainee", "graduate", "junior"]:
        assert word in joined
    for word in ["實習", "工讀", "培訓", "訓練生", "應屆", "畢業", "助理", "初階"]:
        assert word in joined


# ---------------------------------------------------------------------------
# §5 Assistant narrow rule
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Assistant Vice President, Product",
        "Assistant VP, AI Product",
        "Assistant Director, Product Management",
        "Assistant VP, Data Platform",
        "Assistant VP, Growth",
        "Assistant Director, Product",
        "Asst VP, Product",
        "Asst. VP, Product",
    ],
)
def test_assistant_narrow_rule_keeps_senior_trigger_plus_target_context(title):
    """SKIP.md §5.2 — assistant + (VP / vice president / director) adjacent AND a
    target context (product / ai / platform / growth / data) is KEEP."""
    assert _reason(title) is None


@pytest.mark.parametrize(
    "title",
    [
        "Assistant to CEO",
        "Administrative Assistant",
        "Assistant Vice President, Finance",
        "Assistant Product Manager",
        "Assistant Manager, Sales",
        "Assistant VP, Retail",
        "Assistant Manager, Product",
        "Assistant Head of Product",
    ],
)
def test_assistant_narrow_rule_skips_without_senior_trigger_or_context(title):
    """SKIP.md §5.3 — assistant titles that lack an adjacent senior trigger
    ("Assistant to CEO", "Assistant Manager, Sales") or lack a target context
    ("Assistant VP, Retail") SKIP with reason ``assistant``."""
    assert _reason(title) == "assistant"


@pytest.mark.parametrize(
    "title",
    [
        "Assistant Director, Human Resources",
        "Assistant VP, Accounting",
        "Assistant Director, Product Design",
        "Assistant Director, Product Validation",
    ],
)
def test_assistant_hard_non_target_veto_beats_assistant_narrow_rule(title):
    """SKIP.md §2 step 3 + §5 — a hard non-target role identity vetoes the
    assistant narrow rule, so the reason is ``hard_non_target`` (not
    ``assistant``) even when a senior trigger is adjacent."""
    assert _reason(title) == "hard_non_target"


def test_assistant_narrow_rule_uses_word_boundary_contexts():
    """SKIP.md §5.1 (Repair1) — the assistant target contexts are compiled with
    word boundaries, so "Retail" (which contains the letters "ai") must not
    count as an "ai" context."""
    assert S.ASSISTANT_KEEP_CONTEXT_REGEX.search("retail") is None
    assert S.ASSISTANT_KEEP_CONTEXT_REGEX.search("ai product") is not None


def test_assistant_senior_triggers_are_the_narrow_leadership_set():
    """SKIP.md §5.1 / §11.2 — the assistant rule uses its own narrow senior
    trigger list (vice president / vp / director / avp); "manager" and "head"
    are deliberately NOT triggers."""
    assert S.ASSISTANT_SENIOR_TRIGGERS == ["vice president", "vp", "director", "avp"]


# ---------------------------------------------------------------------------
# §6 L2 hard non-target role (no senior rescue)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Senior Product Designer",
        "Product Designers",
        "VP Human Resources",
        "Senior Account Manager",
        "Senior Accountant",
        "Senior Auditor",
        "Finance Audit Director",
        "Senior Recruiter",
        "Director of Recruiting",
        "Head of Recruitment",
        "Senior Buyer",
        "Director of Procurement",
        "Senior Purchaser",
        "Senior Merchandiser",
        "Senior Business Development Manager",
        "Director, Key Account Management",
        "Senior Client Manager",
        "Senior Relationship Manager",
        "Senior Account Executive",
        "Quality Inspector",
        "Test Inspector",
        "Inspection Engineer",
        "Senior Test Coordinator",
        "Office Administrator",
        "Legal Clerk",
        "Executive Secretary",
    ],
)
def test_l2_hard_non_target_role_skips_despite_senior_marker(title):
    """SKIP.md §6.1/§6.2 + §13.1 — hard non-target role identities SKIP with
    reason ``hard_non_target`` and are NOT rescued by a senior marker."""
    assert _reason(title) == "hard_non_target"


@pytest.mark.parametrize(
    "title",
    [
        "會計經理",
        "人資總監",
        "採購副總",
        "行銷專員",
        "市場專員",
        "協調員",
        "行政專員",
        "秘書",
        "書記",
        "稅務專員",
        "稽核員",
        "出納",
        "財會主管",
        "薪酬專員",
        "招募專員",
        "總務主任",
    ],
)
def test_l2_hard_non_target_chinese_substrings_skip(title):
    """SKIP.md §6.3 — the Chinese hard non-target substrings (accounting / HR /
    procurement / admin / marketing) SKIP with reason ``hard_non_target``."""
    assert _reason(title) == "hard_non_target"


def test_l2_bare_sales_is_not_hard_non_target():
    """SKIP.md §6.4 — bare "sales" was removed from L2 on purpose; it is handled
    by L3 role-shape only, so a bare sales token must not produce
    ``hard_non_target``."""
    assert "sales" not in " ".join(S.HARD_NON_TARGET_ROLE_PATTERNS)
    assert _reason("Program Manager, Sales Platform") is None


# ---------------------------------------------------------------------------
# §7 L3 contextual role-shape exclusion
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Sales Manager",
        "Senior Sales Manager",
        "Sales Director",
        "Head of Sales",
        "VP Sales",
        "VP / Sales",
        "AVP - Sales",
        "SVP \u2013 Sales",
        "Head, Sales",
        "Sales - Lead",
        "Sales Executive",
        "Sales Engineer",
        "Sales Development Manager",
        "Sales Operations Manager",
        "Sales Enablement Lead",
        "Sales Strategy Director",
        "Sales & Marketing Manager",
        "Sales and Marketing Lead",
        "Chief Sales Officer",
        "Manager, Sales Development",
        "Senior Manager - Sales Operations",
        "Lead, Sales Strategy",
    ],
)
def test_l3_sales_role_shape_skips(title):
    """SKIP.md §7.1.1/§7.2 — Sales only skips in role shape, across the
    documented separator typography (space / comma / hyphen / slash / figure
    dash / non-breaking hyphen / en dash) and both word orders."""
    assert _reason(title) == "contextual_role"


@pytest.mark.parametrize(
    "title",
    [
        "Quality Director",
        "Senior QA Manager",
        "Senior Test Engineer",
        "QA Engineer",
        "Testing Specialist",
        "Test Engineering Manager",
        "QA Engineering Lead",
        "Director of QA",
        "Head of Testing",
        "VP of QA",
        "Director of Quality",
        "Head of Quality",
        "VP of Quality",
        "AVP of Quality",
        "Director of Quality Assurance",
        "Director of Quality Engineering",
        "Quality Assurance Lead",
        "Quality Engineering Manager",
    ],
)
def test_l3_quality_qa_test_role_shape_skips(title):
    """SKIP.md §7.1.2 (Repair7 P1-02/P1-03) — the Quality / QA / Test families
    are bidirectional: forward ``quality <role>`` and reverse
    ``Director/Head/VP/AVP of Quality`` both SKIP as ``contextual_role``."""
    assert _reason(title) == "contextual_role"


@pytest.mark.parametrize(
    "title",
    [
        "Customer Support Engineer",
        "Customer Support Operations Manager",
        "Technical Support Engineer",
        "Application Support Specialist",
        "Support Operations Manager",
        "Support Engineer",
        "Director of Customer Support",
        "Head of Support",
    ],
)
def test_l3_support_role_shape_skips(title):
    """SKIP.md §7.1.2 (Repair7 P1-04) — the Support family is bidirectional and
    role-shaped only."""
    assert _reason(title) == "contextual_role"


@pytest.mark.parametrize(
    "title",
    [
        "業務經理",
        "銷售主管",
        "業務開發專員",
        "銷售開發工程師",
        "品質經理",
        "品質部經理",
        "品質保證工程師",
        "品質管理專員",
        "品管經理",
        "品管部經理",
        "品保工程師",
        "測試工程師",
        "測試部工程師",
        "客服專員",
        "客服部專員",
        "客服副總",
        "技術支援工程師",
        "技術支援部專員",
        "技術服務代表",
    ],
)
def test_l3_chinese_role_shape_skips(title):
    """SKIP.md §7.1.2 (Repair7 P1-05) + §7.3 — the 9 Chinese contextual
    families (業務/銷售/業務開發/銷售開發/品質/品質保證/品質管理/品管/品保/測試/
    客服/技術支援/技術服務) skip in role shape, with the optional 部門粒度
    ``部`` particle."""
    assert _reason(title) == "contextual_role"


@pytest.mark.parametrize(
    "title",
    [
        "Program Manager, Sales Platform",
        "Strategy Manager, Data Quality",
        "AI Platform Lead, Customer Support Automation",
        "Product Operations Lead, Test Infrastructure",
        "Product Manager, Sales Platform",
        "Product Manager, Data Quality",
        "Product Manager, Customer Support Platform",
        "Product Manager, Test Infrastructure",
        "Product Manager, Quality & Trust",
        "AI Platform Lead, Quality Engineering",
        "Sales Platform Engineer",
        "Product/Marketing Manager",
    ],
)
def test_l3_bare_contextual_words_do_not_kill(title):
    """SKIP.md §7.4 (G01/G02/G03) + §7.1.2 + §3.4.1 — a bare domain word
    ("sales" / "quality" / "support" / "test") without a role suffix does NOT
    kill; and no global punctuation normalization is applied, so
    "Product/Marketing" stays two tokens."""
    assert _reason(title) is None


# ---------------------------------------------------------------------------
# §8 L5 specialist narrow rule
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "Senior Product Specialist",
        "Principal AI Product Specialist",
        "AVP, Product Specialist",
        "Senior Platform Specialist",
        "Senior Data Specialist",
        "Staff UX Specialist",
        "Lead Growth Specialist",
        "Senior Operations Specialist",
    ],
)
def test_l5_specialist_narrow_rule_keeps_senior_plus_target_context(title):
    """SKIP.md §8.2 — specialist titles keep only when a senior marker AND a
    target context (product / ai / platform / data / growth / ux / operations)
    are both present."""
    assert _reason(title) is None


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Product Specialist", "specialist"),
        ("Senior Marketing Specialist", "specialist"),
        # §8.3 lists these under the specialist rule, but L2/L3 fire first, so
        # the runtime reason is the earlier layer (outcome SKIP either way).
        ("Senior Recruitment Specialist", "hard_non_target"),
        ("Senior Sales Specialist", "contextual_role"),
        ("Quality Specialist", "contextual_role"),
    ],
)
def test_l5_specialist_narrow_rule_skips(title, expected):
    """SKIP.md §8.3 — specialist titles without senior+target are SKIP; the
    reason code is the earliest layer that matched (characterization: the spec
    groups all five under L5, the runtime attributes three of them to L2/L3)."""
    assert _reason(title) == expected


def test_l5_specialist_keep_contexts_are_the_documented_set():
    """SKIP.md §8.1 — the English half of SPECIALIST_KEEP_CONTEXTS is exactly the
    documented list.  The Chinese half (產品/平台/數據/用戶增長) is a
    characterization case: the §8.1 snippet lists only the English contexts, the
    qualified implementation additionally carries the Chinese ones."""
    assert S.SPECIALIST_KEEP_CONTEXTS[:7] == [
        "product",
        "ai",
        "platform",
        "data",
        "growth",
        "ux",
        "operations",
    ]
    assert S.SPECIALIST_KEEP_CONTEXTS[7:] == ["產品", "平台", "數據", "用戶增長"]


def test_l5_specialist_contexts_use_word_boundaries():
    """SKIP.md §8.1 (Repair1) — "ai" / "ux" are word-bounded so "retail" and
    "luxury" cannot fake a target context."""
    assert S.SPECIALIST_KEEP_CONTEXT_REGEX.search("retail") is None
    assert S.SPECIALIST_KEEP_CONTEXT_REGEX.search("luxury") is None
    assert S.SPECIALIST_KEEP_CONTEXT_REGEX.search("ai product") is not None


# ---------------------------------------------------------------------------
# §9 L4 Chinese general skip
# ---------------------------------------------------------------------------
def test_l4_chinese_skip_pattern_list_has_eight_entries():
    """SKIP.md §9.1 — the runtime CHINESE_SKIP_PATTERNS list holds exactly the
    8 documented regex entries."""
    assert len(S.CHINESE_SKIP_PATTERNS) == 8


@pytest.mark.parametrize(
    "word",
    [
        "實習",
        "工讀",
        "培訓",
        "訓練生",
        "應屆",
        "畢業",
        "助理",
        "初階",
        "秘書",
        "行政",
        "協調",
        "統籌",
        "工讀生",
        "書記",
        "行銷",
        "市場專員",
    ],
)
def test_l4_chinese_skip_layer_is_shadowed_by_earlier_layers(word):
    """SKIP.md §2 step 8 + §9 — characterization case: every L4 Chinese trigger
    word is already caught by an earlier layer (L1 entry-level for the
    intern/trainee/graduate/assistant/junior words, L2 hard non-target for
    秘書/行政/協調/統籌/書記/行銷/市場專員), so the ``chinese_skip`` reason code
    is unreachable in the qualified implementation.  The SKIP outcome is
    unchanged; only the reason attribution differs."""
    reason = _reason(f"{word}專員")
    assert reason in {"entry_level", "hard_non_target"}
    assert reason != "chinese_skip"


def test_l4_chinese_skip_reason_is_never_produced():
    """SKIP.md §2 step 8 — characterization case: with the qualified Repair7
    implementation no title reaches the L4 Chinese general skip layer, so
    ``chinese_skip`` is never returned."""
    reasons = {
        _reason(f"{word}{suffix}")
        for word in [
            "實習",
            "工讀",
            "培訓",
            "訓練生",
            "應屆",
            "畢業",
            "助理",
            "初階",
            "秘書",
            "行政",
            "協調",
            "統籌",
            "工讀生",
            "書記",
            "行銷",
            "市場專員",
        ]
        for suffix in ["", "專員", "主任", "工程師", "經理"]
    }
    assert "chinese_skip" not in reasons


# ---------------------------------------------------------------------------
# §10 L6 source-specific (onezerofour + cake)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "title",
    [
        "主任倉管",
        "門市店長",
        "作業員",
        "包裝作業員",
        "品檢員",
        "工地主任",
        "保全人員",
        "司機",
        "廚師",
        "安親老師",
        "法務專員",
        "護理師",
    ],
)
@pytest.mark.parametrize("source", ["onezerofour", "cake"])
def test_l6_taiwan_specific_titles_skip_for_l6_sources(title, source):
    """SKIP.md §10 — the 104/Cake L6 layer (13 regex groups, 64 words) skips
    Taiwan-specific non-PM titles with reason ``tw_extra_skip``."""
    assert _reason(title, source=source) == "tw_extra_skip"


@pytest.mark.parametrize("source", [None, "linkedin", "jobstreet", "jora"])
@pytest.mark.parametrize(
    "title",
    [
        "主任倉管",
        "門市店長",
        "作業員",
        "安親老師",
        "護理師",
    ],
)
def test_l6_does_not_fire_for_non_l6_sources(title, source):
    """SKIP.md §10 — the L6 layer is source-gated: for linkedin / jobstreet /
    jora / no source the same titles are KEEP."""
    assert _reason(title, source=source) is None


def test_l6_source_set_is_onezerofour_and_cake():
    """SKIP.md §10 — ``_L6_SOURCES`` is the set of sources running the L6 layer."""
    assert S._L6_SOURCES == {"onezerofour", "cake"}


def test_l6_pattern_group_and_word_counts_match_the_spec():
    """SKIP.md §10 — L6 carries 13 regex groups covering 64 Taiwan-specific
    words."""
    assert len(S.ONEZEROFOUR_EXTRA_SKIP_PATTERNS) == 13
    word_count = sum(len(p.split("|")) for p in S.ONEZEROFOUR_EXTRA_SKIP_PATTERNS)
    assert word_count == 64


def test_l6_is_shadowed_by_l2_for_行政幹事():
    """SKIP.md §10 — characterization case: the L6 group documents "行政幹事" as
    an example, but L2's Chinese substring 行政 fires first, so the reason is
    ``hard_non_target`` for every source (outcome SKIP either way)."""
    assert _reason("行政幹事", source="onezerofour") == "hard_non_target"
    assert _reason("行政幹事") == "hard_non_target"


# ---------------------------------------------------------------------------
# §11 backward-compat structures / senior whitelist
# ---------------------------------------------------------------------------
def test_whitelist_rules_are_preserved_as_documented():
    """SKIP.md §11.4 — WHITELIST_RULES is retained as v8.4 documentation:
    {"assistant": "adjacent", "specialist": "anywhere"}."""
    assert S.WHITELIST_RULES == {"assistant": "adjacent", "specialist": "anywhere"}


def test_senior_markers_constant_is_preserved():
    """SKIP.md §11.2 — SENIOR_MARKERS_ANYWHERE is retained (generic EN + CN
    senior vocabulary)."""
    for marker in ["senior", "principal", "avp", "director", "head", "chief", "lead"]:
        assert marker in S.SENIOR_MARKERS_ANYWHERE
    for marker in ["資深", "主任", "總監"]:
        assert marker in S.SENIOR_MARKERS_ANYWHERE


def test_senior_marker_matching_is_word_bounded_for_english():
    """SKIP.md §11.2 (2026-08-29 word-boundary fix) — "cto" inside "inspector"
    must not be read as a senior marker; Chinese markers stay substring."""
    assert S._has_senior_marker_anywhere("Quality Inspector") is False
    assert S._has_senior_marker_anywhere("inspector") is False
    assert S._has_senior_marker_anywhere("資深產品專家") is True
    assert S._has_senior_marker_anywhere("Senior Product Manager") is True


def test_no_global_senior_rescue():
    """SKIP.md §1 + §12 — v8.5 removed the global "senior marker rescues any
    skip hit" rule: a senior non-PM title still SKIPs."""
    assert _reason("Senior Accountant") == "hard_non_target"
    assert _reason("Director of Sales") == "contextual_role"
    assert _reason("Senior QA Manager") == "contextual_role"
    assert _reason("Head of Procurement") == "hard_non_target"


# ---------------------------------------------------------------------------
# §2 precedence order
# ---------------------------------------------------------------------------
def test_empty_title_is_a_control_state_keep():
    """SKIP.md §2 step 1 / step 10 — an empty title is a control state, not a
    filter layer: it KEEPs."""
    assert _reason("") is None
    assert _reason(None) is None


@pytest.mark.parametrize(
    "title,expected",
    [
        # L1 entry-level outranks the L0 target guard.
        ("Junior Product Manager", "entry_level"),
        ("Product Manager Intern", "entry_level"),
        # The assistant narrow rule outranks the L0 target guard.
        ("Assistant Product Manager", "assistant"),
        # The assistant hard-non-target veto outranks the assistant narrow rule.
        ("Assistant Director, Product Design", "hard_non_target"),
        # L0 target guard outranks L2/L3.
        ("Product Manager, Sales Platform", None),
        ("Head of Product, Human Resources", None),
        # L2 hard non-target outranks L3 and L5.
        ("Senior Product Designer", "hard_non_target"),
        ("Senior Recruitment Specialist", "hard_non_target"),
        # L3 contextual outranks L5 specialist.
        ("Senior Sales Specialist", "contextual_role"),
        ("Quality Specialist", "contextual_role"),
    ],
)
def test_precedence_order_between_layers(title, expected):
    """SKIP.md §2 (the 10 executable steps) — locks the relative order of the
    layers: L1 entry-level > assistant narrow > L0 target > L2 hard non-target >
    L3 contextual > L5 specialist > L4 Chinese > L6 source-specific."""
    assert _reason(title) == expected


def test_l6_is_the_last_layer():
    """SKIP.md §2 steps 8-9 — the L6 source-specific layer is last, so an
    L4/L2-visible title never reaches it with a different reason."""
    assert _reason("行政幹事", source="onezerofour") == "hard_non_target"
    assert _reason("倉管主任", source="onezerofour") == "tw_extra_skip"


# ---------------------------------------------------------------------------
# §3.4.1 / §3.4.2 / §7.1.1 / §7.1.2 — shared fragments
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sep",
    [" ", ",", "-", "/", "\u2012", "\u2011", "\u2013"],
)
def test_sales_separator_fragment_covers_all_documented_separators(sep):
    """SKIP.md §7.1.1 — ``_V85_SALES_SEP`` accepts whitespace, comma, ASCII
    hyphen, slash, figure dash (U+2012), non-breaking hyphen (U+2011) and
    en dash (U+2013)."""
    assert S._V85_SALES_SEP == r"[\s,\-/\u2012\u2011\u2013]+"
    assert _reason(f"Sales{sep}Manager") == "contextual_role"


@pytest.mark.parametrize("sep", [" ", "-", "\u2011", "\u2013"])
def test_product_family_separator_fragment_covers_documented_separators(sep):
    """SKIP.md §3.4.1 — ``_V85_PRODUCT_FAMILY_SEP`` accepts whitespace, ASCII
    hyphen, U+2011 and U+2013 (and NOT figure dash / slash, per the §3.4.1
    note that no global punctuation normalization happens)."""
    assert S._V85_PRODUCT_FAMILY_SEP == r"[\s\u2011\u2013\-]+"
    assert _reason(f"VP of Product{sep}Marketing") == "hard_non_target"


@pytest.mark.parametrize("sep", ["\u2012", "/"])
def test_product_family_separator_rejects_undocumented_separators(sep):
    """SKIP.md §3.4.1 — the Product family separator deliberately does not
    accept figure dash (U+2012) or slash, so those titles are not treated as
    the "Product Marketing" family."""
    assert _reason(f"VP of Product{sep}Marketing") is None


@pytest.mark.parametrize(
    "title",
    ["品質經理", "品質部經理", "品管經理", "品管部經理", "客服專員", "客服部專員"],
)
def test_chinese_org_particle_is_optional(title):
    """SKIP.md §7.1.2 (Repair7 P1-05) — ``_V85_CN_ORG_PARTICLE`` makes the 部門
    particle ``部`` optional, so both 品質經理 and 品質部經理 hit L3."""
    assert S._V85_CN_ORG_PARTICLE == r"(部\s*)?"
    assert _reason(title) == "contextual_role"


def test_compile_mixed_uses_cjk_ideograph_range_not_ord_128():
    """SKIP.md §3.4.2 (Repair7 P1-06) — CJK detection inside
    ``_v85_compile_mixed`` uses the real CJK ideograph ranges, so a pattern
    list containing a non-CJK non-ASCII char (figure dash) still gets the
    English word-boundary wrap instead of being misrouted to the substring
    branch."""
    en_only = S._v85_compile_mixed([r"alpha\u2012beta"])
    assert "(?<![a-z])" in en_only.pattern
    assert "(?![a-z])" in en_only.pattern

    # NOTE: the CJK test must use *real* ideographs, not a regex escape:
    # "\\u4e2d" as source text contains no ideograph, so the detector cannot
    # see it (only the compiled regex would).
    zh_list = S._v85_compile_mixed(["中文"])
    assert "(?<![a-z])" not in zh_list.pattern
    assert "(?![a-z])" not in zh_list.pattern


def test_compile_mixed_word_boundary_prevents_substring_false_positives():
    """SKIP.md §3.4.2 — the R7 P1-06 regression: with the word-boundary wrap
    "Quality Engineer" must NOT match inside "Quality Engineering"."""
    compiled = S._v85_compile_mixed([r"quality\s+engineer"])
    assert compiled.search("Quality Engineering") is None
    assert compiled.search("Quality Engineer") is not None


def test_compile_contexts_as_regex_applies_word_boundaries():
    """SKIP.md §5.1 / §8.1 (Repair1) — ``_v85_compile_contexts_as_regex``
    word-bounds English contexts and escapes regex meta characters."""
    compiled = S._v85_compile_contexts_as_regex(["ai", "ux"])
    assert compiled.pattern == r"(?:\bai\b|\bux\b)"
    assert compiled.search("retail") is None
    assert compiled.search("ai product") is not None

    escaped = S._v85_compile_contexts_as_regex(["a.b"])
    assert escaped.search("axb") is None
    assert escaped.search("a.b") is not None


def test_context_role_noun_fragment_is_the_documented_closure():
    """SKIP.md §7.1.2 (Repair7 P1-01) — the shared ``_V85_CTX_ROLE_NOUN``
    fragment covers the documented role nouns and is used by all five
    contextual families."""
    fragment = S._V85_CTX_ROLE_NOUN
    for noun in [
        "manager",
        "director",
        "head",
        "vp",
        "lead",
        "chief",
        "officer",
        "specialist",
        "engineer",
        "executive",
        "consultant",
        "analyst",
        "coordinator",
        "associate",
        "rep",
        "representative",
        "technician",
        "architect",
        "supervisor",
        "administrator",
        "advisor",
        "operator",
    ]:
        assert noun in fragment
    # "automation" / "control" / "assurance" are deliberately excluded so a
    # domain name is not mistaken for a role noun.
    assert "automation" not in fragment
    assert "control" not in fragment
    assert "assurance" not in fragment


def test_target_role_regex_is_word_bounded_for_english():
    """SKIP.md §3.3 — TARGET_ROLE_REGEX is compiled by ``_v85_compile_mixed``,
    so English target roles are word-bounded while Chinese ones are substrings."""
    assert S.TARGET_ROLE_REGEX.search("Product Manager") is not None
    assert S.TARGET_ROLE_REGEX.search("產品經理") is not None
    assert S.TARGET_ROLE_REGEX.search("Reproduction Manager") is None


# ---------------------------------------------------------------------------
# §11.1 — v8.5 ignores the deprecated skip_pat argument
# ---------------------------------------------------------------------------
def test_match_skip_reason_ignores_the_deprecated_skip_pattern():
    """SKIP.md §11.1 — ``skip_pat`` is accepted for backward compatibility but
    ignored by v8.5; the semantic groups alone decide.  A custom pattern
    therefore cannot change the outcome."""
    pattern = S._make_skip_pattern(["robotics"])
    assert pattern.search("Robotics Product Manager") is not None
    assert _reason("Robotics Product Manager") is None
    assert S.match_skip_reason("Junior Product Manager", pattern) == "entry_level"


def test_match_skip_reason_public_signature_still_accepts_skip_pat():
    """SKIP.md §11.1 — the public signature
    ``match_skip_reason(title, skip_pat=None, *, source=None)`` is preserved."""
    import inspect

    sig = inspect.signature(S.match_skip_reason)
    assert list(sig.parameters) == ["title", "skip_pat", "source"]
    assert sig.parameters["skip_pat"].default is None
    assert sig.parameters["source"].kind is inspect.Parameter.KEYWORD_ONLY
