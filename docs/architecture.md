# Architecture

_Draft placeholder — full one-page diagram and component writeup lands at Milestone 7 (Day 11), once every
component below actually exists and this doc can describe the real thing rather than the plan for it._

## Component map (see repo root for the corresponding directories)

- `simulator/` — generates batches of mandate-failure events across 6 failure classes, driven entirely by
  `config/sim_params.yaml`. No fabricated point-estimate numbers; every non-directly-sourced parameter is a
  swept range, tagged with its `assumptions.md` ID.
- `policies/` — a shared `decide(state, failure_event) -> Decision` interface. `baseline_policy` and
  `adaptive_policy` both implement it; `external_policy_stub` documents, rather than hides, the fact that no
  real third-party engine is pluggable here (A26).
- `compliance/invariants/` — the 24-hour post-notification-failure floor and the OTP ceiling, enforced as
  tested invariants a policy cannot silently bypass.
- `audit/decision_log_schema/` — the structured record every policy decision writes to. Independent of the LLM
  narrator. Tagged `source: simulation | live_test_mode`.
- `eval/` — formal metric definitions, the single reproducibility entrypoint (`run_eval`), and generated
  reports.
- `narrator/` — reads `audit/` records only, produces human explanations and draft customer messages. Never
  feeds back into `policies/`.
- `integration/razorpay_test_mode/` — the scripted, repeatable seed process against real Razorpay test-mode
  APIs (the ~15-20 case qualitative integration proof — not a statistically powered validation set, see
  `docs/positioning.md` and A30).

## Data flow (draft)

`simulator` → `failure_event` → `policies.decide()` → `Decision` → `compliance.invariants` (checked) →
`audit.decision_log` (written) → `eval.metrics` (aggregated) → `narrator` (reads log, produces explanation,
never writes back).
