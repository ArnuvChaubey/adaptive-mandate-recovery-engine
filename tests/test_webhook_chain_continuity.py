"""Pins the webhook receiver's audit-chain wiring.

`live_batch.py` had this exact bug and it was fixed in build log entry 31: a module-level
`DecisionLog()` starts a fresh chain at GENESIS_HASH, and a `write_jsonl` without `append=True`
rewrites the whole file, so every process restart silently destroyed the prior run's audit history.

`webhook_receiver.py` carried the same two lines and was missed, because it is started by hand and
its committed example artifact was old enough (pre-dating hash chaining entirely) that the absent
hash fields looked normal. Found during the pre-submission audit by diffing the committed sample's
keys against the current schema.

The generic mechanism is covered in `test_decision_log_chain_continuity.py`. What is pinned *here*
is the wiring specific to this module -- that it seeds from the file's tip rather than from genesis,
which is the half a well-meaning refactor is most likely to drop.
"""

import importlib

import audit.decision_log_schema.records as records_mod


def test_receiver_seeds_its_chain_from_the_existing_audit_file(monkeypatch):
    """A fresh DecisionLog() here would splice a second genesis into the middle of the file, which
    verify_chain correctly reports as tampering. Assert the seed is read from the audit path."""
    seen: list = []
    real = records_mod.load_chain_tip

    def spy(path):
        seen.append(path)
        return real(path)

    monkeypatch.setattr(records_mod, "load_chain_tip", spy)

    import integration.razorpay_test_mode.webhook_receiver as wr
    importlib.reload(wr)

    assert seen, "receiver constructed its DecisionLog without seeding from the existing chain"
    assert seen[0] == wr.AUDIT_PATH, f"seeded from {seen[0]}, expected the audit path"


def test_receiver_appends_rather_than_truncating():
    """The second half of entry 31's bug: mode 'w' rewrote the file every webhook, so a restart
    dropped every earlier process's records."""
    import inspect

    import integration.razorpay_test_mode.webhook_receiver as wr

    src = inspect.getsource(wr)
    assert "write_jsonl(AUDIT_PATH, append=True)" in src, (
        "webhook receiver must append to its audit log; a default write truncates prior history"
    )
