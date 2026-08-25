# narrator/

Turns decision-log records into prose for operators and customers. Built last, on purpose: the
measurement had to work first, and this is the layer that gets cut if time runs short.

## The boundary

The narrator reads `audit/` records **after** decisions are made. It never writes to policy state,
never participates in a decision, and cannot run before one has been logged. Delete this directory
entirely and the engine, the audit trail, and every number in the evaluation are unchanged.

Every `Narration` carries `influenced_decision: False` in its output schema — not as decoration, but
so that anyone reading a narration in a report, a demo, or a JSON dump can see the boundary without
having to trust a claim made elsewhere.

## Why the LLM is not the primary path

`templates.py` produces narration deterministically, assembled from structured fields that are
already in the record. It cannot invent a rupee amount, a date, or a regulation. That is the default
path and it runs with no API key, no network, and no model.

`llm_explainer/` sits on top and rewrites the same facts more fluently. It adds readability, never
information. If it is unconfigured, unreachable, errors, or produces output that fails grounding
validation, the system falls back to the template — so a model failure costs fluency, never
correctness.

## The grounding check

`validator.py` mechanically verifies LLM output against the source record before it is used:

- every number must appear in the record (small integers are exempt — "a second attempt" is prose)
- the rule ID that fired must be cited verbatim
- prohibited claims (refunds, penalties, legal action, credit scores, guarantees) are rejected outright

It is a mechanical check rather than a second model grading the first, because a validator that can
itself hallucinate is not a validator. `tests/test_narrator.py` proves it rejects a fabricated
amount, a prohibited claim, and a missing rule citation — a guard that never fires is
indistinguishable from no guard.

## Run it

```
python -m narrator.narrate --limit 6
```

Works with or without `ANTHROPIC_API_KEY`; the output states which path produced each narration.
