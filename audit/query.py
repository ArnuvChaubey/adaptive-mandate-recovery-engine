"""Natural-language interrogation of the decision log.

An audit trail's value is proportional to how easily someone can interrogate it. A compliance officer
asking "show me every debit we blocked above the OTP ceiling last month" should not have to write
a JSONL filter.

**The model translates; the code answers.** A question becomes a structured `QuerySpec` -- a
restricted set of named fields with validated values -- and that spec is executed deterministically
over the records. The language model never sees the data, never counts anything, and never phrases
a result. It cannot hallucinate a number because it is never asked for one.

That boundary is the same one used everywhere else in this project, for the same reason: a model is
good at understanding what someone meant, and untrustworthy as a source of fact about money.

    python -m audit.query "which decisions were blocked by compliance?"
    python -m audit.query --list-fields
"""

import argparse
import json
import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from audit.decision_log_schema.records import DecisionType, EscalationAction, Source

MODEL = "claude-opus-5"

VALID_DECISION_TYPES = {d.value for d in DecisionType}
VALID_ESCALATIONS = {e.value for e in EscalationAction}
VALID_SOURCES = {s.value for s in Source}

SYSTEM_PROMPT = f"""You translate questions about a payment-recovery audit log into a structured \
query. You do not answer the question and you never invent data -- a deterministic engine executes \
your query against the real records.

Return ONLY a JSON object using these fields. Omit any field that does not apply.

  decision_type       one of: {sorted(VALID_DECISION_TYPES)}
  escalation_action   one of: {sorted(VALID_ESCALATIONS)}
  source              one of: {sorted(VALID_SOURCES)}
  failure_class       e.g. insufficient_funds, npci_congestion, bank_technical_decline,
                      notification_undelivered, mandate_expired, mandate_revoked
  rule_id             e.g. ADAPT-002, BASE-001
  policy_name         e.g. adaptive, baseline
  min_amount_inr      number
  max_amount_inr      number
  compliance_failed   true to return only decisions where an invariant did NOT pass
  attempt_number      integer
  limit               integer, default 20

Guidance:
- "blocked" / "refused" / "rejected by compliance" -> decision_type "blocked_by_compliance"
- "escalated" / "asked the customer" -> decision_type "escalated"
- "gave up" / "stopped trying" -> decision_type "stopped_attempts_exhausted"
- "above the ceiling" / "over the OTP limit" -> min_amount_inr 15000
- "real" / "live" / "production" -> source "live_test_mode"
- "simulated" -> source "simulation"

Return the JSON object and nothing else."""


@dataclass
class QuerySpec:
    decision_type: str | None = None
    escalation_action: str | None = None
    source: str | None = None
    failure_class: str | None = None
    rule_id: str | None = None
    policy_name: str | None = None
    min_amount_inr: float | None = None
    max_amount_inr: float | None = None
    compliance_failed: bool | None = None
    attempt_number: int | None = None
    limit: int = 20
    rejected_reason: str | None = None

    @property
    def valid(self) -> bool:
        return self.rejected_reason is None

    def describe(self) -> str:
        parts = [
            f"{f.name}={getattr(self, f.name)}"
            for f in fields(self)
            if f.name not in {"limit", "rejected_reason"} and getattr(self, f.name) is not None
        ]
        return " AND ".join(parts) if parts else "all records"


def validate_spec(raw: dict[str, Any]) -> QuerySpec:
    """Builds a spec from model output, rejecting anything unrecognised.

    Unknown keys are refused rather than ignored: a silently-dropped filter would return a *wider*
    result set than the question asked for, which in a compliance context means quietly answering a
    different question than the one posed.
    """
    known = {f.name for f in fields(QuerySpec)} - {"rejected_reason"}
    unknown = set(raw) - known
    if unknown:
        return QuerySpec(rejected_reason=f"unknown query field(s): {sorted(unknown)}")

    spec = QuerySpec(**{k: v for k, v in raw.items() if k in known})

    for value, allowed, label in (
        (spec.decision_type, VALID_DECISION_TYPES, "decision_type"),
        (spec.escalation_action, VALID_ESCALATIONS, "escalation_action"),
        (spec.source, VALID_SOURCES, "source"),
    ):
        if value is not None and value not in allowed:
            return QuerySpec(rejected_reason=f"invalid {label}: {value!r}")

    return spec


