"""Pareto frontier visualisations, rendered as plain SVG -- no charting library, self-contained.

Two charts, two different jobs, chosen deliberately rather than forcing one chart to do both:

**Scatter (recovery vs. waste).** Five policies is five dots -- not enough points to show a frontier
*shape*, only which points dominate which. The real data source is the sensitivity sweep: 19
scenarios x 5 policies = 95 points, each a real run under a different plausible parameterisation.
Plotted as a cloud coloured by policy, the boundary a policy actually occupies becomes visible instead
of asserted. Two axes only (recovery, waste) because a scatter that encodes four dimensions via color
AND size AND shape stops being "immediately visible" and starts being a legend exercise.

**Radar (four axes at once).** The thing a scatter can't show cleanly: "no policy wins everywhere."
Four axes -- recovery, waste, revocations, speed -- normalised per-axis across the five policies shown
(1 = best of this set, 0 = worst), oriented so further outward is always better. One snapshot
(frozen_defaults), not swept, because the point is legibility, not another sweep.

**The oracle is drawn differently on purpose.** It is not a competing candidate and must never look
like one -- a distinct colour and an explicit "(ceiling)" label on every legend entry it appears in,
everywhere this module renders it.
"""

import math

POLICY_COLORS = {
    "baseline": "#f85149",
    "compliance_aware_baseline": "#d29922",
    "adaptive": "#58a6ff",
    "adaptive_hedged": "#3fb950",
    "oracle": "#a371f7",
}
POLICY_LABELS = {
    "baseline": "Baseline",
    "compliance_aware_baseline": "+ Compliance",
    "adaptive": "Adaptive",
    "adaptive_hedged": "Hedged",
    "oracle": "Oracle (ceiling, not deployable)",
}
# Draw order: real candidates first, oracle last so its marker sits on top as a visible reference
# line rather than getting buried under the cloud it's supposed to bound.
POLICY_ORDER = ["baseline", "compliance_aware_baseline", "adaptive", "adaptive_hedged", "oracle"]


def _svg_legend(y: int, policies: list[str]) -> str:
    """Legend rendered as SVG elements, positioned inside a chart's own viewBox."""
    x = 16
    items = ""
    for name in policies:
        color = POLICY_COLORS.get(name, "#8b949e")
        label = POLICY_LABELS.get(name, name)
        items += (
            f'<circle cx="{x + 5}" cy="{y}" r="5" fill="{color}" fill-opacity="0.85"/>'
            f'<text x="{x + 16}" y="{y + 4}" font-size="11" fill="#c9d1d9">{label}</text>'
        )
        x += 20 + len(label) * 6.2
    return items


def _html_legend(policies: list[str]) -> str:
    """Legend rendered as plain HTML, for placement below a chart rather than inside its SVG."""
    items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
        f'<span style="width:10px;height:10px;border-radius:50%;background:'
        f'{POLICY_COLORS.get(p, "#8b949e")};display:inline-block"></span>'
        f'<span style="font-size:12px;color:#c9d1d9">{POLICY_LABELS.get(p, p)}</span></span>'
        for p in policies
    )
    return f'<div style="margin-top:8px;display:flex;flex-wrap:wrap">{items}</div>'


