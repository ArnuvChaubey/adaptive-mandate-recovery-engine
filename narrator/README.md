# narrator/

Reads `audit/` decision-log records only. Produces a human-readable explanation and a draft customer
notification message. Never writes back into policy state — that boundary is the direct evidence for Track
03's "AI judgment" criterion ("the right tool in the right place, and where you chose not to use one").

Scheduled deliberately last (Milestone 5, Day 8-9) — everything above it must already produce a real number
before this starts. If time runs short, this is what gets cut, not the measurement.

Planned:
- `llm_explainer/` — strict prompt template that only summarizes structured fields from a decision-log
  entry; output schema carries an explicit narration-vs-decision tag so it can never be mistaken for having
  influenced the decision.
