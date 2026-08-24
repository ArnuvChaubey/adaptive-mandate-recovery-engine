# simulator/

Generates batches of mandate-failure events across the 6 failure classes, driven entirely by
`config/sim_params.yaml`. Nothing here is fabricated as a point estimate — every non-directly-sourced
parameter is read from a swept range in the config, tagged with its `assumptions.md` ID.

Planned submodules (Milestone 2, Day 3-4):
- `failure_events/` — the 6 generators (`insufficient_funds`, `notification_undelivered`, `npci_congestion`,
  `bank_technical_decline`, `mandate_expired`, `mandate_revoked`), amount field included.
- `balance_evolution/` — the income-event/decay stochastic process. Isolated deliberately: it's the largest
  assumption cluster (A14/A15) and needs to be the easiest thing in the repo to audit or swap.
- `population/` — synthetic customer mixture over income-timing types (A12/A13).
