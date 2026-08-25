# assumptions.md

Every assumption below load-bears on either simulator behavior or evaluation validity. None are padding.
**A1 is the highest Challenge Risk item in this table** — the entire baseline-vs-adaptive recovery-lift claim
depends on it, and it is the one input on the baseline side with no public source.

Legend: Confidence and Challenge Risk are rated LOW / MEDIUM / HIGH. Simulator Impact is NONE / LOW / MEDIUM / HIGH.

| ID | Statement | Evidence | Confidence | Simulator Impact | Challenge Risk |
|---|---|---|---|---|---|
| A1 | Card/UPI retry spacing beyond "retries the following day" follows a conservatively-biased, retry-friendly assumed schedule | Live-fetched Razorpay docs confirm only "following day" for cards; no public multi-attempt cadence found | LOW | HIGH — entire baseline policy timing | **HIGHEST** |
| A2 | Razorpay's actual production retry logic is at least as unsophisticated as our documented baseline (we're not attacking a strawman) | Contradicted in part by Razorpay's own Intelligent Retry Engine (beta, FTX 2026), which already critiques fixed-interval retry | LOW | Low direct, high narrative | HIGH |
| A3 | Emandate bank-holiday shift logic (T-1, T-3) generalizes to holiday-calendar handling across instruments | Directly documented for Emandate only | MEDIUM | MEDIUM | MEDIUM |
| A4 | ~~An undelivered pre-debit notification legally auto-blocks the debit~~ **REFUTED 2026-08-25** — the framework imposes a *send* obligation only | RBI Digital Payments E-mandate Framework 2026, Clause 6(a): *"An issuer shall send a pre-transaction notification to the customer, at least 24 hours prior to the actual charge / debit."* No delivery-confirmation requirement and no auto-block clause exists. Confirmed against two independent analyses of the framework text | **REFUTED** | Was HIGH — now replaced by A5 (timing invariant) and A34 (behavioural effect) | Resolved — the claim is no longer made anywhere in the project |
| A5 | The compliance invariant is a **timing** constraint: no debit attempt may be scheduled less than 24h after the pre-transaction notification was *sent* | RBI E-mandate Framework 2026, Clause 6(a), quoted above — primary-source-backed with a clause number | HIGH | HIGH — this is the hard invariant `compliance/invariants/` enforces | LOW — directly quotable |
| A6 | ₹15,000 no-OTP ceiling (₹1L for insurance/mutual funds/credit-card-bill categories) is accurate at submission time | RBI E-Mandate Framework 2026 reporting; this figure has a revision history | HIGH | LOW | MEDIUM — re-verify immediately pre-submission |
| A7 | NPCI 2026 Traffic Management congestion windows (10am-1pm worst) are stable through the project window | Single-sourced (Republic World, May 2026) | MEDIUM | MEDIUM | MEDIUM |
| A8 | Magnitude of success-probability degradation during the congestion window | No public % exists anywhere | LOW | HIGH for `npci_congestion` realism | HIGH |
| A9 | ~20M UPI Autopay revocations/month, dominantly insufficient-balance-driven | Business Standard, Sept 2025, single-sourced aggregate | MEDIUM-HIGH | MEDIUM | MEDIUM |
| A10 | The 20M/month revocation stat maps to a per-attempt insufficient-funds failure probability | Revocation is a mandate-cancellation event, not a single failed attempt — unjustified inferential leap as stated | LOW | HIGH — directly parameterizes `insufficient_funds` | HIGH |
| A11 | ~808M mandate executions/month (2025) is a stable order-of-magnitude denominator | Single-sourced (Business Standard) | MEDIUM | LOW | LOW |
| A12 | Salary/income crediting clusters near month-end/1st and near the 7th at a population level | Legal deadline (Payment of Wages Act, FACT) + converging industry sources (INFERENCE) | MEDIUM-HIGH | MEDIUM | MEDIUM |
| A13 | Any individual simulated customer's personal adherence to the population-level salary pattern | No source can establish this — aggregate clustering ≠ individual behavior | LOW | HIGH — shapes the customer-population mixture model | HIGH |
| A14 | Balance evolution follows a rise-at-income-event / decay-between-events shape | INFERENCE from general financial-behavior patterns, no specific cited curve | LOW-MEDIUM | HIGH | HIGH |
| A15 | Balance decay rate / spending-volatility parameter values | Pure assumption, no source | LOW | HIGH | HIGH |
| A16 | Number of consecutive failures before a customer voluntarily revokes a mandate | No public source | LOW | MEDIUM-HIGH | MEDIUM |
| A17 | Notification delivery failure rate for the relevant channel | Only generic (non-India-specific, non-Razorpay-specific) messaging-industry benchmarks exist as an anchor | LOW | MEDIUM | MEDIUM |
| A18 | `bank_technical_decline` base rate and recovery-on-retry probability | No public source found at all — least-evidenced failure class in the taxonomy | LOW | MEDIUM | MEDIUM |
| A19 | `mandate_expired` / `mandate_revoked` are unrecoverable by any retry-timing strategy | Logical/definitional, follows from mandate lifecycle mechanics | HIGH | LOW (by design, not tunable) | LOW |
| A20 | 4-attempt retry cap matches Razorpay's documented halt condition and is the correct ceiling for both policies | Directly documented | HIGH | HIGH — defines the entire stopping-rule design | LOW-MEDIUM |
| A21 | Total calendar-time stopping window, downstream of A1's uncertain cadence | Not independently sourced — inherits A1's uncertainty | LOW | MEDIUM | MEDIUM |
| A22 | Mandate amount distribution (needed for the ₹-recovered metric) | No public per-mandate amount distribution sourced for OTT/SIP/EMI mix | LOW | HIGH — the entire "measured money" claim depends on this | HIGH |
| A23 | Wasted-attempt threshold ε, frozen before evaluation | Design choice, not empirically derived | N/A (methodological) | HIGH — defines a headline metric | MEDIUM — must never be tuned post-hoc |
| A24 | Choice of recovery-rate denominator (recoverable-only vs. all) doesn't structurally favor either policy | Needs empirical confirmation once results exist, currently unverified | N/A | MEDIUM | MEDIUM |
| A25 | No independent, publicly benchmarked evaluation of adaptive-vs-fixed mandate retry currently exists | Absence-of-evidence claim, based on directly fetching Razorpay's own FTX 2026 materials, which disclose no methodology or numbers | MEDIUM-HIGH | N/A (positioning) | MEDIUM — scoped narrowly to "no *public* benchmark" |
| A26 | The harness's "policy-agnostic" claim is a design property, not demonstrated against Razorpay's actual engine | Neither Intelligent Retry Engine nor the Subscription Recovery Agent exposes a public callable interface | HIGH | N/A | HIGH — architecture must show this honestly (see `policies/external_policy_stub/`), not imply it away |
| A27 | "Measured money recovered" in the rubric can be satisfied by simulated-batch money, provided it's labeled as such everywhere | Interpretive judgment about how judges will read the rubric wording | N/A | N/A | HIGH — the single biggest interpretive gamble in the project |
| A28 | Fixed seeds + versioned config are sufficient to demonstrate reproducibility within a live judging session's time budget | Assumption about the format/timing of judging | N/A | N/A | MEDIUM |
| A29 | The test-mode 3-day token window can be operated via a scripted, repeatable seeding process without manual intervention | Not yet demonstrated — engineering feasibility assumption | N/A | N/A | MEDIUM — becomes concrete at M1/M6 |
| A30 | ~15-20 live test-mode cases will be read as sufficient proof of end-to-end integration, not mistaken for statistical validation | Assumption about audience interpretation, mitigated only by explicit labeling discipline | N/A | N/A | MEDIUM-HIGH |
| A31 | `bank_technical_decline` per-attempt base rate, range [0.01, 0.05] | No public source — placeholder order-of-magnitude for transient bank-side technical declines in card processing generally | LOW | MEDIUM | MEDIUM |
| A32 | `mandate_expired` validity/expiry duration, range [180, 1095] days | No public source for typical UPI Autopay/mandate validity period; wide range reflects genuine uncertainty, not confidence | LOW | MEDIUM | MEDIUM |
| A33 | Mandate amount-type mixture weights across OTT/SIP/EMI bands | No public source for the population split across these product types | LOW | MEDIUM — shapes the ₹-recovered distribution | MEDIUM |
| A35 | Escalation response rate (customer acts on a re-auth / re-mandate / manual-payment request), range [0.10, 0.40], with a [1, 7] day response lag | No public source. **Applied identically to every policy that escalates**, so it cannot manufacture lift on its own — the only asymmetry it creates is that a policy firing a legally-refusable auto-retry has no escalation to respond to | LOW | HIGH — carries the entire measured value of "compliant escalation" | **HIGH — the most attackable parameter in the project, because it directly drives the ₹-recovered headline. Must always be reported as swept, never as a point estimate** |
| A34 | An undelivered notification reduces success probability **behaviourally** (an unaware customer is less likely to top up before the debit), multiplier range [0.3, 0.8] | No public source. Replaces the refuted A4. Explicitly **not** a regulatory effect — the framework imposes no block on non-delivery | LOW | MEDIUM — drives `notification_undelivered` | MEDIUM — must never be described as a compliance rule |

