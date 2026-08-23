from __future__ import annotations

import job_tracker as JT


class FakeWorksheet:
    def __init__(self, title: str, rows: list[list[str]] | None = None, wid: int = 1, row_count: int = 1000):
        self.title = title
        self._rows = rows or []
        self.id = wid
        self.row_count = row_count

    def row_values(self, row: int):
        assert row == 1
        return list(self._rows[0]) if self._rows else []

    def get_all_values(self):
        return [list(r) for r in self._rows]


class FakeSpreadsheet:
    def __init__(self, worksheets: list[FakeWorksheet]):
        self._worksheets = list(worksheets)

    def worksheets(self):
        return list(self._worksheets)

    def worksheet(self, title: str):
        for ws in self._worksheets:
            if ws.title == title:
                return ws
        raise RuntimeError("not found")


def test_schema_is_exact_a_to_aa_contract():
    assert JT.SCHEMA_VERSION == "job-tracker-v1"
    assert len(JT.HEADERS) == 27
    assert len(JT.HEADER_NOTES) == 27
    assert JT.HEADERS[:11] == (
        "Status｜狀態",
        "Priority｜優先級",
        "加入日期｜Added At",
        "Source｜來源",
        "Job URL｜職缺連結",
        "Company｜公司",
        "Job Title｜職稱",
        "JD | 描述",
        "Location｜地點",
        "Work Mode｜工作型態",
        "Visa / Constraint｜簽證限制",
    )
    assert JT.HEADERS[-2:] == (
        "Positioning / Selling Points｜定位賣點",
        "Risks / Next Action｜風險下一步",
    )


def test_default_region_pairs_match_reference_workbook():
    assert JT.expected_tabs() == [
        "SG-Raw", "SG-Selected",
        "TW-Raw", "TW-Selected",
        "China-Raw", "China-Selected",
    ]
    assert JT.canonical_region("Singapore") == "SG"
    assert JT.canonical_region("Taiwan") == "TW"
    assert JT.canonical_region("CN") == "China"


def test_validation_contract_matches_live_tracker():
    assert JT.VALIDATIONS[0] == ("New", "Scored", "Applied", "Interviewing", "Pending")
    assert JT.VALIDATIONS[1] == ("P0", "P1", "P2", "Low")
    assert JT.VALIDATIONS[9] == ("Remote", "Hybrid", "Onsite", "Unknown")
    assert JT.VALIDATIONS[15] == ("Apply", "Maybe", "Skip")
    assert len(JT.VALIDATIONS) == 7


def test_schema_request_contains_freeze_validation_conditional_and_widths():
    reqs = JT._schema_requests(123, 1000)
    kinds = [next(iter(r)) for r in reqs]
    assert "updateSheetProperties" in kinds
    assert kinds.count("setDataValidation") == 7
    assert kinds.count("addConditionalFormatRule") == 7
    assert kinds.count("updateDimensionProperties") == 28
    freeze = next(r["updateSheetProperties"] for r in reqs if "updateSheetProperties" in r)
    assert freeze["properties"]["gridProperties"]["frozenRowCount"] == 1


def test_plan_initialize_empty_default_sheet_creates_pairs_and_removes_default():
    sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [])])
    plan = JT.plan_initialize(sh, ["SG", "TW"])
    assert plan["create"] == ["SG-Raw", "SG-Selected", "TW-Raw", "TW-Selected"]
    assert plan["incompatible"] == []
    assert plan["remove_blank_defaults"] == ["Sheet1"]


def test_plan_initialize_preserves_compatible_existing_pair():
    good = [list(JT.HEADERS)]
    sh = FakeSpreadsheet([
        FakeWorksheet("SG-Raw", good, wid=11),
        FakeWorksheet("SG-Selected", good, wid=12),
    ])
    plan = JT.plan_initialize(sh, ["SG"])
    assert plan["create"] == []
    assert plan["configure_blank"] == []
    assert plan["already_compatible"] == ["SG-Raw", "SG-Selected"]
    assert plan["incompatible"] == []


def test_plan_initialize_fails_closed_on_nonempty_schema_mismatch():
    sh = FakeSpreadsheet([
        FakeWorksheet("SG-Raw", [["Status", "Priority", "Date"]], wid=11),
        FakeWorksheet("SG-Selected", [list(JT.HEADERS)], wid=12),
    ])
    plan = JT.plan_initialize(sh, ["SG"])
    assert len(plan["incompatible"]) == 1
    assert plan["incompatible"][0]["sheet"] == "SG-Raw"
    assert plan["incompatible"][0]["error_code"] == "SCHEMA_MISMATCH"


def test_resolve_region_worksheet_uses_name_not_user_gid():
    good = [list(JT.HEADERS)]
    sh = FakeSpreadsheet([FakeWorksheet("China-Raw", good, wid=488353479)])
    ws = JT.resolve_region_worksheet(sh, "China")
    assert ws.id == 488353479
    assert ws.title == "China-Raw"


def test_invalid_region_rejected():
    try:
        JT.canonical_region("../secret")
    except JT.TrackerError as exc:
        assert exc.error_code == "INVALID_REGION"
    else:
        raise AssertionError("invalid region should fail")