def scatter_svg(sensitivity_summary: dict, width: int = 760, height: int = 440) -> str:
    scenarios = sensitivity_summary.get("scenarios", [])
    points: list[tuple[float, float, str, str]] = []  # (waste, recovery, policy, scenario_name)
    for s in scenarios:
        for policy_name, report in s.get("reports", {}).items():
            points.append((
                report["wasted_attempt_rate"],
                report["recovery_rate_recoverable_only"],
                policy_name,
                s["name"],
            ))
    if not points:
        return '<p class="sub">No sensitivity data -- run <code>python -m eval.sensitivity</code> first.</p>'

    margin = {"top": 20, "right": 24, "bottom": 46, "left": 56}
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]

    x_max = max(p[0] for p in points) * 1.12 or 0.01
    y_vals = [p[1] for p in points]
    y_min, y_max = min(y_vals) * 0.94, min(1.0, max(y_vals) * 1.03)

    def px(waste: float) -> float:
        return margin["left"] + (waste / x_max) * plot_w

    def py(recovery: float) -> float:
        return margin["top"] + (1 - (recovery - y_min) / (y_max - y_min)) * plot_h

    # Gridlines + axis labels, y as recovery %, x as waste %.
    grid = ""
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        gy = margin["top"] + frac * plot_h
        val = y_max - frac * (y_max - y_min)
        grid += (
            f'<line x1="{margin["left"]}" y1="{gy:.1f}" x2="{width - margin["right"]}" y2="{gy:.1f}" '
            f'stroke="#26303d" stroke-width="1"/>'
            f'<text x="{margin["left"] - 8}" y="{gy + 4:.1f}" font-size="10" fill="#8b949e" '
            f'text-anchor="end">{val:.0%}</text>'
        )
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        gx = margin["left"] + frac * plot_w
        val = frac * x_max
        grid += (
            f'<text x="{gx:.1f}" y="{height - margin["bottom"] + 16}" font-size="10" fill="#8b949e" '
            f'text-anchor="middle">{val:.1%}</text>'
        )

    dots = ""
    for waste, recovery, policy_name, scenario_name in points:
        color = POLICY_COLORS.get(policy_name, "#8b949e")
        is_oracle = policy_name == "oracle"
        r = 5 if is_oracle else 4
        opacity = 0.95 if is_oracle else 0.55
        dots += (
            f'<circle cx="{px(waste):.1f}" cy="{py(recovery):.1f}" r="{r}" fill="{color}" '
            f'fill-opacity="{opacity}" stroke="{"#0d1117" if is_oracle else "none"}" '
            f'stroke-width="{1 if is_oracle else 0}">'
            f'<title>{POLICY_LABELS.get(policy_name, policy_name)} -- {scenario_name}\n'
            f'recovery {recovery:.1%}, waste {waste:.1%}</title></circle>'
        )

    return f"""<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">
  {grid}
  <line x1="{margin['left']}" y1="{margin['top']}" x2="{margin['left']}" y2="{height - margin['bottom']}" stroke="#8b949e"/>
  <line x1="{margin['left']}" y1="{height - margin['bottom']}" x2="{width - margin['right']}" y2="{height - margin['bottom']}" stroke="#8b949e"/>
  {dots}
  <text x="{margin['left'] + plot_w / 2:.0f}" y="{height - 6}" font-size="11" fill="#8b949e" text-anchor="middle">wasted attempt rate  -&gt;  worse</text>
  <text x="14" y="{margin['top'] + plot_h / 2:.0f}" font-size="11" fill="#8b949e" text-anchor="middle" transform="rotate(-90 14 {margin['top'] + plot_h / 2:.0f})">recovery rate  -&gt;  better</text>
  {_svg_legend(height - 4, POLICY_ORDER)}
</svg>"""


def radar_svg(frozen_defaults_reports: dict, width: int = 420, height: int = 420) -> str:
    axes = [
        ("Recovery", "recovery_rate_recoverable_only", False),
        ("Low waste", "wasted_attempt_rate", True),
        ("Low revocations", "revocation_rate", True),
        ("Speed", "median_days_to_recovery", True),
    ]
    policies = [p for p in POLICY_ORDER if p in frozen_defaults_reports]

    # Per-axis min-max normalisation across exactly this set of policies, oriented so 1 = best,
    # 0 = worst, further outward always better -- a relative comparison within this chart, not
    # against an absolute scale.
    normalized: dict[str, dict[str, float]] = {p: {} for p in policies}
    for label, field, invert in axes:
        raw = {p: (frozen_defaults_reports[p].get(field) or 0.0) for p in policies}
        lo, hi = min(raw.values()), max(raw.values())
        for p in policies:
            if hi == lo:
                normalized[p][label] = 1.0
            else:
                frac = (raw[p] - lo) / (hi - lo)
                normalized[p][label] = (1 - frac) if invert else frac

    cx, cy = width / 2, height / 2 - 6
    R = min(width, height) / 2 - 64
    n = len(axes)
    angle = lambda i: -math.pi / 2 + i * (2 * math.pi / n)

    rings = ""
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = " ".join(
            f"{cx + math.cos(angle(i)) * R * frac:.1f},{cy + math.sin(angle(i)) * R * frac:.1f}"
            for i in range(n)
        )
        rings += f'<polygon points="{pts}" fill="none" stroke="#26303d" stroke-width="1"/>'

    axis_lines, axis_labels = "", ""
    for i, (label, _, _) in enumerate(axes):
        ax, ay = cx + math.cos(angle(i)) * R, cy + math.sin(angle(i)) * R
        axis_lines += f'<line x1="{cx}" y1="{cy}" x2="{ax:.1f}" y2="{ay:.1f}" stroke="#26303d"/>'
        lx, ly = cx + math.cos(angle(i)) * (R + 20), cy + math.sin(angle(i)) * (R + 20)
        anchor = "middle" if abs(math.cos(angle(i))) < 0.3 else ("start" if math.cos(angle(i)) > 0 else "end")
        axis_labels += (
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" fill="#8b949e" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{label}</text>'
        )

    polygons = ""
    for p in policies:
        pts = " ".join(
            f"{cx + math.cos(angle(i)) * R * normalized[p][axes[i][0]]:.1f},"
            f"{cy + math.sin(angle(i)) * R * normalized[p][axes[i][0]]:.1f}"
            for i in range(n)
        )
        color = POLICY_COLORS.get(p, "#8b949e")
        is_oracle = p == "oracle"
        polygons += (
            f'<polygon points="{pts}" fill="{color}" fill-opacity="{0.05 if is_oracle else 0.12}" '
            f'stroke="{color}" stroke-width="{2.5 if is_oracle else 2}" '
            f'stroke-dasharray="{"4,3" if is_oracle else "none"}"/>'
        )

    return f"""<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px">
  {rings}{axis_lines}{polygons}{axis_labels}
</svg>
{_html_legend(policies)}"""
