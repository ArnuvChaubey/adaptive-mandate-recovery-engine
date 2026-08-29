# assumptions.md

Every assumption below load-bears on either simulator behavior or evaluation validity. None are padding.
**A1 was the highest Challenge Risk item in this table until 2026-08-28**, when a pre-submission
re-verification found the cadence is in fact published for both cards and UPI. It is now a cited FACT,
and the committed baseline value turned out to match the documented schedule exactly. The highest
remaining risks are A35 (escalation response rate, which carries the ₹ headline and has no public
source) and A13 (individual adherence to the population-level payday pattern).

Legend: Confidence and Challenge Risk are rated LOW / MEDIUM / HIGH. Simulator Impact is NONE / LOW / MEDIUM / HIGH.

| ID | Statement | Evidence | Confidence | Simulator Impact | Challenge Risk |
|---|---|---|---|---|---|
| A1 | ~~Card/UPI retry spacing is an unsourced assumption~~ **RESOLVED 2026-08-28 — now a FACT.** Razorpay documents the full multi-attempt cadence for cards *and* UPI | [Razorpay Payment Retries docs](https://razorpay.com/docs/payments/subscriptions/payment-retries/): *"we automatically reattempt the charge on T+1 day. If the charge fails again, we automatically reattempt the charge two more times on T+2 and T+3 days, respectively"*, then `halted`. Cross-checks A20 (1 charge + 3 retries = the 4-attempt cap). Emandate is documented as a different, bank-confirmation-driven model | **HIGH** | HIGH — entire baseline policy timing | **LOW** — directly quotable, and the committed value matches it |
| A2 | Razorpay's actual production retry logic is at least as unsophisticated as our documented baseline (we're not attacking a strawman) | Contradicted in part by Razorpay's own Intelligent Retry Engine (beta, FTX 2026), which already critiques fixed-interval retry | LOW | Low direct, high narrative | HIGH |
| A3 | Emandate bank-holiday shift logic (T-1, T-3) generalizes to holiday-calendar handling across instruments | Directly documented for Emandate only | MEDIUM | MEDIUM | MEDIUM |
| A4 | ~~An undelivered pre-debit notification legally auto-blocks the debit~~ **REFUTED 2026-08-25** — the framework imposes a *send* obligation only | RBI Digital Payments E-mandate Framework 2026, Clause 6(a): *"An issuer shall send a pre-transaction notification to the customer, at least 24 hours prior to the actual charge / debit."* No delivery-confirmation requirement and no auto-block clause exists. Confirmed against two independent analyses of the framework text | **REFUTED** | Was HIGH — now replaced by A5 (timing invariant) and A34 (behavioural effect) | Resolved — the claim is no longer made anywhere in the project |
| A5 | The compliance invariant is a **timing** constraint: no debit attempt may be scheduled less than 24h after the pre-transaction notification was *sent* | RBI E-mandate Framework 2026, Clause 6(a), quoted above — primary-source-backed with a clause number | HIGH | HIGH — this is the hard invariant `compliance/invariants/` enforces | LOW — directly quotable |
| A6 | ₹15,000 no-OTP ceiling (₹1L for insurance/mutual funds/credit-card-bill categories) is accurate at submission time | **Re-verified 2026-08-25.** RBI E-Mandate Framework 2026; BusinessToday (21 Apr 2026) reports the framework as effective immediately, ₹15,000 general ceiling and ₹1 lakh for insurance / mutual funds / credit-card bills both unchanged | HIGH | LOW | LOW — verified close to submission |
| A7 | NPCI 2026 Traffic Management congestion windows (10am-1pm worst) are stable through the project window | **Re-verified 2026-08-25 and upgraded from single-sourced.** Originally Republic World (May 2026) alone; now independently corroborated by Paytm and Pine Labs write-ups describing the same 10:00-13:00 peak window and the same better windows (before 10:00, 13:00-17:00, after 21:30), with enforcement of "execution windows" reported as active since May 2026 | MEDIUM-HIGH | MEDIUM | LOW-MEDIUM |
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
| A29 | The test-mode 3-day token window can be operated via a scripted, repeatable seeding process without manual intervention | **Scope narrowed 2026-08-25.** The 3-day limit applies to *card tokens* created during subscription authorisation, not to API keys (which do not expire). Razorpay docs: *"In test mode, you can perform a subsequent debit only within 3 days of token creation, as card tokens are valid for 3 days only."* The live subset currently uses one-time Payment Links, which tokenise nothing — so the window does not bind unless M6 returns to the subscription path | MEDIUM | N/A | LOW-MEDIUM — materially reduced now that the live path avoids tokenisation |
| A30 | ~15-20 live test-mode cases will be read as sufficient proof of end-to-end integration, not mistaken for statistical validation | Assumption about audience interpretation, mitigated only by explicit labeling discipline | N/A | N/A | MEDIUM-HIGH |
| A31 | `bank_technical_decline` per-attempt base rate, range [0.01, 0.05] | No public source — placeholder order-of-magnitude for transient bank-side technical declines in card processing generally | LOW | MEDIUM | MEDIUM |
| A32 | `mandate_expired` validity/expiry duration, range [180, 1095] days | No public source for typical UPI Autopay/mandate validity period; wide range reflects genuine uncertainty, not confidence | LOW | MEDIUM | MEDIUM |
| A33 | Mandate amount-type mixture weights across OTT/SIP/EMI bands | No public source for the population split across these product types | LOW | MEDIUM — shapes the ₹-recovered distribution | MEDIUM |
| A36 | Failure-class mix: 55% insufficient funds, 15% congestion, 10% notification, 10% technical, 5% expired, 5% revoked | No public distribution of failure classes for Indian recurring payments exists — that is precisely the proprietary data this project works without. The dominance of insufficient funds is consistent with A9 (~20M monthly UPI Autopay revocations attributed to low balance) | LOW | **HIGH — the single most impactful parameter in the simulator** | MEDIUM — now swept across three mixes (funds-dominated, technical-dominated, high-unrecoverable) |
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