def execute(spec: QuerySpec, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic execution. No model involvement, no interpretation."""
    def matches(r: dict[str, Any]) -> bool:
        if spec.decision_type and r.get("decision_type") != spec.decision_type:
            return False
        if spec.escalation_action and r.get("escalation_action") != spec.escalation_action:
            return False
        if spec.source and r.get("source") != spec.source:
            return False
        if spec.failure_class and r.get("failure_class") != spec.failure_class:
            return False
        if spec.rule_id and r.get("rule_id") != spec.rule_id:
            return False
        if spec.policy_name and r.get("policy_name") != spec.policy_name:
            return False
        if spec.attempt_number is not None and r.get("attempt_number") != spec.attempt_number:
            return False
        amount = r.get("amount_inr")
        if spec.min_amount_inr is not None and (amount is None or amount < spec.min_amount_inr):
            return False
        if spec.max_amount_inr is not None and (amount is None or amount > spec.max_amount_inr):
            return False
        if spec.compliance_failed:
            if all(c.get("passed", True) for c in r.get("compliance_checks", [])):
                return False
        return True

    return [r for r in records if matches(r)]


def load_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def translate(question: str, client=None) -> QuerySpec:
    if client is None:
        import anthropic
        client = anthropic.Anthropic()

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": question}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return QuerySpec(rejected_reason="model returned no JSON object")
    try:
        return validate_spec(json.loads(match.group(0)))
    except json.JSONDecodeError as exc:
        return QuerySpec(rejected_reason=f"unparseable JSON from model: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the audit log a question in English")
    parser.add_argument("question", nargs="?", help="e.g. 'what did compliance block?'")
    parser.add_argument("--list-fields", action="store_true")
    args = parser.parse_args()

    if args.list_fields:
        print("\n".join(sorted(f.name for f in fields(QuerySpec) if f.name != "rejected_reason")))
        return
    if not args.question:
        parser.error("give a question, or use --list-fields")

    from dotenv import load_dotenv
    load_dotenv()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set -- translation needs the model")

    reports = Path(__file__).parent.parent / "eval" / "reports"
    records = load_records([
        reports / "decision_log_adaptive.jsonl",
        reports / "decision_log_baseline.jsonl",
        reports / "live_test_mode_decisions.jsonl",
        reports / "live_webhook_decisions.jsonl",
        reports / "examples" / "simulation_sample.jsonl",
        reports / "examples" / "live_test_mode_sample.jsonl",
    ])
    if not records:
        raise SystemExit("no audit records found -- run `python -m eval.run_eval --write-log` first")

    spec = translate(args.question)
    print()
    print(f'  Q: "{args.question}"')
    if not spec.valid:
        print(f"  ! query rejected: {spec.rejected_reason}")
        return

    print(f"  -> {spec.describe()}")
    matched = execute(spec, records)
    print(f"  {len(matched)} of {len(records)} records match"
          + (f", showing {min(spec.limit, len(matched))}" if matched else ""))
    print()

    total = sum(r.get("amount_inr") or 0 for r in matched)
    for r in matched[: spec.limit]:
        checks = " ".join(
            f'{c["invariant_id"].replace("INV-RBI-", "")}'
            f'{"" if c["passed"] else "=BLOCKED"}'
            for c in r.get("compliance_checks", [])
        )
        print(f'  {r["source"]:15s} {r["decision_type"]:26s} {r["rule_id"]:12s} '
              f'INR {r.get("amount_inr") or 0:>10,.2f}  {r["failure_class"]}')
        if checks:
            print(f'  {"":15s} {checks}')
    if matched:
        print()
        print(f"  total value across matches: INR {total:,.2f}")
    print()


if __name__ == "__main__":
    main()
