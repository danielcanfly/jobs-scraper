"""v1.7.0: 寫入起點不能蓋掉有資料的 row。

2026-11-24 實測事故: sg 14d 那輪, Sheet 中間有一列空白 (前一次 run 被殺造成的
hole)。寫入起點取「第一個空白 row」→ 那一輪要寫 159 列 → 下面 158 列**有資料**
的 row 被寫爆蓋掉; 連帶把另外兩塊的 127 列也蓋了, 合計 415 列舊資料消失。
被蓋掉的 job 因為不在 sheet 裡 → 下次 pre-dedup 不會擋 → 又要重抓一次 JD。

修法: 寫入起點要在知道要寫幾列之後才算 — 只有當那個 gap 連續 n_rows 列都是
空白時才用 gap, 否則 append 到最後。純 append 語意 → 永遠不蓋掉有資料的 row。

所有測試都是離線的: 不碰網路、不碰 Sheet。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import sg_product_jobs as M  # noqa: E402


def _rows(*specs: list[str]) -> list[list[str]]:
    return [list(s) for s in specs]


def test_a_single_gap_is_still_filled_when_the_write_fits():
    """既有行為保留: 只有 1 列要寫、那個 gap 也塞得下 → 填那個 gap。"""
    existing = _rows(
        ["header"],
        ["a"],
        [],
        ["c"],
    )
    _, next_row = M._load_sheet_keys(existing, n_rows=1)
    assert next_row == 3


def test_a_gap_that_cannot_hold_the_write_falls_back_to_append():
    """gap 只有 1 列、但要寫 3 列 → 不能用那個 gap (會蓋掉下面的資料) → append。"""
    existing = _rows(
        ["header"],
        ["a"],
        [],
        ["c"],
        ["d"],
    )
    _, next_row = M._load_sheet_keys(existing, n_rows=3)
    assert next_row == 6  # len(existing) + 1


def test_a_gap_at_the_tail_can_be_used():
    """gap 在最後一列、而且塞得下 → 用那個 gap。"""
    existing = _rows(
        ["header"],
        ["a"],
        ["b"],
        [],
    )
    _, next_row = M._load_sheet_keys(existing, n_rows=1)
    assert next_row == 4


def test_a_run_of_blank_rows_can_absorb_the_write():
    """連續 3 列空白 + 要寫 3 列 → 剛好塞滿那個 gap。"""
    existing = _rows(
        ["header"],
        ["a"],
        [],
        [],
        [],
        ["f"],
    )
    _, next_row = M._load_sheet_keys(existing, n_rows=3)
    assert next_row == 3


def test_a_run_of_blank_rows_that_is_too_short_is_skipped():
    """連續 2 列空白、但要寫 3 列 → 塞不下 → append (不能蓋掉 row 6)。"""
    existing = _rows(
        ["header"],
        ["a"],
        [],
        [],
        ["e"],
    )
    _, next_row = M._load_sheet_keys(existing, n_rows=3)
    assert next_row == 6


def test_blank_run_helper():
    assert M._blank_run([["a"], ["b"]], 3, 2) is True  # 超出長度 = 空白
    assert M._blank_run([["a"], [], ["c"]], 2, 1) is True
    assert M._blank_run([["a"], [], ["c"]], 2, 2) is False


def test_keys_are_still_collected_from_a_sheet_with_a_gap():
    existing = _rows(
        ["header"],
        ["New", "", "2026-01-01", "LinkedIn / Minimax", "111", "OKX", "VP", "JD", "SG", "Onsite", ""],
        [],
        ["New", "", "2026-01-02", "JobStreet / Minimax", "222", "Acme", "PM", "JD", "SG", "Onsite", ""],
    )
    keys, next_row = M._load_sheet_keys(existing, n_rows=1)
    assert keys == {("linkedin", "111"), ("jobstreet", "222")}
    assert next_row == 3


def test_default_behaviour_is_unchanged_for_a_single_row_write():
    """不傳 n_rows → 跟舊版一樣 (填第一個 gap)。"""
    existing = _rows(["header"], ["a"], [], ["c"])
    _, next_row = M._load_sheet_keys(existing)
    assert next_row == 3
