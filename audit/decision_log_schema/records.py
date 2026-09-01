"""The audit trail.

Every retry / stop / escalate decision any policy makes writes exactly one record here, tagged with
the rule that produced it. Two properties matter and are non-negotiable:

1. **Independent of the LLM.** The narrator (Milestone 5) reads these records to produce human
   explanations; it never writes to them and never influences a decision. Delete narrator/ entirely
   and the audit trail is unchanged and still complete. This boundary is the evidence for Track 03's
   "AI judgment -- the right tool in the right place, and where you chose not to use one".
2. **Same schema for simulated and live events.** `source` distinguishes them so a reader can never
   mistake a simulated batch statistic for a real-money one, but the structure is identical, so the
   same queries work over both.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class DecisionType(str, Enum):
    RETRY_SCHEDULED = "retry_scheduled"
    STOPPED_ATTEMPTS_EXHAUSTED = "stopped_attempts_exhausted"
    STOPPED_UNRECOVERABLE = "stopped_unrecoverable"
    ESCALATED = "escalated"
    # A retry the policy proposed but compliance refused to execute. Recorded rather than hidden:
    # a policy that repeatedly proposes non-compliant actions is a policy with a real defect, and
    # that defect should be visible in the audit trail and measurable in the metrics.
    BLOCKED_BY_COMPLIANCE = "blocked_by_compliance"


class EscalationAction(str, Enum):
    """What a policy does instead of retrying. The rubric asks for *compliant escalation*, which
    means the stop decision must name a next action, not merely give up."""
    REQUEST_REMANDATE = "request_remandate"          # expired mandate: authorization must be renewed
    NOTIFY_CUSTOMER_MANUAL_PAYMENT = "notify_customer_manual_payment"
    NO_ACTION_POSSIBLE = "no_action_possible"        # revoked: customer withdrew consent
    # Above the no-OTP ceiling (A6) a recurring debit legally requires additional factor
    # authentication, so it cannot be auto-retried at all -- the compliant move is to ask the
    # customer to re-authenticate rather than to fire an attempt that must be refused.
    REQUEST_ADDITIONAL_AUTHENTICATION = "request_additional_authentication"


class Source(str, Enum):
    SIMULATION = "simulation"
    LIVE_TEST_MODE = "live_test_mode"


@dataclass(frozen=True)
class ComplianceCheck:
    """One invariant evaluated against a proposed decision.

    Recording checks that *passed* matters as much as ones that blocked something: it's the
    difference between "we never violated the rule" and "we never tested the rule."

    `applicable` distinguishes a rule that was tested and satisfied from one that didn't apply to
    this decision at all. Both are non-blocking, but conflating them makes the audit trail read
    misleadingly -- an escalation triggered *because* an amount exceeds the OTP ceiling should not
    also report "OTP ceiling: satisfied".
    """
    invariant_id: str
    description: str
    passed: bool
    detail: str = ""
    applicable: bool = True


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    mandate_id: str
    policy_name: str
    decision_type: DecisionType
    rule_id: str                      # which rule in the policy fired -- the auditable link
    rule_description: str
    failure_class: str
    attempt_number: int
    decided_at: datetime
    source: Source
    scheduled_retry_at: datetime | None = None
    escalation_action: EscalationAction | None = None
    compliance_checks: list[ComplianceCheck] = field(default_factory=list)
    amount_inr: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decided_at"] = self.decided_at.isoformat()
        d["scheduled_retry_at"] = (
            self.scheduled_retry_at.isoformat() if self.scheduled_retry_at else None
        )
        return d


GENESIS_HASH = "0" * 64  # the "previous hash" a chain's first record chains to; not a real digest


def _canonical(d: dict[str, Any]) -> str:
    """Deterministic serialization so the same record always hashes to the same digest regardless
    of dict insertion order -- `sort_keys=True` is what makes that a guarantee, not a convention."""
    return json.dumps(d, sort_keys=True, default=str)


def _record_digest(prev_hash: str, record_dict: dict[str, Any]) -> str:
    """The hash for one record: a function of its own content AND the previous record's hash.

    That second part is what makes this a *chain* rather than a list of individually-checksummed
    records. Editing record 5 changes record 5's digest, which no longer matches what record 6
    recorded as its `prev_hash` -- the break is visible at record 6, not silently absorbed. An
    attacker would have to rewrite every record from the edit point to the end to hide the change.
    """
    return hashlib.sha256((prev_hash + "|" + _canonical(record_dict)).encode()).hexdigest()


@dataclass(frozen=True)
class ChainVerification:
    """The result of checking a decision log's hash chain end to end."""
    intact: bool
    records_checked: int
    broken_at_index: int | None = None
    detail: str = ""


def load_chain_tip(path: Path | str) -> str:
    """The hash a new DecisionLog must be seeded with to continue an existing file's chain.

    Returns GENESIS_HASH if the file doesn't exist or is empty -- correct in both cases, since a
    log with nothing to continue from should start its own chain from genesis, same as the first
    run ever would. Reads only the last line, not the whole file, so this stays cheap regardless of
    how long a live audit trail has grown.
    """
    path = Path(path)
    if not path.exists():
        return GENESIS_HASH
    last_line = None
    for line in path.read_text().splitlines():
        if line.strip():
            last_line = line
    if last_line is None:
        return GENESIS_HASH
    record = json.loads(last_line)
    return record.get("record_hash", GENESIS_HASH)


