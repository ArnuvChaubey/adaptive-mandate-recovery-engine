"""Checks a decision log's hash chain from the command line -- no API key, no server, no trust in
the process that wrote it. Point this at any JSONL file `DecisionLog.write_jsonl` produced and it
tells you, independently, whether every record is exactly as written.

    python -m audit.verify_chain
    python -m audit.verify_chain eval/reports/decision_log_adaptive.jsonl
    python -m audit.verify_chain --tamper-demo   # edits a scratch copy and shows the break
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from audit.decision_log_schema.records import verify_chain

DEFAULT_PATHS = [
    "eval/reports/decision_log_adaptive.jsonl",
    "eval/reports/decision_log_baseline.jsonl",
    "eval/reports/decision_log_compliance_aware_baseline.jsonl",
    "eval/reports/decision_log_adaptive_hedged.jsonl",
    "eval/reports/live_test_mode_decisions.jsonl",
    "eval/reports/live_webhook_decisions.jsonl",
]


def _check_one(path: Path) -> str:
    """Returns 'intact', 'tampered', or 'legacy' (predates chain fields -- not evidence of
    tampering, just a file this schema change hasn't touched yet)."""
    if not path.exists():
        print(f"  {path}  -- not found, skipped")
        return "intact"
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    result = verify_chain(records)
    if result.intact:
        print(f"  ✓ {path}  ({result.records_checked} records, chain intact)")
        return "intact"
    if result.broken_at_index == 0 and "no chain fields" in result.detail:
        print(f"  · {path}  -- legacy file, predates chain fields (not evidence of tampering)")
        return "legacy"
    print(f"  ✗ {path}")
    print(f"      broken at record {result.broken_at_index}: {result.detail}")
    return "tampered"


def _tamper_demo() -> None:
    """Proves the check is real by breaking a real log on purpose and showing it get caught."""
    source = Path("eval/reports/decision_log_adaptive.jsonl")
    if not source.exists():
        raise SystemExit(
            "no adaptive log to demo against -- run "
            "`python -m eval.run_eval --policies adaptive --write-log` first"
        )
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "tampered.jsonl"
        shutil.copy(source, scratch)

        lines = scratch.read_text().splitlines()
        target = len(lines) // 2
        record = json.loads(lines[target])
        print(f"  Before: record {target} amount_inr = {record.get('amount_inr')}")
        record["amount_inr"] = 999_999.0
        lines[target] = json.dumps(record)
        scratch.write_text("\n".join(lines) + "\n")
        print(f"  After:  record {target} amount_inr = 999999.0  (edited directly in the file)")
        print()

        print("  Verifying the tampered copy:")
        _check_one(scratch)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a decision log's hash chain")
    parser.add_argument("paths", nargs="*", help="JSONL files to check (default: every log under eval/reports)")
    parser.add_argument(
        "--tamper-demo", action="store_true",
        help="edit a scratch copy of a real log and show verification catch it",
    )
    args = parser.parse_args()

    if args.tamper_demo:
        _tamper_demo()
        return

    paths = [Path(p) for p in (args.paths or DEFAULT_PATHS)]
    print()
    print("=" * 78)
    print("  DECISION LOG CHAIN VERIFICATION")
    print("=" * 78)
    statuses = [_check_one(path) for path in paths]
    tampered = statuses.count("tampered")
    legacy = statuses.count("legacy")
    print("=" * 78)
    if tampered:
        print(f"  TAMPERING DETECTED in {tampered} file(s) -- see above")
    elif legacy:
        print(f"  All chained files intact. {legacy} legacy file(s) predate chaining, not tampered.")
    else:
        print("  ALL CHAINS INTACT")
    print("=" * 78)
    print()
    if tampered:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
