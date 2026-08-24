# Adaptive Mandate Recovery Engine

Built for Razorpay's AI Buildathon, Track 03 — AI Revenue Recovery.

## What this is

An open, auditable, reproducible **evaluation harness** for adaptive recurring-payment mandate-recovery
policies. Razorpay's own Intelligent Retry Engine (beta, FTX 2026) already validates the core thesis — fixed-
interval retry is the wrong model — but ships as a configurable black box with no published methodology, no
benchmarked recovery lift, and no visible audit trail. This project is the credibility layer such a system
doesn't currently expose publicly: a policy-agnostic harness that scores a deterministic Adaptive Policy
against a documented-behavior Baseline, on identical frozen simulator ground truth, with every retry/stop/
escalate decision traceable to a rule in an audit log.

Full positioning, including the honest limits of this framing, is in [docs/positioning.md](docs/positioning.md).

## What this is NOT

- Not payment processing, not a payment predictor, not a Razorpay replacement.
- Not a claim about real-world recovery rates. Every recovery-rate, lift, and ₹-recovered number this project
  produces is a **simulated-batch statistic**, computed from a frozen, version-controlled config
  (`config/sim_params.yaml`) and a fixed seed list (`config/seeds.txt`) — labeled as such everywhere it
  appears, no exceptions.
- Not benchmarked against Razorpay's actual Intelligent Retry Engine — that engine exposes no public callable
  interface. See assumption A26.
- The ~15-20 case Razorpay test-mode subset (`integration/razorpay_test_mode/`) is a **qualitative integration
  proof** — evidence the system calls real APIs end to end — not a statistically powered validation set. It
  never appears next to a recovery-rate number as if it supports it.

## Status

Day 1 of 13 (deadline: 5 September 2026). Repository scaffold only — no simulator, policy, or eval code yet.
See the implementation plan below for what lands when.

## Repository map

| Path | Purpose |
|---|---|
| `simulator/` | Generates failure-event batches across 6 classes; every non-sourced parameter is a swept range, not a fabricated point estimate |
| `policies/` | Shared `decide()` interface; `baseline_policy`, `adaptive_policy`, and an honest unreachable `external_policy_stub` |
| `compliance/` | Hard-coded, tested regulatory floors (24h notice, OTP ceiling) — separate from policy logic on purpose |
| `audit/` | Structured decision log, independent of the LLM narrator |
| `eval/` | Formal metric definitions and the single reproducibility entrypoint |
| `narrator/` | LLM explanation/customer-messaging layer — reads the audit log only, never decides anything |
| `integration/razorpay_test_mode/` | Scripted, repeatable Razorpay test-mode API calls |
| `assumptions.md` | Every load-bearing assumption — statement, evidence, confidence, simulator impact, challenge risk |
| `docs/research_matrix.md` | Evidence and confidence per failure class and cross-cutting item |
| `docs/positioning.md` | The competitive framing against Razorpay's own Intelligent Retry Engine |

## Setup

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your own Razorpay TEST MODE keys — never commit .env
```

## Reproducibility

Once `eval/run_eval` exists (Milestone 2), every number in this README, the pitch video, and the demo comes
from one command:

```
python -m eval.run_eval --config config/sim_params.yaml --seeds config/seeds.txt --policies baseline,adaptive
```

No cited result exists that didn't come out of this command against a frozen, hashed config.
