# Research Matrix

For every failure class plus the cross-cutting items that turned out to matter more than any single failure
class, this records: evidence required, public sources found, and confidence level. Six background facts
(subscription lifecycle states, RBI notification requirement's existence, NPCI AutoPay's existence, mandate
revocability, unrecoverable-failure existence, no-real-data constraint) are treated as settled and not re-derived
here.

| # | Item | Evidence Required | Public Sources | Confidence |
|---|---|---|---|---|
| R1 | **Baseline retry interval/timing (highest risk item)** | Exact spacing between the 4 documented retry attempts, per instrument | [Razorpay Payment Retries docs](https://razorpay.com/docs/payments/subscriptions/payment-retries/): cards — "We automatically retry the payment on the following day" (vague, not T+1/T+2/T+3); Emandate — precise bank-holiday shift rule (T-1, or T-3 if T and T-1 are both holidays). No UPI-specific cadence found on current live docs. | MEDIUM for Emandate holiday-shift mechanics (FACT). **LOW for card/UPI multi-attempt spacing — stays ASSUMPTION.** |
| R2 | `insufficient_funds` | Base rate / materiality | [Business Standard, Sept 2025](https://www.business-standard.com/finance/news/upi-autopay-revocations-hit-20-mn-monthly-over-low-customer-balances-125090700500_1.html): ~20M UPI Autopay revocations/month attributed to insufficient balance; dominant use cases OTT, loan repayment, investments, utilities. Execution volume context: ~808M mandate executions/month (Jul 2025). | MEDIUM-HIGH for existence/materiality. **LOW for mapping to a per-attempt failure probability** (revocation ≠ single failed attempt, see A10). |
| R3 | `notification_undelivered` | Regulatory mechanism: does non-delivery legally block the debit? | RBI e-mandate framework circulars: 24-hour minimum pre-debit notice confirmed, with mandatory opt-out facility. "Undelivered ⇒ auto-blocked" mechanism from original brief **not yet independently re-verified against RBI primary-circular text**. | MEDIUM. Dedicated primary-source check pending (RBI/2024-25/64 or successor circular). |
| R4 | `npci_congestion` | Existence and timing of deprioritization windows | Republic World, May 2026 — 10am-1pm worst, before 10am / 1-5pm / after 9:30pm better. | MEDIUM — single-sourced, live regulatory area. **Magnitude of degradation: no public % — LOW, pure ASSUMPTION.** |
| R5 | `bank_technical_decline` | Base rate, recovery-on-retry probability | No public source found for this failure class specifically. | **LOW — least-evidenced failure class in the taxonomy.** Justified by category logic only. |
| R6 | `mandate_expired` | Confirms unrecoverable-by-retry-timing status | Follows from mandate lifecycle mechanics | HIGH — logical/definitional |
| R7 | `mandate_revoked` | Confirms unrecoverable-by-retry-timing status | Same logic as R6; volume context from R2 | HIGH — logical/definitional |
| R8 | Salary-cycle / income-event timing (for balance-evolution modeling) | Legal payment deadlines + observed practice | Payment of Wages Act — legal deadline: 7th of following month (<1,000 employees), 10th (larger). Multiple industry payroll sources report common practice clustering around month-end/1st and around the 7th. | MEDIUM-HIGH for **population-level** clustering. **LOW for any individual customer's personal adherence.** |
| R9 | Compliance floors (₹15,000 / ₹1L OTP ceiling) | Current thresholds, exemption categories | RBI E-Mandate Framework 2026: ₹15,000 general no-OTP ceiling confirmed current; ₹1 lakh threshold for insurance/mutual funds/credit-card-bill categories. | HIGH, but explicitly a live regulatory area — this number has a revision history. |
| R10 | **Competitive landscape — Intelligent Retry Engine / Agent Studio** | What Razorpay already ships in this exact problem space | [Razorpay Newsroom, FTX 2026](https://razorpay.com/newsroom/razorpay-launches-the-worlds-first-ai-native-agent-studio-for-payments-at-ftx26-powered-by-anthropics-claude/): Agent Studio ships a "Subscription Recovery Agent" (voice-led, ElevenLabs). [Intelligent Revenue-Protect blog](https://razorpay.com/blog/upi-autopay-with-intelligent-revenue-protect/): "Intelligent Retry Engine" (beta) critiques fixed-interval retry, lets merchants configure retry cadence/templates. No published methodology, no disclosed approach, no recovery-rate/lift numbers, no audit-trail or compliance framing in either source. | HIGH for existence/positioning (primary-sourced). This is the basis for A25's differentiation claim. |

## Open items carried into Week 1

- **R1** stays the highest-priority unresolved item — the entire baseline timing model rests on it.
- **R3** needs a direct primary-source check against the actual RBI circular text (not press summaries) before A4 can be upgraded past MEDIUM confidence.
- **R9** needs re-verification immediately before submission — this threshold has changed before.
