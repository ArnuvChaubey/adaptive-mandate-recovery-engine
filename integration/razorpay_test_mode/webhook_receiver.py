"""Live webhook receiver -- the closed loop.

A real Razorpay event arrives, its HMAC signature is verified, and it is handed to the same policy
engine, the same compliance invariants, and the same audit schema used against the simulator. The
narration is produced from the resulting record. Nothing about the policy changes because the event
is real; that is the whole point.

    uvicorn integration.razorpay_test_mode.webhook_receiver:app --port 8010

Signature verification is the gate and is never optional. An unverified webhook is
attacker-controlled input, and everything downstream turns input into money decisions.
"""

import hashlib
import hmac
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

from audit.decision_log_schema.records import DecisionLog
from integration.razorpay_test_mode.idempotency import IdempotencyStore, event_key
from integration.razorpay_test_mode.live_pipeline import process_event
from narrator.llm_explainer.explainer import narrate
from policies.adaptive_policy.policy import AdaptivePolicy
from simulator.config_loader import load_config

load_dotenv()

app = FastAPI(title="Adaptive Mandate Recovery -- live webhook loop")

AUDIT_PATH = Path(__file__).parent.parent.parent / "eval" / "reports" / "live_webhook_decisions.jsonl"

_config = load_config()
_policy = AdaptivePolicy()
_log = DecisionLog()

# Attempts seen per mandate, so a second failure on the same entity is attempt 2 and the policy's
# stopping rule can actually fire. In-memory by design: this is a demonstration loop, and persisting
# it would imply a durability guarantee the process does not have.
_attempts: dict[str, int] = defaultdict(int)

# Razorpay retries webhooks and networks duplicate them. Without this, a replayed payment.failed
# increments the attempt counter twice and produces a second decision -- which in a deployment where
# decisions fire real debits is a double-charge bug.
_idempotency = IdempotencyStore()

_recovered_inr = 0.0


def verify_signature(raw_body: bytes, received_signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received_signature)


@app.post("/webhook")
async def receive_webhook(request: Request):
    global _recovered_inr

    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="RAZORPAY_WEBHOOK_SECRET not set in .env")

    signature = request.headers.get("X-Razorpay-Signature", "")
    raw_body = await request.body()  # raw bytes -- never parse before verifying

    if not verify_signature(raw_body, signature, secret):
        raise HTTPException(status_code=400, detail="signature verification failed")

    payload = json.loads(raw_body)
    event = payload.get("event", "unknown")

    # Idempotency gate, before any state is mutated. A replayed event returns the original answer
    # rather than nothing -- the same question deserves the same answer, and silently dropping it
    # would leave the caller with no result for an event it legitimately asked about.
    dedupe_key = event_key(payload)
    if dedupe_key and _idempotency.already_processed(dedupe_key):
        prior = _idempotency.prior_result(dedupe_key)
        print(f"[webhook] {event}: REPLAY of {dedupe_key} -- returning original decision, "
              f"no new attempt counted")
        return {**prior, "replayed": True}

    entity = (payload.get("payload", {}).get("payment", {}) or {}).get("entity", {})
    key = entity.get("order_id") or entity.get("id") or "unknown"
    _attempts[key] += 1

    result = process_event(payload, _config, _policy, attempt_number=_attempts[key])

    if result.recovered_amount_inr is not None:
        _recovered_inr += result.recovered_amount_inr
        print(f"[webhook] {event}: RECOVERED INR {result.recovered_amount_inr:,.2f} "
              f"(running total INR {_recovered_inr:,.2f})")
        response = {"status": "ok", "outcome": "recovered",
                    "amount_inr": result.recovered_amount_inr}
        if dedupe_key:
            _idempotency.record(dedupe_key, response)
        return response

    if result.record is None:
        print(f"[webhook] {event}: no decision -- {result.ignored_reason}")
        response = {"status": "ok", "outcome": "ignored", "reason": result.ignored_reason}
        if dedupe_key:
            _idempotency.record(dedupe_key, response)
        return response

    record = result.record
    _log.append(record)
    _log.write_jsonl(AUDIT_PATH)
    narration = narrate(record)

    print(f"[webhook] {event}: {record.decision_type.value} via {record.rule_id} "
          f"(INR {record.amount_inr:,.2f}, attempt {record.attempt_number})")
    print(f"           {narration.internal_explanation}")

    response = {
        "status": "ok",
        "outcome": record.decision_type.value,
        "rule_id": record.rule_id,
        "scheduled_retry_at": record.scheduled_retry_at.isoformat() if record.scheduled_retry_at else None,
        "escalation_action": record.escalation_action.value if record.escalation_action else None,
        "compliance_checks": [
            {"invariant": c.invariant_id, "passed": c.passed, "applicable": c.applicable}
            for c in record.compliance_checks
        ],
        "customer_message": narration.customer_message or None,
        "narration_source": narration.source,
        "influenced_decision": narration.influenced_decision,
    }
    if dedupe_key:
        _idempotency.record(dedupe_key, response)
    return response


@app.get("/health")
async def health():
    return {"status": "listening"}


@app.get("/state")
async def state():
    """Live view of what the loop has done -- useful for a demo without tailing logs."""
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "decisions_recorded": len(_log),
        "events_deduplicated": _idempotency.replays_detected,
        "recovered_inr": _recovered_inr,
        "compliance_violations": len(_log.compliance_failures()),
        "decisions": [
            {
                "mandate_id": r.mandate_id,
                "decision": r.decision_type.value,
                "rule_id": r.rule_id,
                "amount_inr": r.amount_inr,
                "failure_class": r.failure_class,
            }
            for r in _log
        ],
    }
