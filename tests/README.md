# tests/

- `test_invariants/` — compliance-floor tests. Must fail when an invariant (24h notice floor, OTP ceiling)
  is deliberately violated, proving the check actually checks something.
- `test_reproducibility/` — asserts `eval.run_eval` output matches a committed golden hash for a fixed
  seed/config. If this ever fails without a corresponding CHANGELOG entry in `assumptions.md`, something
  drifted silently and the run should not be reported.
