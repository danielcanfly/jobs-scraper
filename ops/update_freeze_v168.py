"""v1.6.8 freeze update: bump the freeze, restate the policy, re-pin the blobs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(os.environ.get("UPSTREAM_DIR", str(Path.home() / ".minimax-agent" / "projects" / "jobs-scraper-unified")))
FREEZE = ROOT / "tests" / "equivalence" / "HARNESS_FREEZE.json"

KEYWORD_POLICY = (
    " Every JobStreet keyword is crawled to the end of its own pool: the soft stop that ends a keyword "
    "measures the postings that are new to that keyword, never the postings that are new to the whole "
    "crawl, because the five keywords share one seen set and a signal measured against that set stops "
    "four of the five keywords on their first page. The shared set decides only what is returned, so a "
    "posting two keywords both match is still returned once, and the JobStreet page budget is sized for "
    "the largest keyword's pool. A keyword that exhausts its retries ends that keyword only: the failure "
    "stays visible while the other keywords' postings are not discarded with it."
)

OLD_ANCHOR = (
    "the JobStreet daterange parameter takes a number of days, mapped through JOBSTREET_TPR, never the CLI range name."
)


def blob(path: str) -> str:
    return subprocess.check_output(["git", "hash-object", "--", path], cwd=ROOT, text=True).strip()


def main() -> int:
    data = json.loads(FREEZE.read_text(encoding="utf-8"))
    data["freeze_version"] = 13
    data["baseline"] = {
        "release": "v1.6.8",
        "authorized_delta": "per-keyword-jobstreet-soft-stop-budgets-sized-to-the-largest-keyword-pool",
        "parent_main": "969c2cd",
    }
    policy = data["policy"].replace("The v1.6.7 contract is frozen", "The v1.6.8 contract is frozen")
    if OLD_ANCHOR not in policy:
        raise SystemExit("policy anchor not found")
    policy = policy.replace(OLD_ANCHOR, OLD_ANCHOR + KEYWORD_POLICY, 1)
    data["policy"] = policy

    blobs = dict(data["frozen_blobs"])
    blobs["tests/test_jobstreet_per_keyword_v168.py"] = "PLACEHOLDER"
    blobs = {path: blob(path) if value == "PLACEHOLDER" else value for path, value in blobs.items()}
    # the contract changed in this release, so its blob is re-pinned
    blobs["tests/equivalence/BEHAVIOUR_EQUIVALENCE_CONTRACT.md"] = blob(
        "tests/equivalence/BEHAVIOUR_EQUIVALENCE_CONTRACT.md"
    )
    data["frozen_blobs"] = dict(sorted(blobs.items()))

    FREEZE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"freeze_version={data['freeze_version']} baseline={data['baseline']['release']}")
    print(f"frozen_blobs={len(data['frozen_blobs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
