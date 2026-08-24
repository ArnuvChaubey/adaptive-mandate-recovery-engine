# eval/

Formal metric definitions and the single reproducibility entrypoint. No number appears in the README, the
deck, or the pitch video that didn't come out of running this.

Planned:
- `metrics/` (Milestone 2, Day 3-4) — recovery rate (both denominators), ₹ recovered, wasted attempts (ε
  frozen in `config/sim_params.yaml`, never tuned after seeing results), time to recovery, recovery lift —
  all defined before anything is computed against them.
- `run_eval` (Milestone 2 → hardened at Milestone 4) — `run_eval --config config/sim_params.yaml --seeds
  config/seeds.txt --policies baseline,adaptive [--scenarios config/scenarios.yaml]`.
- `reports/` — generated output. Only curated example reports are committed; the rest is gitignored because
  it's regenerable from the command above.