**2026-08-28 (eighth entry) — COMMENT-ONLY CHANGE + assumption re-rating. No value moved.**
Pre-submission re-verification of A1 (the project's stated highest-risk assumption) found that
Razorpay *does* publish the multi-attempt retry cadence, for cards and UPI both: T+1, T+2, T+3, then
`halted`. The assumption table had claimed "no public multi-attempt cadence found," which was false as
of this date and would have been visible as stale research to any reviewer who works there.

Two corrections followed. A1 is re-rated from LOW confidence / HIGHEST challenge risk to **FACT /
LOW risk**, quoting the docs. And a comment in `sim_params.yaml` that labelled `[1, 2, 3]` as
"T+1/T+2/T+3" was wrong on its own terms: the values are *gaps* (see
`policies/baseline_policy/policy.py`), so `[1, 2, 3]` produces T+1/T+3/T+6, while a repeated `[1]` is
what actually yields T+1/T+2/T+3.

**Results were already observed. No number changed and none could:** `value: [1]` is untouched, and
the conservative headline is reported against `[3, 7, 14]` regardless. The effect is that the
baseline's timing stops being an assumption and becomes a citation — the project's weakest link got
stronger without any figure moving. See docs/build_log.md entry 28.

**2026-08-27 (seventh entry) — CODE CORRECTNESS FIX, not a config change.** `config/sim_params.yaml`
is untouched. Both the adaptive policy and `compliance/invariants/rules.py` compared this project's
product names (`ott_subscription`, `sip_investment`, `emi`) directly against A6's
`higher_ceiling_categories` (`insurance`, `mutual_funds`, `credit_card_bills`). Those sets are
disjoint, so the ₹1,00,000 higher ceiling was unreachable everywhere and A6's carve-out was, in
effect, unimplemented — while a unit test covering it passed throughout, because it supplied the
category by hand. Fixed with an explicit `sip_investment → mutual_funds` mapping (deliberately not
mapping `emi`, which is a loan instalment rather than a credit-card bill; claiming that carve-out
without a citation is the A4 mistake).

**Results were already observed before this change, and it made ours worse.** The conservative
headline fell from **+12.5% to +8.7%**, because the bug was suppressing the *baseline* more than the
candidate — 12.3% of mandates were being escalated when the law permits an auto-retry, and the
baseline lost more of them. Recorded here rather than quietly re-baselined: this is a correctness fix
to a misimplemented FACT, in the direction that costs us. See docs/build_log.md entry 26.

**2026-08-25 (sixth entry)** — Moved the failure-class distribution from `eval/harness.py` into
`config/sim_params.yaml` as `failure_class_mix` (A36). It had been hardcoded in the harness since day
4, which meant the single most impactful ground-truth parameter in the simulator sat **outside** the
freeze protocol the entire credibility claim depends on, carried no assumption ID, and could not be
swept. Values are unchanged, so no result moved; the parameter is simply now inside the discipline it
should always have been inside. Three sensitivity scenarios were added to exercise it, taking the
sweep from 15 scenarios to 18. Detail in `docs/build_log.md` entry 18.

**2026-08-25 (fifth entry) — POLICY ITERATION, not a config change.** Added
`policies/adaptive_hedged_policy/` after observing that `adaptive` lost badly on wasted attempts.
`config/sim_params.yaml` was **not modified** — the freeze protects simulator ground truth, and
iterating a policy against fixed ground truth is the intended use of the harness. Logged here anyway
because the change was made *after* seeing results and a reader is entitled to know that. The
original `adaptive` policy is retained unchanged and both are reported side by side; neither
dominates (see `docs/build_log.md` entry 16).

**2026-08-25 (fourth entry)** — Added `plausible_alternatives` to A1
(`retry_policy_shared.card_retry_cadence_days`) and made baseline cadence a swept sensitivity
dimension. **This change was made after adaptive-policy results had been observed, and it made our
own headline number worse — deliberately.** Measurement showed the committed `[1]` cadence is the
*weakest* plausible baseline (63.5%), not the strongest (74.6% at `[3,7,14]`): repeated next-day
retries hammer an empty account, while spread retries catch income events. The brief required
biasing the baseline toward the harder comparison case, and `[1]` did the opposite. The headline is
now reported against the strongest baseline, dropping the recovery-rate lift from ~+36% to **+11.8%**.
Detail in `docs/build_log.md` entry 13.

Two harness bugs were also fixed, both surfaced by the sweep returning byte-identical results for
scenarios that should have differed: (a) all mandates were created at midnight so the NPCI congestion
window never triggered for anyone, making that failure class inert; (b) mandate revocation could only
ever be a starting condition, so A16's threshold was never read and customers could never give up
mid-sequence. Both fixes **increased** measured lift, which is the direction that warrants scrutiny —
see the build-log entry for why each mechanism is independently justified rather than convenient.

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
