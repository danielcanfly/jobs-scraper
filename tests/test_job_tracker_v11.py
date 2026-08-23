from __future__ import annotations

import job_tracker as JT


class FakeWorksheet:
    def __init__(
        self,
        title: str,
        rows: list[list[str]] | None = None,
        wid: int = 1,
        row_count: int = 1000,
        col_count: int = 26,
    ):
        self.title = title
        self._rows = rows or []
        self.id = wid
        self.row_count = row_count
        self.col_count = col_count
        self.added_rows = 0
        self.added_cols = 0

    def row_values(self, row: int):
        assert row == 1
        return list(self._rows[0]) if self._rows else []

    def get_all_values(self):
        return [list(r) for r in self._rows]

    def add_rows(self, count: int):
        self.added_rows += count
        self.row_count += count

    def add_cols(self, count: int):
        self.added_cols += count
        self.col_count += count


class FakeSpreadsheet:
    def __init__(self, worksheets: list[FakeWorksheet]):
        self._worksheets = list(worksheets)
        self.batch_bodies: list[dict] = []

    def worksheets(self):
        return list(self._worksheets)

    def worksheet(self, title: str):
        for ws in self._worksheets:
            if ws.title == title:
                return ws
        raise RuntimeError("not found")

    def batch_update(self, body: dict):
        self.batch_bodies.append(body)
        return {}


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


def test_reference_dimensions_are_locked_from_exported_tracker():
    assert JT.COLUMN_WIDTHS == (
        111, 111,
        124, 124, 124,
        172, 172, 172,
        137, 137, 137, 137, 137,
        133, 133, 133, 133,
        109, 109, 109, 109, 109, 109, 109, 109,
        286, 286,
    )
    assert JT.HEADER_HEIGHT_PX == 52


def test_schema_request_contains_freeze_validation_conditional_and_widths():
    reqs = JT._schema_requests(123, 1000)
    kinds = [next(iter(r)) for r in reqs]
    assert "updateSheetProperties" in kinds
    assert kinds.count("setDataValidation") == 7
    assert kinds.count("addConditionalFormatRule") == 7
    assert kinds.count("updateDimensionProperties") == 28
    freeze = next(r["updateSheetProperties"] for r in reqs if "updateSheetProperties" in r)
    assert freeze["properties"]["gridProperties"]["frozenRowCount"] == 1
    dimensions = [r["updateDimensionProperties"] for r in reqs if "updateDimensionProperties" in r]
    assert dimensions[-1]["properties"]["pixelSize"] == 52


def test_apply_schema_grows_small_blank_grid_before_batch_update():
    ws = FakeWorksheet("SG-Raw", [], row_count=50, col_count=10)
    sh = FakeSpreadsheet([ws])
    JT._apply_schema(sh, ws)
    assert ws.col_count == 27
    assert ws.row_count == 1000
    assert ws.added_cols == 17
    assert ws.added_rows == 950
    assert len(sh.batch_bodies) == 1


def test_plan_initialize_empty_default_sheet_creates_pairs_and_removes_default():
    sh = FakeSpreadsheet([FakeWorksheet("Sheet1", [])])
    plan = JT.plan_initialize(sh, ["SG", "TW"])
    assert plan["create"] == ["SG-Raw", "SG-Selected", "TW-Raw", "TW-Selected"]
    assert plan["incompatible"] == []
    assert plan["remove_blank_defaults"] == ["Sheet1"]


def test_plan_initialize_preserves_compatible_existing_pair():
    good = [list(JT.HEADERS)]
    sh = FakeSpreadsheet([
        FakeWorksheet("SG-Raw", good, wid=11, col_count=27),
        FakeWorksheet("SG-Selected", good, wid=12, col_count=27),
    ])
    plan = JT.plan_initialize(sh, ["SG"])
    assert plan["create"] == []
    assert plan["configure_blank"] == []
    assert plan["already_compatible"] == ["SG-Raw", "SG-Selected"]
    assert plan["incompatible"] == []


def test_plan_initialize_fails_closed_on_nonempty_schema_mismatch():
    sh = FakeSpreadsheet([
        FakeWorksheet("SG-Raw", [["Status", "Priority", "Date"]], wid=11),
        FakeWorksheet("SG-Selected", [list(JT.HEADERS)], wid=12, col_count=27),
    ])
    plan = JT.plan_initialize(sh, ["SG"])
    assert len(plan["incompatible"]) == 1
    assert plan["incompatible"][0]["sheet"] == "SG-Raw"
    assert plan["incompatible"][0]["error_code"] == "SCHEMA_MISMATCH"


def test_resolve_region_worksheet_uses_name_not_user_gid():
    good = [list(JT.HEADERS)]
    sh = FakeSpreadsheet([FakeWorksheet("China-Raw", good, wid=488353479, col_count=27)])
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