## Pattern worth naming directly

A10, A13, A15, A17, A18, and A22 are the same failure mode in different clothes — a real, citable *aggregate*
fact (revocation volume, salary clustering, messaging benchmarks) stretched to cover a per-individual or
per-attempt number that no aggregate can actually supply. That stretch is unavoidable given the no-real-data
constraint. It is not a flaw to fix — it is exactly what the sensitivity-sweep methodology in `eval/` exists to
survive. If the headline result only holds at one exact point in that stretched range, the project has a real
problem. If it holds across the swept range, that is the actual evidence.

## CHANGELOG (post-freeze parameter changes)

Per the anti-circularity requirement: `config/sim_params.yaml` must be frozen and committed *before* the adaptive
policy is evaluated against it. Any change made after seeing evaluation results is logged here with date, what
changed, why, and an explicit statement of whether results were already observed before the change.

**2026-08-25 (third entry)** — Added an `escalation` block (A35: response rate and response lag).
Without it, escalation decisions recovered nothing in-model, so "compliant escalation" measured as
worthless and the compliance decomposition returned +0.0% across the board — an artefact of the model
having no path for an escalated mandate to ever recover, not a finding. The rate is applied
identically to every policy that escalates, precisely so it cannot manufacture lift on its own.
**No adaptive-policy result had yet been accepted or reported when this was added**; the first
three-way run was executed after this change, not before. Also fixed a genuine bug in
`check_otp_ceiling`: it flagged *escalation* decisions as ceiling violations, penalising the very
behaviour the ceiling requires. The ceiling now applies only where an auto-debit is actually scheduled.

