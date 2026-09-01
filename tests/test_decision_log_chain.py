"""Guards the audit trail's tamper-evidence, not just its presence.

A `DecisionRecord` was always individually correct, but nothing stopped one from being edited after
the fact -- an append-only log is append-only by convention, not by proof. Every record now chains to
the one before it via a SHA-256 digest, so the file on disk is checkable independently of whether the
reader trusts the process that wrote it. These tests exist to prove the chain actually discriminates:
clean logs verify, and every distinct way of tampering with a written log is caught, with the break
reported at the point of tampering rather than surfacing as a vague "something's wrong somewhere."
"""

import json
from datetime import datetime
from pathlib import Path

from audit.decision_log_schema.records import (
    DecisionLog,
    DecisionRecord,
    DecisionType,
    Source,
    verify_chain,
)


def _record(i: int, **overrides) -> DecisionRecord:
    defaults = dict(
        decision_id=f"d{i}",
        mandate_id=f"m{i}",
        policy_name="adaptive",
        decision_type=DecisionType.RETRY_SCHEDULED,
        rule_id="ADAPT-004",
        rule_description="test",
        failure_class="insufficient_funds",
        attempt_number=1,
        decided_at=datetime(2026, 8, 29, 12, 0),
        source=Source.SIMULATION,
        amount_inr=1000.0,
    )
    defaults.update(overrides)
    return DecisionRecord(**defaults)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_clean_log_verifies_intact(tmp_path):
    log = DecisionLog()
    for i in range(5):
        log.append(_record(i))
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)

    result = verify_chain(_read_jsonl(out))
    assert result.intact
    assert result.records_checked == 5
    assert result.broken_at_index is None


def test_empty_log_is_vacuously_intact(tmp_path):
    log = DecisionLog()
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)
    result = verify_chain(_read_jsonl(out))
    assert result.intact
    assert result.records_checked == 0


def test_first_record_chains_to_genesis(tmp_path):
    log = DecisionLog()
    log.append(_record(0))
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)
    records = _read_jsonl(out)
    assert records[0]["prev_hash"] == "0" * 64


def test_editing_a_record_after_the_fact_is_caught(tmp_path):
    """The core threat model: someone opens the JSONL and changes a value post-hoc."""
    log = DecisionLog()
    for i in range(4):
        log.append(_record(i))
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)

    records = _read_jsonl(out)
    records[2]["amount_inr"] = 999_999.0  # tamper with the middle record's content

    result = verify_chain(records)
    assert not result.intact
    assert result.broken_at_index == 2


def test_deleting_a_record_breaks_the_chain_at_the_splice_point(tmp_path):
    log = DecisionLog()
    for i in range(5):
        log.append(_record(i))
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)

    records = _read_jsonl(out)
    del records[2]  # remove one record; every subsequent prev_hash now points at a gap

    result = verify_chain(records)
    assert not result.intact
    assert result.broken_at_index == 2


def test_reordering_records_breaks_the_chain(tmp_path):
    log = DecisionLog()
    for i in range(4):
        log.append(_record(i))
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)

    records = _read_jsonl(out)
    records[1], records[2] = records[2], records[1]

    result = verify_chain(records)
    assert not result.intact
    assert result.broken_at_index == 1


def test_inserting_a_fabricated_record_is_caught(tmp_path):
    """Not just detecting edits to real records -- a wholly invented record inserted into the
    stream, even one that is internally self-consistent on its own terms, must still break the
    chain, because it cannot possibly carry the real predecessor's hash."""
    log = DecisionLog()
    for i in range(3):
        log.append(_record(i))
    out = tmp_path / "log.jsonl"
    log.write_jsonl(out)
    records = _read_jsonl(out)

    fake = _record(99).to_json_dict()
    fake["prev_hash"] = "f" * 64  # attacker doesn't know the real chain value
    fake["record_hash"] = "e" * 64
    records.insert(2, fake)

    result = verify_chain(records)
    assert not result.intact
    assert result.broken_at_index == 2


def test_a_record_missing_chain_fields_entirely_is_flagged_not_silently_skipped(tmp_path):
    """Guards against a regression where some write path forgets to attach chain fields at all --
    that must be reported as broken, not treated as vacuously fine."""
    plain = _record(0).to_json_dict()  # no prev_hash / record_hash, as if written by old code
    result = verify_chain([plain])
    assert not result.intact
    assert result.broken_at_index == 0


def test_chain_depends_on_write_order_not_object_identity(tmp_path):
    """Two logs with identical record content but different orders must NOT produce the same
    chain -- otherwise the hash wouldn't actually be securing sequence, only content."""
    log_a, log_b = DecisionLog(), DecisionLog()
    r0, r1 = _record(0), _record(1)
    log_a.append(r0); log_a.append(r1)
    log_b.append(r1); log_b.append(r0)

    out_a, out_b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    log_a.write_jsonl(out_a)
    log_b.write_jsonl(out_b)

    hashes_a = [r["record_hash"] for r in _read_jsonl(out_a)]
    hashes_b = [r["record_hash"] for r in _read_jsonl(out_b)]
    assert hashes_a != hashes_b
