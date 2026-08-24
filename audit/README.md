# audit/

The structured, queryable decision log every policy writes to on every retry/stop/escalate decision.
Independent of the LLM narrator — this must remain fully inspectable with the narrator layer switched off
entirely. Every record is tagged `source: simulation | live_test_mode`.

Planned (Milestone 2, Day 3-4):
- `decision_log_schema/` — one record per decision: failure event, rule ID that fired, decision made,
  timestamp, compliance-floor checks applied, source tag.
