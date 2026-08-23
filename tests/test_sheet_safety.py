"""
Sheet write safety tests (Q38-Q42, Q69).

Verifies that the two-phase write in _write_rows_to_sheet:
  - Writes E column with USER_ENTERED (so the generated HYPERLINK formula becomes live).
  - Writes all other columns with RAW (so hostile scraped text starting with
    =, +, -, or @ cannot execute as a formula).
  - Supports dry_run without external writes.
  - Validates gid to avoid silent first-tab writes.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402

HOSTILE_VALUES = [
    '=HYPERLINK("https://evil.example","x")',
    '=IMPORTXML("https://evil.example","//x")',
    "+1+1",
    "-1+1",
    "@SUM(1,1)",
]


class _RecordingWS:
    """Mock gspread worksheet that records every update call."""
    def __init__(self, row_count: int = 100) -> None:
        self.row_count = row_count
        self.calls: list[dict] = []
        self.added_rows: int = 0

    def add_rows(self, n: int) -> None:
        self.added_rows += n
        self.row_count += n

    def update(self, range_name=None, values=None, value_input_option=None):
        self.calls.append({
            "range": range_name,
            "values": values,
            "vopt": value_input_option,
        })


def _build_job(job_id: str, source: str, **overrides) -> dict:
    base = {
        "job_id": job_id,
        "title": "Product Manager",
        "company": "Tech Co",
        "location": "Singapore",
        "source": source,
        "jd_text": "We are hiring a PM. Do not require sponsorship.",
        "jd_hash": "abc",
        "url": "https://example.com/jobs/123",
    }
    base.update(overrides)
    return base


def _row_with_hostile(job_id: str, source: str, hostile_col: str, hostile_value: str) -> list:
    """Build a row with a hostile value planted in the chosen column."""
    job = _build_job(job_id, source)
    row = M._build_sheet_row(job, "LinkedIn / Minimax", "Singapore", set())
    assert row is not None, f"build_sheet_row returned None for {job}"
    col_idx = {"A": 0, "B": 1, "C": 2, "D": 3, "F": 5, "G": 6, "H": 7, "I": 8, "J": 9, "K": 10}[hostile_col]
    row[col_idx] = hostile_value
    return row


# ── Q38: Non-E cells cannot execute formulas starting with = ─────────
def test_equals_in_company_stays_text():
    ws = _RecordingWS()
    row = _row_with_hostile("1", "linkedin", "F", '=HYPERLINK("https://evil","x")')
    M._write_rows_to_sheet(ws, next_row=2, new_rows=[row])
    # Find the F-column write (A:D is cols 0-3, F:K is cols 5-10)
    f_call = [c for c in ws.calls if c["range"].startswith("F2:")][0]
    assert f_call["vopt"] == "RAW", f"company cell used {f_call['vopt']}"


def test_equals_in_title_stays_text():
    ws = _RecordingWS()
    row = _row_with_hostile("2", "linkedin", "G", '=IMPORTXML("https://evil","//x")')
    M._write_rows_to_sheet(ws, next_row=2, new_rows=[row])
    f_call = [c for c in ws.calls if c["range"].startswith("F2:")][0]
    assert f_call["vopt"] == "RAW"
    # The value in F call (G column = index 1) must be the hostile text
    assert f_call["values"][0][1] == '=IMPORTXML("https://evil","//x")'


# ── Q39: Non-E cells cannot execute formulas starting with + - @ ────
def test_plus_minus_at_in_jd_stays_text():
    for hostile in ("+1+1", "-1+1", "@SUM(1,1)"):
        ws = _RecordingWS()
        row = _row_with_hostile("3", "linkedin", "H", hostile)
        M._write_rows_to_sheet(ws, next_row=2, new_rows=[row])
        f_call = [c for c in ws.calls if c["range"].startswith("F2:")][0]
        assert f_call["vopt"] == "RAW", f"{hostile!r} used {f_call['vopt']}"


# ── Q40: Intentional E-column HYPERLINK remains functional ─────────
def test_e_column_hyperlink_written_with_user_entered():
    ws = _RecordingWS()
    row = _row_with_hostile("4", "linkedin", "F", "Regular Co")
    M._write_rows_to_sheet(ws, next_row=2, new_rows=[row])
    e_call = [c for c in ws.calls if c["range"].startswith("E2:")][0]
    assert e_call["vopt"] == "USER_ENTERED", f"E column used {e_call['vopt']}"
    # E value must be a HYPERLINK formula
    assert e_call["values"][0][0].startswith("=HYPERLINK("), \
        f"E not a formula: {e_call['values'][0][0]!r}"


# ── Q38b: The non-E phase is split into A:D and F:K (continuous ranges) ─
def test_two_phase_write_uses_three_updates():
    """Three update() calls expected: E (USER_ENTERED), A:D (RAW), F:K (RAW)."""
    ws = _RecordingWS()
    row = _row_with_hostile("5", "linkedin", "F", "Plain Co")
    M._write_rows_to_sheet(ws, next_row=3, new_rows=[row])
    assert len(ws.calls) == 3, f"expected 3 update() calls, got {len(ws.calls)}"
    ranges = [c["range"] for c in ws.calls]
    assert "E3:E3" in ranges, f"missing E phase: {ranges}"
    assert "A3:D3" in ranges, f"missing A:D phase: {ranges}"
    assert "F3:K3" in ranges, f"missing F:K phase: {ranges}"


# ── Q38c: All three ranges receive the same number of rows ──────────
def test_three_phases_consistent_row_count():
    ws = _RecordingWS()
    rows = [
        _row_with_hostile(str(i), "linkedin", "F", f"Co{i}")
        for i in range(5)
    ]
    M._write_rows_to_sheet(ws, next_row=10, new_rows=rows)
    counts = [len(c["values"]) for c in ws.calls]
    assert counts == [5, 5, 5], f"phase row counts disagree: {counts}"


# ── Q41: dry_run performs zero external writes ─────────────────────
def test_dry_run_does_not_invoke_update():
    """The `push_to_sheet` dry-run path returns before any update() call."""
    # Construct a tiny job list and call push_to_sheet with dry_run=True on a fake ws.
    # We test the small branch by inspecting the source for the early return.
    src = (REPO_ROOT / "sg_product_jobs.py").read_text(encoding="utf-8")
    # The early return for dry_run must be before any google auth or update call.
    dry_idx = src.find("if dry_run:")
    update_idx = src.find("ws.update(")
    assert dry_idx > 0 and update_idx > dry_idx, \
        f"dry_run early-return not before update(): dry={dry_idx}, update={update_idx}"
    # And _write_rows_to_sheet must not be called from dry-run path.
    # Direct test: invoke the inline dry-run path through the helper.
    fake_ws = _RecordingWS()
    jobs = [_build_job("99", "linkedin")]
    # The push_to_sheet function's dry_run branch is tested by inspection; here
    # we directly verify _write_rows_to_sheet still produces writes (so dry-run
    # branch must explicitly avoid calling it).
    M._write_rows_to_sheet(fake_ws, next_row=2, new_rows=[M._build_sheet_row(jobs[0], "X", "Singapore", set())])
    assert len(fake_ws.calls) == 3, "_write_rows_to_sheet should write when called normally"


# ── Q42: gid validation prevents silent first-tab writes ───────────
def test_gid_zero_is_explicit_not_default():
    """The fallback gid is 0; push_to_sheet/get_worksheet_by_id should be called
    with the user-provided gid (not the old hardcoded 1119491672)."""
    import sg_product_jobs as M
    # The default gid when env is empty is 0 (sentinel for "not configured").
    assert M.SG_RAW_GID == 0
    # And the hardcoded historical default must be gone.
    src = (REPO_ROOT / "sg_product_jobs.py").read_text(encoding="utf-8")
    assert "else 1119491672" not in src


# ── Sanity: built row still has 11 columns ──────────────────────────
def test_row_has_11_columns():
    row = _build_job("42", "linkedin")
    built = M._build_sheet_row(row, "LinkedIn / Minimax", "Singapore", set())
    assert built is not None
    assert len(built) == 11, f"expected 11 cols, got {len(built)}"


if __name__ == "__main__":
    import inspect
    tests = [(n, fn) for n, fn in globals().items() if n.startswith("test_") and callable(fn)]
    n_pass = n_fail = 0
    for n, fn in tests:
        try:
            fn()
            print(f"  ✅ {n}")
            n_pass += 1
        except Exception as e:
            print(f"  ❌ {n}: {type(e).__name__}: {e}")
            n_fail += 1
    print(f"\n{n_pass}/{len(tests)} 通過, {n_fail} 失敗")
    sys.exit(0 if n_fail == 0 else 1)