**2026-08-25 (second entry)** — Restructured `failure_classes.notification_undelivered` after a
primary-source check refuted A4. The original brief claimed an undelivered pre-debit notification
legally auto-blocks the debit; the RBI E-mandate Framework 2026 Clause 6(a) actually imposes only a
*send* obligation ("An issuer shall send a pre-transaction notification to the customer, at least 24
hours prior to the actual charge / debit"), with no delivery-confirmation requirement and no
auto-block clause. Replaced `post_failure_min_retry_hours` with
`min_hours_between_notification_and_debit` (the real, quotable compliance invariant), and added
`undelivered_success_multiplier` as an explicitly *behavioural* effect (A34), not a regulatory one.
**No baseline or adaptive-policy results existed at this point** — no policy code has been written
yet. This is a correctness fix to ground truth, not a tuning change.

**2026-08-25** — Added numeric values for `bank_technical_decline.base_rate`, `mandate_expired`
validity duration, and `mandate_amount_distribution` type-mixture weights (A31-A33). These fields existed
in the frozen v0 schema with a status tag but no value — Day 3 simulator coding needed real numbers to
run against. **No baseline or adaptive-policy results existed at this point** — freeze commit `894d1d3`
predates any policy code entirely, so this completes an incomplete draft rather than tuning a result.
Recommitted as the new frozen baseline; see `config/sim_params.yaml`'s `meta` block for the updated hash.
