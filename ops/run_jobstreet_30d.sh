#!/bin/bash
# Detached JobStreet 30d SG run — detached via os.setsid() so the runtime
# background-task watchdog (~60 min) cannot kill it mid-JD-fetch.
cd "${JOBS_SCRAPER_DIR:-${HOME}/.minimax/plugins/jobs-scraper}" || exit 1

URL=$(.venv/bin/python -c "import sg_product_jobs as M; print(M.SG_RAW_URL)")

echo "=== START $(date '+%F %T') ==="
echo "TARGET: $URL"
echo "SEEN: $(wc -l < seen_jds.jsonl) 筆 (before)"
echo "--- JobStreet 30d ---"

.venv/bin/python -u sg_product_jobs.py 30d --source jobstreet --with-jd --to-sheet "$URL"
echo "JOBSTREET_EXIT=$?"
echo "SEEN: $(wc -l < seen_jds.jsonl) 筆 (after)"
echo "=== END $(date '+%F %T') ==="
