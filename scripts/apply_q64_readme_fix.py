#!/usr/bin/env python3
"""One-shot exact-anchor repair for fresh qualification Q64.

Scope is README.md only. Refuses to proceed on candidate drift.
"""
from pathlib import Path

p = Path("README.md")
s = p.read_text(encoding="utf-8")

replacements = [
    (
        '''# Edit .env (fill in your own values; empty values fail-closed on Sheet tools):\n#   GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json\n#   SHEET_ID=<paste your sheet ID>\n#   SHEET_GID=<paste your GID, usually 0 for first tab>\n```''',
        '''# Edit .env (fill in your own values; empty values fail-closed on Sheet tools):\n#   GSPREAD_SA_KEY_PATH=.secrets/gsheet-sa.json\n#   SHEET_ID=<paste your sheet ID>\n#   SHEET_GID=<paste your GID, usually 0 for first tab>\n\n# Load those same .env values into this shell for the CLI examples below.\nset -a\n. ./.env\nset +a\n```''',
    ),
    (
        '''.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd --to-sheet "$SHEET_URL"''',
        '''.venv/bin/python sg_product_jobs.py 7d --source linkedin --with-jd --to-sheet "$SHEET_ID" --gid "$SHEET_GID"''',
    ),
    (
        '''.venv/bin/python sg_product_jobs.py 14d --source linkedin --with-jd --to-sheet "$URL"''',
        '''.venv/bin/python sg_product_jobs.py 14d --source linkedin --with-jd --to-sheet "$SHEET_ID" --gid "$SHEET_GID"''',
    ),
    (
        '''.venv/bin/python sg_product_jobs.py 30d --source jobstreet --with-jd --to-sheet "$URL"''',
        '''.venv/bin/python sg_product_jobs.py 30d --source jobstreet --with-jd --to-sheet "$SHEET_ID" --gid "$SHEET_GID"''',
    ),
    (
        '''.venv/bin/python sg_product_jobs.py 7d --source linkedin --refetch --to-sheet "$URL"''',
        '''.venv/bin/python sg_product_jobs.py 7d --source linkedin --refetch --to-sheet "$SHEET_ID" --gid "$SHEET_GID"''',
    ),
    (
        '''  - 11-column Google Sheet write, two-phase (E=HYPERLINK USER_ENTERED, rest=RAW)''',
        '''  - 11-column Google Sheet write, three-phase (A:D/F:K RAW first; E=HYPERLINK USER_ENTERED last)''',
    ),
    (
        '''Should print `47 passed` (27 original helper tests + 20 contract tests for\nthe MCP v2 server, fail-closed config, two-phase sheet write, and the setup\ncontract). Tests are deterministic, do not require Google credentials, and\ndo not touch a production Sheet.''',
        '''Should complete with all tests passing. The frozen v1.0.0 qualification candidate\ncurrently has **83 pytest cases**; CI also runs the original **27/27 helper\nregressions explicitly**. Tests are deterministic, do not require Google\ncredentials, and do not touch a production Sheet.''',
    ),
]

for old, new in replacements:
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"Q64 repair refused: expected exactly one anchor, found {count}: {old[:80]!r}")
    s = s.replace(old, new, 1)

p.write_text(s, encoding="utf-8")
print("Q64 README repair applied: 7 exact anchors")
