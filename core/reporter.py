"""
Report generation for AI Evals Framework.

Produces daily, weekly, and PR-level markdown reports plus a self-contained
HTML dashboard with inline SVG sparklines.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev

from core.config import load_config
from core.eval_engine import EvalResult

# ---------------------------------------------------------------------------
# Traffic light helpers
# ---------------------------------------------------------------------------

TRAFFIC_LIGHT = {(0.8, 1.01): "GREEN", (0.6, 0.8): "YELLOW", (0.0, 0.6): "RED"}

TRAFFIC_LIGHT_EMOJI = {"GREEN": "GREEN", "YELLOW": "YELLOW", "RED": "RED"}


def traffic_light(score: float) -> str:
    """Map a 0-1 score to a traffic-light label."""
    for (lo, hi), color in TRAFFIC_LIGHT.items():
        if lo <= score < hi:
            return color
    return "RED"


# ---------------------------------------------------------------------------
# Result loading helpers
# ---------------------------------------------------------------------------


def _load_results_for_date(date: str, config: dict) -> list[EvalResult]:
    results_dir = Path(config["results_dir"]).expanduser()
    results_file = results_dir / f"{date}.jsonl"

    if not results_file.exists():
        return []

    results: list[EvalResult] = []
    with open(results_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                results.append(EvalResult(**data))
            except (json.JSONDecodeError, TypeError):
                continue
    return results


def _load_results_range(start_date: str, end_date: str, config: dict) -> list[EvalResult]:
    """Load all results between start_date and end_date inclusive."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    all_results: list[EvalResult] = []
    current = start
    while current <= end:
        day_str = current.strftime("%Y-%m-%d")
        all_results.extend(_load_results_for_date(day_str, config))
        current += timedelta(days=1)
    return all_results


def _category_averages(results: list[EvalResult]) -> dict[str, dict]:
    """Group results by category. Returns {category: {avg, count, scores}}."""
    by_cat: dict[str, list[float]] = {}
    for r in results:
        if r.error is None:
            by_cat.setdefault(r.category, []).append(r.overall_score)

    out = {}
    for cat, scores in sorted(by_cat.items()):
        out[cat] = {
            "avg": round(mean(scores), 3),
            "count": len(scores),
            "scores": scores,
        }
    return out


def _skill_averages(results: list[EvalResult]) -> dict[str, dict]:
    """Group results by skill. Returns {skill: {avg, count}}."""
    by_skill: dict[str, list[float]] = {}
    for r in results:
        if r.error is None:
            by_skill.setdefault(r.skill, []).append(r.overall_score)

    out = {}
    for skill, scores in sorted(by_skill.items()):
        out[skill] = {
            "avg": round(mean(scores), 3),
            "count": len(scores),
        }
    return out


# ---------------------------------------------------------------------------
# Daily report
# ---------------------------------------------------------------------------


