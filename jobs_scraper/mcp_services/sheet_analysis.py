"""Pure row analysis shared by legacy and region-aware MCP tools."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import sg_product_jobs as M


def audit_rows(rows: list[list[str]], *, seen_path: Path | None = None) -> dict[str, Any]:
    keys: list[tuple[str, str]] = []
    for row in rows:
        key = M.parse_sheet_row_to_key(row)
        if key:
            keys.append(key)

    key_counts = Counter(keys)
    dup_keys = sum(1 for count in key_counts.values() if count > 1)
    url_counts = Counter(row[4].strip() for row in rows if len(row) > 4 and row[4].strip())
    dup_urls = sum(1 for count in url_counts.values() if count > 1)
    li_ids = {job_id for source, job_id in keys if source == "linkedin" and job_id.isdigit()}
    js_ids = {job_id for source, job_id in keys if source == "jobstreet" and job_id.isdigit()}

    key_to_meta: dict[tuple[str, str], set[tuple[str, str]]] = {}
    for row in rows:
        key = M.parse_sheet_row_to_key(row)
        if key:
            key_to_meta.setdefault(key, set()).add(
                (row[5][:30] if len(row) > 5 else "", row[6][:50] if len(row) > 6 else "")
            )

    sheet_seen_drift = 0
    if seen_path is not None and seen_path.exists():
        seen = M.load_seen_ids(seen_path)
        sheet_seen_drift = len(set(keys) - seen)

    work_mode = Counter(row[9] for row in rows if len(row) > 9)
    source = Counter(row[3] for row in rows if len(row) > 3)
    visa_hard = sum(1 for row in rows if len(row) > 10 and row[10].startswith("⚠️ HARD"))
    visa_soft_or_positive = sum(
        1 for row in rows if len(row) > 10 and row[10] and not row[10].startswith("⚠️ HARD")
    )

    return {
        "rows_read": len(rows),
        "dup_keys": dup_keys,
        "dup_urls": dup_urls,
        "cross_source_id_collisions": len(li_ids & js_ids),
        "title_company_mismatches": sum(1 for values in key_to_meta.values() if len(values) > 1),
        "sheet_seen_drift": sheet_seen_drift,
        "work_mode_distribution": {key or "(empty)": count for key, count in work_mode.most_common()},
        "visa_hard": visa_hard,
        "visa_soft_or_positive": visa_soft_or_positive,
        "source_distribution": dict(source.most_common()),
    }


def stats_rows(rows: list[list[str]], *, seen_path: Path | None = None) -> dict[str, Any]:
    source = Counter(row[3] for row in rows if len(row) > 3)
    work_mode = Counter(row[9] for row in rows if len(row) > 9)
    dates = Counter(row[2] for row in rows if len(row) > 2 and row[2])

    seen_unique: int | None = None
    seen_by_source: dict[str, int] | None = None
    if seen_path is not None and seen_path.exists():
        seen = M.load_seen_ids(seen_path)
        seen_unique = len(seen)
        seen_by_source = dict(Counter(source for source, _ in seen).most_common())

    return {
        "total_rows": len(rows),
        "source_distribution": dict(source.most_common()),
        "work_mode_distribution": {key or "(empty)": count for key, count in work_mode.most_common()},
        "date_distribution_top10": {key: count for key, count in dates.most_common(10)},
        "seen_unique_count": seen_unique,
        "seen_by_source": seen_by_source,
    }
