"""Guards against a real bug found the night before recording the demo video.

`live_batch.py` constructs a fresh `DecisionLog()` on every invocation -- it's a script, not a
long-running process. Every earlier version of `write_jsonl` opened its target file in "w" mode
unconditionally, so running the script a second time (exactly what the video does: once for a
compliant retry, once for the above-ceiling escalation) silently destroyed the first run's real
audit records. A project whose entire pitch rests on the audit trail being trustworthy was, until
this fix, guaranteed to lose history every time its own live-integration script ran twice.

These tests prove multi-invocation continuity directly: two separate `DecisionLog` instances,
constructed and written the way two separate `live_batch.py` process runs actually would be, must
combine into one file that (a) contains every record from both runs and (b) verifies as one intact
chain end to end.
"""

import json
from datetime import datetime

from audit.decision_log_schema.records import (
    GENESIS_HASH,
    DecisionLog,
    DecisionRecord,
    DecisionType,
    Source,
    load_chain_tip,
    verify_chain,
)


def _record(i: int) -> DecisionRecord:
    return DecisionRecord(
        decision_id=f"d{i}",
        mandate_id=f"m{i}",
        policy_name="adaptive",
        decision_type=DecisionType.RETRY_SCHEDULED,
        rule_id="ADAPT-004",
        rule_description="test",
        failure_class="insufficient_funds",
        attempt_number=1,
        decided_at=datetime(2026, 8, 29, 12, 0),
        source=Source.LIVE_TEST_MODE,
        amount_inr=1000.0 + i,
    )


def _read(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_load_chain_tip_on_missing_file_is_genesis(tmp_path):
    assert load_chain_tip(tmp_path / "does_not_exist.jsonl") == GENESIS_HASH


def test_load_chain_tip_on_empty_file_is_genesis(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("")
    assert load_chain_tip(path) == GENESIS_HASH


def test_load_chain_tip_matches_the_last_records_hash(tmp_path):
    log = DecisionLog()
    for i in range(3):
        log.append(_record(i))
    path = tmp_path / "log.jsonl"
    log.write_jsonl(path)

    tip = load_chain_tip(path)
    assert tip == _read(path)[-1]["record_hash"]


def test_default_write_still_overwrites_for_callers_that_want_a_fresh_batch(tmp_path):
    """run_eval.py's use case must be unaffected -- a fresh evaluation run replacing a stale prior
    file is correct there, not a regression."""
    path = tmp_path / "log.jsonl"

    first = DecisionLog()
    first.append(_record(0))
    first.write_jsonl(path)
    assert len(_read(path)) == 1

    second = DecisionLog()
    second.append(_record(1))
    second.write_jsonl(path)  # append defaults to False
    assert len(_read(path)) == 1, "second run should have replaced the first, not added to it"


def test_two_separate_process_runs_form_one_continuous_verified_chain(tmp_path):
    """The actual bug, reproduced exactly the way live_batch.py triggers it: two independent
    DecisionLog instances, as two separate process invocations would create, writing to the same
    path with the real fix's exact call pattern."""
    path = tmp_path / "live_test_mode_decisions.jsonl"

    # "First invocation" -- fires two retries.
    run_one = DecisionLog(seed_hash=load_chain_tip(path))
    for i in range(2):
        run_one.append(_record(i))
    run_one.write_jsonl(path, append=True)

    # "Second invocation" -- a fresh process, fresh DecisionLog, but seeded from what's on disk.
    run_two = DecisionLog(seed_hash=load_chain_tip(path))
    for i in range(2, 3):
        run_two.append(_record(i))
    run_two.write_jsonl(path, append=True)

    records = _read(path)
    assert len(records) == 3, "both runs' records must be present -- the second must not erase the first"

    result = verify_chain(records)
    assert result.intact, f"combined file must verify as one continuous chain: {result.detail}"
    assert result.records_checked == 3


def test_without_the_fix_a_naive_second_run_would_have_destroyed_the_first():
    """Documents the regression this guards, explicitly: constructing a DecisionLog with no seed
    and writing with append=False (the old default/only behaviour) on a second run is exactly what
    used to happen, and is exactly what these tests now prove doesn't happen by default in
    live_batch.py's actual call pattern."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "log.jsonl"

        run_one = DecisionLog()
        run_one.append(_record(0))
        run_one.write_jsonl(path)  # old-style: no seed, no append
        assert len(_read(path)) == 1

        run_two = DecisionLog()  # the bug: fresh log, no seed_hash
        run_two.append(_record(1))
        run_two.write_jsonl(path)  # the bug: append=False (the old only mode)

        assert len(_read(path)) == 1, "this reproduces the destructive old behaviour on purpose"