def generate_daily_report(date: str, results_dir: str | None = None) -> str:
    """Generate markdown report for a single day.

    Load JSONL for the date, compute category averages, identify best/worst.
    """
    config = load_config()
    if results_dir:
        config["results_dir"] = results_dir

    results = _load_results_for_date(date, config)

    lines: list[str] = []
    lines.append(f"# AI Evals Report -- {date}")
    lines.append("")

    if not results:
        lines.append("*No eval results for this date.*")
        return "\n".join(lines)

    scored = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]
    regressions = [r for r in scored if r.regression]

    overall_avg = round(mean(r.overall_score for r in scored), 3) if scored else 0.0
    status = traffic_light(overall_avg)

    lines.append("## Health Summary")
    lines.append("")
    lines.append(f"**APQS: {overall_avg}** ({status}) -- {len(scored)} evals, {len(regressions)} regressions")
    lines.append("")

    # Category breakdown
    cat_avgs = _category_averages(scored)
    if cat_avgs:
        lines.append("| Category | Evals | Avg Score | Status |")
        lines.append("|----------|-------|-----------|--------|")
        for cat, info in cat_avgs.items():
            tl = traffic_light(info["avg"])
            lines.append(f"| {cat} | {info['count']} | {info['avg']:.2f} | {tl} |")
        lines.append("")

    # Highlight reel
    if scored:
        sorted_scored = sorted(scored, key=lambda r: r.overall_score)
        best = sorted_scored[-1]
        worst = sorted_scored[0]
        lines.append("## Highlight Reel")
        lines.append("")
        lines.append(f"**Best**: {best.input_summary or best.eval_name} scored {best.overall_score:.2f} on {best.skill}")
        lines.append(f"**Worst**: {worst.input_summary or worst.eval_name} scored {worst.overall_score:.2f} on {worst.skill}")
        lines.append("")

    # Regressions — aggregate by skill
    if regressions:
        lines.append("## Regressions")
        lines.append("")
        reg_by_skill: dict[str, list[float]] = {}
        for r in regressions:
            reg_by_skill.setdefault(r.skill, []).append(r.overall_score)
        lines.append("| Skill | Count | Avg Score | Worst |")
        lines.append("|-------|-------|-----------|-------|")
        for skill in sorted(reg_by_skill, key=lambda s: mean(reg_by_skill[s])):
            scores = reg_by_skill[skill]
            lines.append(f"| {skill} | {len(scores)} | {mean(scores):.2f} | {min(scores):.2f} |")
        lines.append("")

    # Skill usage
    skill_avgs = _skill_averages(scored)
    if skill_avgs:
        lines.append("## Skill Usage")
        lines.append("")
        lines.append("| Skill | Uses | Avg Score |")
        lines.append("|-------|------|-----------|")
        for skill, info in skill_avgs.items():
            lines.append(f"| {skill} | {info['count']} | {info['avg']:.2f} |")
        lines.append("")

    # Errors
    if errors:
        lines.append("## Errors")
        lines.append("")
        for r in errors:
            lines.append(f"- {r.eval_name}: {r.error}")
        lines.append("")

    lines.append(f"*Generated {datetime.now(timezone.utc).isoformat()}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Weekly report
# ---------------------------------------------------------------------------


def generate_weekly_report(end_date: str, results_dir: str | None = None) -> str:
    """Generate weekly rollup. 7 daily reports aggregated.

    Includes APQS trend (7 daily scores), regression alerts, improvements.
    """
    config = load_config()
    if results_dir:
        config["results_dir"] = results_dir

    end = datetime.strptime(end_date, "%Y-%m-%d")
    start = end - timedelta(days=6)

    lines: list[str] = []
    lines.append(f"# Weekly AI Quality Report -- Week of {start.strftime('%Y-%m-%d')}")
    lines.append("")

    # Collect daily APQS values
    daily_data: list[dict] = []
    all_results: list[EvalResult] = []

    for i in range(7):
        day = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        day_results = _load_results_for_date(day, config)
        all_results.extend(day_results)

        scored = [r for r in day_results if r.error is None]
        if scored:
            day_avg = round(mean(r.overall_score for r in scored), 2)
            daily_data.append({"date": day, "apqs": day_avg, "count": len(scored)})

    if not daily_data:
        lines.append("*No eval results for this week.*")
        return "\n".join(lines)

    # Previous week for comparison
    prev_start = start - timedelta(days=7)
    prev_end = start - timedelta(days=1)
    prev_results = _load_results_range(
        prev_start.strftime("%Y-%m-%d"),
        prev_end.strftime("%Y-%m-%d"),
        config,
    )
    prev_scored = [r for r in prev_results if r.error is None]
    prev_avg = round(mean(r.overall_score for r in prev_scored), 2) if prev_scored else None

    # APQS trend
    lines.append("## APQS Trend")
    lines.append("")
    trend_parts = []
    for d in daily_data:
        day_name = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a")
        trend_parts.append(f"{day_name}: {d['apqs']:.2f}")
    lines.append(" | ".join(trend_parts))

    week_avg = round(mean(d["apqs"] for d in daily_data), 2)
    if prev_avg and prev_avg > 0:
        change_pct = round(((week_avg - prev_avg) / prev_avg) * 100, 1)
        sign = "+" if change_pct >= 0 else ""
        lines.append(f"Weekly: {week_avg:.2f} (prev week: {prev_avg:.2f}, {sign}{change_pct}%)")
    else:
        lines.append(f"Weekly: {week_avg:.2f}")
    lines.append("")

    # Category breakdown
    scored_all = [r for r in all_results if r.error is None]
    cat_avgs = _category_averages(scored_all)
    if cat_avgs:
        lines.append("## Category Breakdown")
        lines.append("")
        lines.append("| Category | Evals | Avg Score | Status |")
        lines.append("|----------|-------|-----------|--------|")
        for cat, info in cat_avgs.items():
            tl = traffic_light(info["avg"])
            lines.append(f"| {cat} | {info['count']} | {info['avg']:.2f} | {tl} |")
        lines.append("")

    # Regressions — aggregate by skill instead of listing each eval
    regressions = [r for r in scored_all if r.regression]
    lines.append("## Regressions This Week")
    lines.append("")
    if regressions:
        reg_by_skill: dict[str, list] = {}
        for r in regressions:
            reg_by_skill.setdefault(r.skill, []).append(r.overall_score)
        lines.append("| Skill | Count | Avg Score | Worst |")
        lines.append("|-------|-------|-----------|-------|")
        for skill in sorted(reg_by_skill, key=lambda s: mean(reg_by_skill[s])):
            scores = reg_by_skill[skill]
            lines.append(f"| {skill} | {len(scores)} | {mean(scores):.2f} | {min(scores):.2f} |")
    else:
        lines.append("No regressions detected.")
    lines.append("")

    # Improvements — aggregate by skill instead of listing each eval
    improvements = [r for r in scored_all if r.overall_score > 0.9 and not r.regression]
    lines.append("## Improvements This Week")
    lines.append("")
    if improvements:
        imp_by_skill: dict[str, list] = {}
        for r in improvements:
            imp_by_skill.setdefault(r.skill, []).append(r.overall_score)
        lines.append("| Skill | Count | Avg Score |")
        lines.append("|-------|-------|-----------|")
        for skill in sorted(imp_by_skill, key=lambda s: -mean(imp_by_skill[s])):
            scores = imp_by_skill[skill]
            lines.append(f"| {skill} | {len(scores)} | {mean(scores):.2f} |")
    else:
        lines.append("No standout improvements (>0.9) this week.")
    lines.append("")

    lines.append(f"*{len(scored_all)} evals across {len(daily_data)} days with data*")
    lines.append("")
    lines.append(f"*Generated {datetime.now(timezone.utc).isoformat()}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PR report
# ---------------------------------------------------------------------------


def generate_pr_report(commit_sha: str, results: list[EvalResult]) -> str:
    """Generate PR-level eval report."""
    short_sha = commit_sha[:7] if len(commit_sha) >= 7 else commit_sha

    lines: list[str] = []
    lines.append(f"# PR Eval: {short_sha}")
    lines.append("")

    if not results:
        lines.append("*No artifacts evaluated in this PR.*")
        return "\n".join(lines)

    scored = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]

    if scored:
        overall = round(mean(r.overall_score for r in scored), 3)
        status = traffic_light(overall)
        regressions = sum(1 for r in scored if r.regression)
        lines.append(f"**Score: {overall}** ({status}) -- {len(scored)} artifacts, {regressions} regressions")
        lines.append("")

    lines.append("| Artifact | Category | Score | Status |")
    lines.append("|----------|----------|-------|--------|")

    for r in sorted(results, key=lambda x: x.overall_score):
        if r.error:
            lines.append(f"| {r.input_summary or r.eval_name} | {r.category} | ERROR | RED |")
        else:
            tl = traffic_light(r.overall_score)
            lines.append(f"| {r.input_summary or r.eval_name} | {r.category} | {r.overall_score:.2f} | {tl} |")

    lines.append("")

    if errors:
        lines.append("## Errors")
        lines.append("")
        for r in errors:
            lines.append(f"- {r.eval_name}: {r.error}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML dashboard
# ---------------------------------------------------------------------------

_DASHBOARD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Evals Dashboard</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: #121212;
    color: #FFFFFF;
    padding: 24px;
    line-height: 1.5;
  }}
  h1 {{
    font-size: 28px;
    font-weight: 700;
    margin-bottom: 4px;
  }}
  .subtitle {{
    color: #B3B3B3;
    font-size: 14px;
    margin-bottom: 32px;
  }}
  .grid {{
    display: grid;
    grid-template-columns: 280px 1fr;
    gap: 24px;
    margin-bottom: 32px;
  }}
  .card {{
    background: #1E1E1E;
    border-radius: 12px;
    padding: 24px;
  }}
  .apqs-card {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }}
  .apqs-label {{
    font-size: 13px;
    color: #B3B3B3;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
  }}
  .apqs-score {{
    font-size: 72px;
    font-weight: 700;
    line-height: 1;
  }}
  .apqs-status {{
    font-size: 16px;
    font-weight: 600;
    margin-top: 8px;
    padding: 4px 16px;
    border-radius: 20px;
  }}
  .status-GREEN {{ color: #1DB954; background: rgba(29,185,84,0.15); }}
  .status-YELLOW {{ color: #F5A623; background: rgba(245,166,35,0.15); }}
  .status-RED {{ color: #E3524F; background: rgba(227,82,79,0.15); }}
  .color-GREEN {{ color: #1DB954; }}
  .color-YELLOW {{ color: #F5A623; }}
  .color-RED {{ color: #E3524F; }}
  .sparkline-card {{
    display: flex;
    flex-direction: column;
  }}
  .sparkline-card h2 {{
    font-size: 16px;
    font-weight: 600;
    margin-bottom: 16px;
  }}
  .sparkline-container {{
    flex: 1;
    display: flex;
    align-items: center;
  }}
  svg.sparkline {{
    width: 100%;
    height: 120px;
  }}
  .categories {{
    margin-bottom: 32px;
  }}
  .categories h2 {{
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 16px;
  }}
  .cat-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 12px;
  }}
  .cat-item {{
    background: #1E1E1E;
    border-radius: 8px;
    padding: 16px;
  }}
  .cat-name {{
    font-size: 13px;
    color: #B3B3B3;
    margin-bottom: 8px;
  }}
  .cat-bar-track {{
    height: 8px;
    background: #333;
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 8px;
  }}
  .cat-bar-fill {{
    height: 100%;
    border-radius: 4px;
    transition: width 0.3s;
  }}
  .cat-score {{
    font-size: 24px;
    font-weight: 700;
  }}
  .cat-count {{
    font-size: 12px;
    color: #B3B3B3;
    float: right;
    margin-top: 8px;
  }}
  .recent {{
    margin-bottom: 32px;
  }}
  .recent h2 {{
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 16px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
  }}
  th {{
    text-align: left;
    font-size: 12px;
    color: #B3B3B3;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 12px;
    border-bottom: 1px solid #333;
  }}
  td {{
    padding: 10px 12px;
    font-size: 14px;
    border-bottom: 1px solid #1E1E1E;
  }}
  tr:hover td {{
    background: #1E1E1E;
  }}
  .alerts {{
    margin-bottom: 32px;
  }}
  .alerts h2 {{
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 16px;
  }}
  .alert-item {{
    background: rgba(227,82,79,0.1);
    border-left: 3px solid #E3524F;
    border-radius: 0 8px 8px 0;
    padding: 12px 16px;
    margin-bottom: 8px;
    font-size: 14px;
  }}
  .alert-item.warning {{
    background: rgba(245,166,35,0.1);
    border-left-color: #F5A623;
  }}
  .footer {{
    text-align: center;
    color: #666;
    font-size: 12px;
    padding-top: 16px;
    border-top: 1px solid #1E1E1E;
  }}
</style>
</head>
<body>
<h1>AI Evals Dashboard</h1>
<p class="subtitle">Generated {generated_at}</p>

<div class="grid">
  <div class="card apqs-card">
    <div class="apqs-label">APQS Composite</div>
    <div class="apqs-score color-{apqs_status}">{apqs_score}</div>
    <div class="apqs-status status-{apqs_status}">{apqs_status}</div>
  </div>
  <div class="card sparkline-card">
    <h2>30-Day Trend</h2>
    <div class="sparkline-container">
      {sparkline_svg}
    </div>
  </div>
</div>

<div class="categories">
  <h2>Category Breakdown</h2>
  <div class="cat-grid">
    {category_cards}
  </div>
</div>

{alerts_section}

<div class="recent">
  <h2>Recent Evaluations</h2>
  <table>
    <thead>
      <tr><th>Date</th><th>Skill</th><th>Eval</th><th>Score</th><th>Status</th></tr>
    </thead>
    <tbody>
      {recent_rows}
    </tbody>
  </table>
</div>

<div class="footer">
  AI Evals Framework v1.0.0 -- {total_evals} evals across {days_with_data} days
</div>
</body>
</html>
"""


def _build_sparkline_svg(daily_scores: list[dict]) -> str:
    """Build an inline SVG sparkline from daily APQS values."""
    if not daily_scores:
        return '<svg class="sparkline" viewBox="0 0 600 120"><text x="300" y="60" text-anchor="middle" fill="#666" font-size="14">No data</text></svg>'

    width = 600
    height = 120
    padding = 10
    plot_w = width - 2 * padding
    plot_h = height - 2 * padding

    scores = [d["apqs"] for d in daily_scores]
    n = len(scores)

    if n == 1:
        # Single point
        y = padding + plot_h * (1 - scores[0])
        return (
            f'<svg class="sparkline" viewBox="0 0 {width} {height}">'
            f'<circle cx="{width // 2}" cy="{y:.0f}" r="4" fill="#1DB954"/>'
            f'</svg>'
        )

    # Build polyline points
    points = []
    for i, s in enumerate(scores):
        x = padding + (i / (n - 1)) * plot_w
        y = padding + plot_h * (1 - s)  # 1.0 is top, 0.0 is bottom
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)

    # Build gradient fill area (polyline closed to bottom)
    area_points = polyline + f" {padding + plot_w:.1f},{padding + plot_h:.1f} {padding:.1f},{padding + plot_h:.1f}"

    # Grid lines at 0.6 and 0.8
    y_06 = padding + plot_h * (1 - 0.6)
    y_08 = padding + plot_h * (1 - 0.8)

    svg = (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}">'
        f'<defs><linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#1DB954" stop-opacity="0.3"/>'
        f'<stop offset="100%" stop-color="#1DB954" stop-opacity="0.02"/>'
        f'</linearGradient></defs>'
        f'<line x1="{padding}" y1="{y_08:.0f}" x2="{padding + plot_w}" y2="{y_08:.0f}" stroke="#333" stroke-width="1" stroke-dasharray="4,4"/>'
        f'<text x="{padding + plot_w + 4}" y="{y_08 + 4:.0f}" fill="#666" font-size="10">0.8</text>'
        f'<line x1="{padding}" y1="{y_06:.0f}" x2="{padding + plot_w}" y2="{y_06:.0f}" stroke="#333" stroke-width="1" stroke-dasharray="4,4"/>'
        f'<text x="{padding + plot_w + 4}" y="{y_06 + 4:.0f}" fill="#666" font-size="10">0.6</text>'
        f'<polygon points="{area_points}" fill="url(#grad)"/>'
        f'<polyline points="{polyline}" fill="none" stroke="#1DB954" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    )

    # End dot
    last_x = padding + ((n - 1) / (n - 1)) * plot_w
    last_y = padding + plot_h * (1 - scores[-1])
    svg += f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" fill="#1DB954"/>'

    svg += '</svg>'
    return svg


def _build_category_card(name: str, avg: float, count: int) -> str:
    """Build HTML for a single category card."""
    tl = traffic_light(avg)
    color_map = {"GREEN": "#1DB954", "YELLOW": "#F5A623", "RED": "#E3524F"}
    fill_color = color_map.get(tl, "#E3524F")
    bar_width = max(int(avg * 100), 2)

    return (
        f'<div class="cat-item">'
        f'<div class="cat-name">{name}</div>'
        f'<div class="cat-bar-track"><div class="cat-bar-fill" style="width:{bar_width}%;background:{fill_color};"></div></div>'
        f'<span class="cat-score color-{tl}">{avg:.2f}</span>'
        f'<span class="cat-count">{count} evals</span>'
        f'</div>'
    )


def generate_dashboard_html(results_dir: str | None = None, output_path: str | None = None) -> str:
    """Generate a self-contained HTML dashboard.

    Features:
    - APQS composite score (large number with traffic light color)
    - Category breakdown bars
    - 30-day sparkline trend (inline SVG)
    - Recent eval list
    - Regression alerts

    Uses inline CSS, no external dependencies. Dark theme with Spotify green.
    Returns the HTML string and optionally writes to output_path.
    """
    config = load_config()
    if results_dir:
        config["results_dir"] = results_dir

    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # Load 30 days of results
    all_results: list[EvalResult] = []
    daily_scores: list[dict] = []
    days_with_data = 0

    for i in range(30):
        day = (now - timedelta(days=29 - i)).strftime("%Y-%m-%d")
        day_results = _load_results_for_date(day, config)
        all_results.extend(day_results)

        scored = [r for r in day_results if r.error is None]
        if scored:
            day_avg = round(mean(r.overall_score for r in scored), 3)
            daily_scores.append({"date": day, "apqs": day_avg, "count": len(scored)})
            days_with_data += 1

    scored_all = [r for r in all_results if r.error is None]

    # APQS composite
    if scored_all:
        weights = config.get("scoring_weights", {})
        category_map = {
            "structured_doc": "structured_docs",
            "open_reasoning": "reasoning",
            "data_analysis": "data_analytics",
            "code_technical": "code_technical",
            "search_retrieval": "search_retrieval",
            "pipeline": "pipelines",
            "mcp_reliability": "mcp_reliability",
        }
        by_cat: dict[str, list[float]] = {}
        for r in scored_all:
            by_cat.setdefault(r.category, []).append(r.overall_score)

        apqs = 0.0
        total_weight = 0.0
        for cat, scores in by_cat.items():
            w_key = category_map.get(cat, cat)
            w = weights.get(w_key, 0.1)
            apqs += w * mean(scores)
            total_weight += w
        apqs = round(apqs / total_weight, 2) if total_weight > 0 else 0.0
    else:
        apqs = 0.0

    apqs_status = traffic_light(apqs)

    # Category cards
    cat_avgs = _category_averages(scored_all)
    category_cards = "\n    ".join(
        _build_category_card(cat, info["avg"], info["count"])
        for cat, info in cat_avgs.items()
    ) if cat_avgs else '<div class="cat-item"><div class="cat-name">No data yet</div></div>'

    # Sparkline
    sparkline_svg = _build_sparkline_svg(daily_scores)

    # Regression alerts
    regressions = [r for r in scored_all if r.regression]
    if regressions:
        alert_items = "\n    ".join(
            f'<div class="alert-item">'
            f'<strong>{r.skill}</strong> / {r.eval_name}: {r.overall_score:.2f} '
            f'({r.timestamp[:10]})</div>'
            for r in regressions[-10:]  # Last 10
        )
        alerts_section = (
            f'<div class="alerts">\n'
            f'  <h2>Regression Alerts ({len(regressions)})</h2>\n'
            f'  {alert_items}\n'
            f'</div>'
        )
    else:
        alerts_section = ""

    # Recent evals (last 20)
    recent = sorted(scored_all, key=lambda r: r.timestamp, reverse=True)[:20]
    if recent:
        recent_rows = "\n      ".join(
            f'<tr>'
            f'<td>{r.timestamp[:10]}</td>'
            f'<td>{r.skill}</td>'
            f'<td>{r.eval_name}</td>'
            f'<td class="color-{traffic_light(r.overall_score)}">{r.overall_score:.2f}</td>'
            f'<td class="color-{traffic_light(r.overall_score)}">{traffic_light(r.overall_score)}</td>'
            f'</tr>'
            for r in recent
        )
    else:
        recent_rows = '<tr><td colspan="5" style="color:#666;text-align:center;">No evaluations yet</td></tr>'

    html = _DASHBOARD_TEMPLATE.format(
        generated_at=now.strftime("%Y-%m-%d %H:%M UTC"),
        apqs_score=f"{apqs:.2f}",
        apqs_status=apqs_status,
        sparkline_svg=sparkline_svg,
        category_cards=category_cards,
        alerts_section=alerts_section,
        recent_rows=recent_rows,
        total_evals=len(scored_all),
        days_with_data=days_with_data,
    )

    if output_path:
        out = Path(output_path).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
    else:
        # Default to reports dir
        reports_dir = Path(config.get("reports_dir", "~/.ai-evals/reports")).expanduser()
        reports_dir.mkdir(parents=True, exist_ok=True)
        default_path = reports_dir / "dashboard.html"
        default_path.write_text(html, encoding="utf-8")

    return html
