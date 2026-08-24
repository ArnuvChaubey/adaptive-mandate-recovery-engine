# compliance/

Hard-coded, tested regulatory floors — kept separate from `policies/` specifically so a policy change can
never silently bypass them, and so a reviewer can verify that fact by looking at one small module instead of
auditing all policy logic.

Planned (Milestone 3, Day 5-6):
- `invariants/` — the 24-hour post-notification-failure minimum retry floor (A5) and the OTP-free ceiling /
  higher-ceiling categories (A6). `tests/test_invariants` must fail when one of these is deliberately violated
  — that's the proof the check is real, not decorative.
