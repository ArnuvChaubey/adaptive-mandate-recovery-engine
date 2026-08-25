"""Idempotency tests.

Razorpay retries webhooks and networks duplicate them independently. In a system where a decision
eventually fires a debit, processing the same failure twice is a double-charge bug — so these tests
exist to pin the exact property that prevents it.
"""

from integration.razorpay_test_mode.idempotency import IdempotencyStore, event_key


def failed(payment_id="pay_A", order_id="order_A", created_at=1787591039):
    return {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {
            "id": payment_id, "order_id": order_id, "amount": 50000,
            "error_reason": "insufficient_fund", "created_at": created_at,
        }}},
        "created_at": created_at,
    }


def test_same_event_yields_same_key():
    assert event_key(failed()) == event_key(failed())


def test_key_is_stable_across_redelivery_timestamps():
    """A retry of the same event carries a different delivery time. The key must not include it, or
    every redelivery looks new and deduplication silently does nothing."""
    assert event_key(failed(created_at=1787591039)) == event_key(failed(created_at=1787599999))


def test_different_payments_yield_different_keys():
    assert event_key(failed(payment_id="pay_A")) != event_key(failed(payment_id="pay_B"))


def test_different_event_types_on_same_payment_are_distinct():
    """A payment that fails and is later captured produces two legitimately different facts about
    the same entity; collapsing them would drop the capture."""
    captured = failed()
    captured["event"] = "payment.captured"
    assert event_key(failed()) != event_key(captured)


def test_key_is_none_when_nothing_stable_is_present():
    """No stable identity means the caller must decide. The honest default is to process the event
    rather than silently drop a real one."""
    assert event_key({"event": "payment.failed", "payload": {}}) is None
    assert event_key({}) is None


def test_store_detects_replay_and_returns_original_result():
    store = IdempotencyStore()
    key = event_key(failed())
    assert not store.already_processed(key)

    store.record(key, {"outcome": "retry_scheduled", "rule_id": "ADAPT-004"})
    assert store.already_processed(key)

    prior = store.prior_result(key)
    assert prior["rule_id"] == "ADAPT-004"
    assert store.replays_detected == 1


def test_three_deliveries_produce_one_decision():
    """The end-to-end property, verified over real HTTP as well: three deliveries of one event give
    one decision and two deduplications."""
    store = IdempotencyStore()
    key = event_key(failed())
    decisions = 0

    for _ in range(3):
        if store.already_processed(key):
            store.prior_result(key)
            continue
        decisions += 1
        store.record(key, {"outcome": "retry_scheduled"})

    assert decisions == 1
    assert store.replays_detected == 2
    assert len(store) == 1