def verify_chain(chained_records: list[dict[str, Any]]) -> ChainVerification:
    """Recomputes every record's digest from its content and checks it against what was stored,
    then checks that each record's `prev_hash` matches the actual previous record's digest.

    Two distinct failure modes, both caught: a record edited after being written (its own recomputed
    digest no longer matches its stored `record_hash`), and a record spliced in or deleted (its
    `prev_hash` no longer matches the real predecessor's `record_hash`, even if the spliced record is
    internally self-consistent). Takes plain dicts, not `DecisionRecord`, so it can verify a JSONL
    file read back from disk in a completely separate process -- which is the actual threat model:
    proving the file on disk wasn't altered after `write_jsonl` wrote it, not just that this run's
    in-memory objects agree with themselves.
    """
    if not chained_records:
        return ChainVerification(intact=True, records_checked=0, detail="empty log")

    expected_prev = GENESIS_HASH
    for i, stored in enumerate(chained_records):
        record_hash = stored.get("record_hash")
        prev_hash = stored.get("prev_hash")
        if record_hash is None or prev_hash is None:
            return ChainVerification(
                intact=False, records_checked=i, broken_at_index=i,
                detail=f"record {i} carries no chain fields -- not written by a chaining DecisionLog",
            )
        if prev_hash != expected_prev:
            return ChainVerification(
                intact=False, records_checked=i, broken_at_index=i,
                detail=f"record {i}'s prev_hash does not match record {i - 1}'s record_hash -- "
                       f"a record was edited, inserted, deleted, or reordered",
            )
        content = {k: v for k, v in stored.items() if k not in ("prev_hash", "record_hash")}
        recomputed = _record_digest(prev_hash, content)
        if recomputed != record_hash:
            return ChainVerification(
                intact=False, records_checked=i, broken_at_index=i,
                detail=f"record {i}'s content does not match its own recorded hash -- it was "
                       f"edited after being written",
            )
        expected_prev = record_hash

    return ChainVerification(intact=True, records_checked=len(chained_records))


class DecisionLog:
    """Append-only decision log. Queryable after the fact, serializable to JSONL.

    Hash-chained: each appended record's digest depends on the previous record's digest, so the
    written file is tamper-evident, not merely append-only by convention. `write_jsonl` persists the
    chain fields; `verify_chain` (module-level, operates on the dicts read back from disk) is what a
    reader actually checks, independent of whether they trust the process that wrote the file.
    """

    def __init__(self, seed_hash: str = GENESIS_HASH) -> None:
        # seed_hash lets a NEW process continue an EXISTING file's chain instead of starting a
        # second, disconnected genesis in the middle of it. Found the need for this the night
        # before recording the demo video: live_batch.py constructs a fresh DecisionLog() on every
        # invocation, and every invocation used to overwrite the file from scratch -- so running it
        # twice in a row (once for a retry case, once for an escalation case, exactly what the video
        # does) silently destroyed the first run's real audit history. See docs/build_log.md entry 31.
        self._seed_hash = seed_hash
        self._records: list[DecisionRecord] = []
        self._hashes: list[str] = []

    def append(self, record: DecisionRecord) -> None:
        prev = self._hashes[-1] if self._hashes else self._seed_hash
        self._hashes.append(_record_digest(prev, record.to_json_dict()))
        self._records.append(record)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self):
        return iter(self._records)

    @property
    def records(self) -> list[DecisionRecord]:
        return list(self._records)

    def for_mandate(self, mandate_id: str) -> list[DecisionRecord]:
        return [r for r in self._records if r.mandate_id == mandate_id]

    def by_decision_type(self, decision_type: DecisionType) -> list[DecisionRecord]:
        return [r for r in self._records if r.decision_type == decision_type]

    def compliance_failures(self) -> list[DecisionRecord]:
        """Any record where an invariant did not pass. Should always be empty -- a policy is not
        permitted to emit a decision that violates a compliance floor."""
        return [r for r in self._records if any(not c.passed for c in r.compliance_checks)]

    def write_jsonl(self, path: Path | str, append: bool = False) -> None:
        """Writes this log's records to `path`.

        `append=False` (default) overwrites the file -- correct for a caller like `eval/run_eval.py`
        producing one complete, self-consistent batch per invocation, where a stale prior file must
        not linger. `append=True` opens in "a" mode instead, so a caller like `live_batch.py` --
        invoked fresh each time, but representing an ongoing real-world audit trail -- adds to the
        file rather than replacing it. Pair `append=True` with `seed_hash=load_chain_tip(path)` at
        construction time, or the newly-appended records will chain from GENESIS_HASH instead of
        from the file's real prior tail, and `verify_chain` will correctly report that break as
        broken, because it *is* broken -- just not from tampering.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        prev = self._seed_hash
        with open(path, "a" if append else "w") as f:
            for record, record_hash in zip(self._records, self._hashes):
                chained = {**record.to_json_dict(), "prev_hash": prev, "record_hash": record_hash}
                f.write(json.dumps(chained) + "\n")
                prev = record_hash
