"""Idempotency for webhook delivery.

Razorpay retries webhooks that don't return 2xx, and networks duplicate deliveries independently of
that. Without deduplication the same `payment.failed` arriving twice produces two decisions, two
attempt increments, and — in a real deployment where decisions actually fire debits — potentially two
charges against the same customer for the same failure.

That is the difference between a demo and something you would let near money.

**The key is derived from the event, not the delivery.** A `payment.failed` for `pay_X` is a fact
about the world; it does not become a different fact because it was delivered twice. So the key is
(event type, payment id), and it deliberately does NOT include a timestamp or delivery id, both of
which vary between retries of the same event.

**A replay returns the original decision rather than nothing.** Skipping silently would leave the
caller with no answer for an event it legitimately asked about; returning the first decision is both
idempotent and honest — the same question gets the same answer.

In production this belongs in a durable store keyed by the same identity, with the decision log as
the source of truth. The in-memory implementation here is the same contract at demo scale, and says
so rather than implying persistence it does not have.
"""

from dataclasses import dataclass, field
from typing import Any


def event_key(payload: dict[str, Any]) -> str | None:
    """Stable identity for a webhook event, independent of how many times it is delivered.

    Returns None when the payload carries nothing stable enough to deduplicate on -- in which case
    the caller must decide, and the honest default is to process it rather than silently drop a
    real event.
    """
    event = payload.get("event")
    if not event:
        return None

    inner = payload.get("payload", {}) or {}
    for entity_type in ("payment", "subscription"):
        entity = (inner.get(entity_type) or {}).get("entity") or {}
        entity_id = entity.get("id")
        if entity_id:
            return f"{event}:{entity_id}"
    return None


@dataclass
class IdempotencyStore:
    """Remembers which events have been processed and what was decided.

    In-memory and per-process by design. Naming that explicitly matters: an idempotency store that
    silently loses its state on restart provides weaker guarantees than its callers assume, and the
    place to be clear about that is here rather than in a postmortem.
    """

    _seen: dict[str, Any] = field(default_factory=dict)
    replays_detected: int = 0

    def already_processed(self, key: str) -> bool:
        return key in self._seen

    def record(self, key: str, result: Any) -> None:
        self._seen[key] = result

    def prior_result(self, key: str) -> Any:
        self.replays_detected += 1
        return self._seen[key]

    def __len__(self) -> int:
        return len(self._seen)
