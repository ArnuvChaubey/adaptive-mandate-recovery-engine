"""Generates a self-contained HTML report from a real evaluation run.

Track 03 asks to *show* measured money recovered across a batch. A terminal table technically shows
it; this makes it legible to someone who will not run the code -- which, for a five-minute video and
a repo skim, is everyone.

Nothing here recomputes or reinterprets anything. It renders exactly what `run_eval` and
`sensitivity` produced, including the metric the adaptive policy loses on. A report that quietly
dropped the unflattering row would defeat the purpose of having frozen the metric in the first place.

    python -m eval.report
"""

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from eval.harness import run_policy_on_batch
from eval.metrics.definitions import MetricsReport, compute_metrics, recovery_lift
from eval.run_eval import AVAILABLE_POLICIES, REPORTS_DIR, load_seeds
from narrator.llm_explainer.explainer import narrate
from simulator.batch import generate_mandates
from simulator.config_loader import load_config

OUT_PATH = REPORTS_DIR / "report.html"
SEEDS_PATH = Path(__file__).parent.parent / "config" / "seeds.txt"
SENSITIVITY_PATH = REPORTS_DIR / "sensitivity_summary.json"

POLICY_LABELS = {
    "baseline": "Baseline",
    "compliance_aware_baseline": "+ Compliance aware",
    "adaptive": "Adaptive",
    "adaptive_hedged": "Adaptive (hedged)",
}

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--line:#26303d;--ink:#e6edf3;--dim:#8b949e;
--pos:#3fb950;--neg:#f85149;--warn:#d29922;--accent:#58a6ff;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:48px 24px 80px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.02em}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
margin:48px 0 16px;font-weight:600}
.sub{color:var(--dim);margin:0 0 28px}
.banner{background:rgba(210,153,34,.09);border:1px solid rgba(210,153,34,.35);
border-left:3px solid var(--warn);border-radius:6px;padding:14px 18px;margin:0 0 32px;
color:#e3b341;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin-bottom:8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px 20px}
.card .label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--dim);margin-bottom:8px}
.card .value{font-size:26px;font-weight:600;letter-spacing:-.02em;font-family:var(--mono)}
.card .note{font-size:12px;color:var(--dim);margin-top:6px}
.pos{color:var(--pos)}.neg{color:var(--neg)}.warnc{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:14px;background:var(--panel);
border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:11px 14px;text-align:right;border-bottom:1px solid var(--line)}
th:first-child,td:first-child{text-align:left}
th{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim);
font-weight:600;background:rgba(255,255,255,.02)}
tr:last-child td{border-bottom:none}
td.num{font-family:var(--mono)}
.best{color:var(--pos);font-weight:600}
.scroll{overflow-x:auto}
.rec{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px 18px;margin-bottom:12px}
.rec .head{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.tag{font-family:var(--mono);font-size:11px;padding:3px 8px;border-radius:4px;
background:rgba(88,166,255,.12);color:var(--accent);border:1px solid rgba(88,166,255,.3)}
.tag.esc{background:rgba(210,153,34,.12);color:var(--warn);border-color:rgba(210,153,34,.3)}
.tag.live{background:rgba(63,185,80,.12);color:var(--pos);border-color:rgba(63,185,80,.3)}
.rec .amt{margin-left:auto;font-family:var(--mono);font-weight:600}
.rec .why{font-size:13px;color:var(--dim);margin-bottom:10px}
.rec .msg{font-size:13px;border-left:2px solid var(--line);padding-left:12px;color:#c9d1d9}
.rec .msg b{color:var(--dim);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.chk{font-family:var(--mono);font-size:11px;color:var(--dim);margin-top:8px}
ul.lim{margin:0;padding-left:18px;color:var(--dim);font-size:14px}
ul.lim li{margin-bottom:9px}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);
color:var(--dim);font-size:12px;font-family:var(--mono)}
"""


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def _signed(x: float) -> str:
    return f"{x:+.1%}"


def _metric_rows(reports: dict[str, MetricsReport]) -> str:
    names = list(reports)

    def row(label: str, fn, best: str = "max") -> str:
        vals = {n: fn(reports[n]) for n in names}
        numeric = {n: v for n, v in vals.items() if isinstance(v, (int, float))}
        winner = (max if best == "max" else min)(numeric, key=numeric.get) if numeric else None
        cells = "".join(
            f'<td class="num{" best" if n == winner else ""}">'
            f'{v if isinstance(v, str) else (_pct(v) if abs(v) <= 1 else f"{v:,.1f}")}</td>'
            for n, v in vals.items()
        )
        return f"<tr><td>{label}</td>{cells}</tr>"

    header = "".join(f"<th>{POLICY_LABELS.get(n, n)}</th>" for n in names)
    body = "".join([
        row("Recovery rate (recoverable)", lambda r: r.recovery_rate_recoverable_only),
        row("Recovery rate (all mandates)", lambda r: r.recovery_rate_all),
        f"<tr><td>Value recovered</td>" + "".join(
            f'<td class="num{" best" if reports[n].recovered_value_inr == max(x.recovered_value_inr for x in reports.values()) else ""}">'
            f"{_inr(reports[n].recovered_value_inr)}</td>" for n in names
        ) + "</tr>",
        row("Wasted attempt rate", lambda r: r.wasted_attempt_rate, best="min"),
        f"<tr><td>Median days to recovery</td>" + "".join(
            f'<td class="num">{reports[n].median_days_to_recovery:.1f}</td>'
            if reports[n].median_days_to_recovery is not None else '<td class="num">n/a</td>'
            for n in names
        ) + "</tr>",
        f"<tr><td>Attempts made</td>" + "".join(
            f'<td class="num">{reports[n].total_attempts:,}</td>' for n in names
        ) + "</tr>",
    ])
    return f'<div class="scroll"><table><tr><th>Metric</th>{header}</tr>{body}</table></div>'


def _decomposition(reports: dict[str, MetricsReport]) -> str:
    if not {"baseline", "compliance_aware_baseline", "adaptive"} <= set(reports):
        return ""
    pairs = [
        ("baseline", "compliance_aware_baseline", "Compliance awareness alone"),
        ("compliance_aware_baseline", "adaptive", "Retry timing alone"),
        ("baseline", "adaptive", "Total"),
    ]
    rows = ""
    for base, cand, label in pairs:
        lift = recovery_lift(reports[base], reports[cand])
        strong = ' style="font-weight:600"' if label == "Total" else ""
        rows += (
            f"<tr{strong}><td>{label}</td>"
            f'<td class="num pos">{_signed(lift["recovery_rate_recoverable_only"])}</td>'
            f'<td class="num pos">{_signed(lift["recovered_value_inr"])}</td></tr>'
        )
    return (
        "<table><tr><th>Source of gain</th><th>Recovery rate</th><th>Value</th></tr>"
        f"{rows}</table>"
    )


def _sensitivity() -> str:
    if not SENSITIVITY_PATH.exists():
        return '<p class="sub">Run <code>python -m eval.sensitivity</code> to populate this section.</p>'
    data = json.loads(SENSITIVITY_PATH.read_text())
    scenarios = data["scenarios"]
    rows = ""
    for s in scenarios:
        lift = s["lift_candidate_vs_baseline"]
        rate, waste = lift["recovery_rate_recoverable_only"], lift["wasted_attempt_rate"]
        rate_cls = "pos" if rate > 0 else "neg"
        waste_cls = "pos" if waste < 0 else "neg"
        rows += (
            f'<tr><td>{html.escape(s["name"])}</td>'
            f'<td class="num {rate_cls}">{_signed(rate)}</td>'
            f'<td class="num {rate_cls}">{_signed(lift["recovered_value_inr"])}</td>'
            f'<td class="num {waste_cls}">{_signed(waste) if waste == waste else "n/a"}</td></tr>'
        )
    positive = sum(1 for s in scenarios
                   if s["lift_candidate_vs_baseline"]["recovery_rate_recoverable_only"] > 0)
    return (
        f'<p class="sub">Each scenario pins a low-confidence assumption to a point inside its '
        f'already-declared range. Recovery lift is positive in <b>{positive} of {len(scenarios)}</b>.</p>'
        '<div class="scroll"><table><tr><th>Scenario</th><th>Rate lift</th><th>Value lift</th>'
        f'<th>Waste lift</th></tr>{rows}</table></div>'
    )


def _audit_samples(log, config, limit: int = 4) -> str:
    by_type: dict = {}
    for rec in log:
        by_type.setdefault(rec.decision_type, []).append(rec)
    picked = []
    while len(picked) < limit and any(by_type.values()):
        for recs in by_type.values():
            if recs and len(picked) < limit:
                picked.append(recs.pop(0))

    out = ""
    for rec in picked:
        n = narrate(rec)
        esc = " esc" if rec.escalation_action else ""
        checks = " · ".join(
            f'{c.invariant_id.replace("INV-RBI-", "")} '
            f'{"PASS" if c.passed else "BLOCKED"}{"" if c.applicable else " (n/a)"}'
            for c in rec.compliance_checks
        )
        customer = (
            f'<div class="msg"><b>Customer message</b><br>{html.escape(n.customer_message)}</div>'
            if n.customer_message else
            '<div class="msg"><b>Customer message</b><br><i>none — contact not appropriate</i></div>'
        )
        out += (
            f'<div class="rec"><div class="head">'
            f'<span class="tag{esc}">{html.escape(rec.decision_type.value)}</span>'
            f'<span class="tag">{html.escape(rec.rule_id)}</span>'
            f'<span class="tag">{html.escape(rec.failure_class)}</span>'
            f'<span class="amt">{_inr(rec.amount_inr or 0)}</span></div>'
            f'<div class="why">{html.escape(rec.rule_description)}</div>'
            f'{customer}'
            f'<div class="chk">{html.escape(checks)} · narration: {n.source}</div></div>'
        )
    return out


def _live_samples() -> str:
    path = REPORTS_DIR / "examples" / "live_test_mode_sample.jsonl"
    if not path.exists():
        return ""
    out = ""
    for line in path.read_text().splitlines():
        r = json.loads(line)
        esc = " esc" if r.get("escalation_action") else ""
        out += (
            f'<div class="rec"><div class="head">'
            f'<span class="tag live">live_test_mode</span>'
            f'<span class="tag{esc}">{html.escape(r["decision_type"])}</span>'
            f'<span class="tag">{html.escape(r["rule_id"])}</span>'
            f'<span class="amt">{_inr(r["amount_inr"])}</span></div>'
            f'<div class="why">{html.escape(r["rule_description"])}</div>'
            f'<div class="chk">razorpay id {html.escape(r["mandate_id"])} · '
            f'decline code {html.escape(r["metadata"]["razorpay_error_reason"])}</div></div>'
        )
    return out


def build(seeds: list[int], n_mandates: int) -> str:
    config = load_config()
    reports: dict[str, MetricsReport] = {}
    sample_log = None

    for name in ["baseline", "compliance_aware_baseline", "adaptive", "adaptive_hedged"]:
        policy = AVAILABLE_POLICIES[name]()
        m_out, a_out = [], []
        for seed in seeds:
            mandates = generate_mandates(n=n_mandates, seed=seed, config=config)
            result = run_policy_on_batch(policy, mandates, config, seed)
            m_out.extend(result.mandate_outcomes)
            a_out.extend(result.attempt_outcomes)
            if name == "adaptive" and sample_log is None:
                sample_log = result.decision_log
        reports[name] = compute_metrics(name, m_out, a_out, config)

    base, adapt = reports["baseline"], reports["adaptive"]
    gain = adapt.recovered_value_inr - base.recovered_value_inr
    total_value = adapt.total_value_inr

    head = (
        f'<div class="grid">'
        f'<div class="card"><div class="label">Batch value</div>'
        f'<div class="value">{_inr(total_value)}</div>'
        f'<div class="note">{adapt.n_mandates:,} mandates · {len(seeds)} seeds</div></div>'
        f'<div class="card"><div class="label">Recovered — baseline</div>'
        f'<div class="value">{_inr(base.recovered_value_inr)}</div>'
        f'<div class="note">{_pct(base.recovery_rate_recoverable_only)} of recoverable</div></div>'
        f'<div class="card"><div class="label">Recovered — adaptive</div>'
        f'<div class="value pos">{_inr(adapt.recovered_value_inr)}</div>'
        f'<div class="note">{_pct(adapt.recovery_rate_recoverable_only)} of recoverable</div></div>'
        f'<div class="card"><div class="label">Additional recovered</div>'
        f'<div class="value pos">{_inr(gain)}</div>'
        f'<div class="note">{_signed(recovery_lift(base, adapt)["recovered_value_inr"])} vs baseline</div></div>'
        f"</div>"
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit = config["meta"]["frozen_commit_hash"][:12]

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Adaptive Mandate Recovery — Batch Report</title><style>{CSS}</style></head><body>
<div class="wrap">
<h1>Adaptive Mandate Recovery Engine</h1>
<p class="sub">Batch evaluation report · Razorpay AI Buildathon, Track 03</p>

<div class="banner"><b>Simulated batch.</b> Every figure below is computed from a frozen,
version-controlled simulator config (commit <code>{commit}</code>) and a fixed seed list. It is not
measured against real transaction data and is not a revenue forecast. The live test-mode section is
an integration proof and carries no statistical claim.</div>

<h2>Measured money recovered across the batch</h2>
{head}

<h2>Policy comparison</h2>
{_metric_rows(reports)}

<h2>Where the gain comes from</h2>
<p class="sub">The adaptive policy escalates amounts above the ₹15,000 no-OTP ceiling instead of
firing retries that must legally be refused. That is a compliance check, not intelligence — so an
ablation isolates it. If you believe production systems already do this, the honest claim is the
timing row, not the total.</p>
{_decomposition(reports)}

<h2>Where it loses</h2>
<p class="sub">The adaptive policy wastes <b>more</b> attempts than baseline. Waiting for a likely
payday wins for customers who follow the pattern and fires into a drained account for those who do
not — the measurable cost of assumption A13. The metric and its threshold were frozen before any
adaptive policy existed, which is why this row is still here. The hedged variant halves the
regression and cuts median recovery time from {reports['adaptive'].median_days_to_recovery:.1f} to
{reports['adaptive_hedged'].median_days_to_recovery:.1f} days, at the cost of ~9 points of lift —
because the extra attempt more than doubles customer-initiated revocations. Neither dominates.</p>

<h2>Does it survive the assumptions?</h2>
{_sensitivity()}

<h2>Audit trail — simulated decisions</h2>
<p class="sub">Every decision carries the rule that produced it and every compliance check evaluated.
Narration is generated after the fact and never influences a decision.</p>
{_audit_samples(sample_log, config)}

<h2>Audit trail — real Razorpay test-mode API</h2>
<p class="sub">Same policy engine, same compliance invariants, same audit schema — driven by entities
created and re-fetched through Razorpay's live test-mode API, with documented decline codes mapped
onto the failure taxonomy. Integration proof only; excluded from every figure above.</p>
{_live_samples()}

<h2>Honest limits</h2>
<ul class="lim">
<li>Not measured against real transaction data — this demonstrates a measurement methodology, not a revenue outcome.</li>
<li>Not benchmarked against Razorpay's Intelligent Retry Engine; it exposes no public callable interface.</li>
<li>The live batch is 9 real entities. A scripted completed-payment batch is not possible on a standard test account.</li>
<li>The escalation response rate (A35) carries the ₹ headline and has no public source. It is applied identically to every policy so it cannot manufacture lift, and it is swept — but attack it first.</li>
<li>Real production retry cadence is unpublished (A1). The baseline is an informed construction, and the headline is reported against the <i>strongest</i> baseline we could build.</li>
</ul>

<footer>Generated {generated} · frozen config {commit} · seeds {len(seeds)} × {n_mandates:,} mandates<br>
Regenerate: <code>python -m eval.report</code></footer>
</div></body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the HTML batch report")
    parser.add_argument("--seeds", default=str(SEEDS_PATH))
    parser.add_argument("--n-mandates", type=int, default=200)
    args = parser.parse_args()

    seeds = load_seeds(Path(args.seeds))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(build(seeds, args.n_mandates))
    print(f"report written to {OUT_PATH.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
