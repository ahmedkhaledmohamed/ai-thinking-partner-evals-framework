"""
Regression detection for AI Evals Framework.

Computes rolling baselines, detects score drops, and correlates
with recent changes to skill files, CLAUDE.md, and MCP configs.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev

from core.config import load_config
from core.eval_engine import EvalResult


@dataclass
class Regression:
    metric: str  # e.g., "structured_doc.completeness"
    current: float
    baseline_mean: float
    baseline_std: float
    drop_pct: float  # How much below baseline
    consecutive_below: int
    first_seen: str  # ISO date
    possible_causes: list[str] = field(default_factory=list)
    severity: str = "watch"  # "watch", "warning", "alert"


# ---------------------------------------------------------------------------
# Result loading
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


# ---------------------------------------------------------------------------
# Baseline computation
# ---------------------------------------------------------------------------


def compute_baselines(
    results_dir: str | None = None,
    window_days: int = 30,
) -> dict[str, dict]:
    """Compute rolling mean + std for each metric over the window.

    Returns {"category.dimension": {"mean": float, "std": float, "n": int}}
    Saves to ~/.ai-evals/baselines.json.
    """
    config = load_config()
    if results_dir:
        config["results_dir"] = results_dir

    now = datetime.now(timezone.utc)
    all_results: list[EvalResult] = []

    for i in range(window_days):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        all_results.extend(_load_results_for_date(day, config))

    scored = [r for r in all_results if r.error is None]

    # Group by category + eval_name
    groups: dict[str, list[float]] = {}
    for r in scored:
        key = f"{r.category}.{r.eval_name}"
        groups.setdefault(key, []).append(r.overall_score)

    # Also group by category alone
    by_cat: dict[str, list[float]] = {}
    for r in scored:
        by_cat.setdefault(r.category, []).append(r.overall_score)

    baselines: dict[str, dict] = {}

    for key, scores in groups.items():
        baselines[key] = {
            "mean": round(mean(scores), 4),
            "std": round(stdev(scores), 4) if len(scores) > 1 else 0.0,
            "n": len(scores),
        }

    for cat, scores in by_cat.items():
        baselines[cat] = {
            "mean": round(mean(scores), 4),
            "std": round(stdev(scores), 4) if len(scores) > 1 else 0.0,
            "n": len(scores),
        }

    # Save baselines
    baselines_dir = Path("~/.ai-evals").expanduser()
    baselines_dir.mkdir(parents=True, exist_ok=True)
    baselines_path = baselines_dir / "baselines.json"

    with open(baselines_path, "w") as f:
        json.dump(
            {"computed_at": now.isoformat(), "window_days": window_days, "metrics": baselines},
            f,
            indent=2,
        )

    return baselines


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------


def detect_regressions(
    results_dir: str | None = None,
    baselines: dict | None = None,
) -> list[Regression]:
    """Detect regressions:

    - Score drops >15% below 7-day rolling average
    - 3 consecutive scores below baseline mean
    - Any pipeline CRITICAL

    For each regression, try to correlate with recent changes.
    """
    config = load_config()
    if results_dir:
        config["results_dir"] = results_dir

    threshold_pct = config.get("thresholds", {}).get("regression_pct", 15)

    if baselines is None:
        baselines = compute_baselines(results_dir)

    now = datetime.now(timezone.utc)

    # Load recent results (7 days for current window)
    recent: list[EvalResult] = []
    for i in range(7):
        day = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        recent.extend(_load_results_for_date(day, config))

    scored = [r for r in recent if r.error is None]
    if not scored:
        return []

    # Group by metric key (category.eval_name)
    by_metric: dict[str, list[EvalResult]] = {}
    for r in scored:
        key = f"{r.category}.{r.eval_name}"
        by_metric.setdefault(key, []).append(r)

    regressions: list[Regression] = []

    for metric_key, metric_results in by_metric.items():
        baseline = baselines.get(metric_key)
        if not baseline or baseline["n"] < 3:
            continue

        baseline_mean = baseline["mean"]
        baseline_std = baseline["std"]

        if baseline_mean <= 0:
            continue

        current_scores = sorted(metric_results, key=lambda r: r.timestamp)
        current_avg = mean(r.overall_score for r in current_scores)
        drop_pct = ((baseline_mean - current_avg) / baseline_mean) * 100

        # Count consecutive scores below baseline
        consecutive_below = 0
        for r in reversed(current_scores):
            if r.overall_score < baseline_mean:
                consecutive_below += 1
            else:
                break

        # Determine severity
        is_regression = False
        severity = "watch"

        if drop_pct > threshold_pct:
            is_regression = True
            if drop_pct > 30:
                severity = "alert"
            elif drop_pct > threshold_pct:
                severity = "warning"

        if consecutive_below >= 3:
            is_regression = True
            if severity == "watch":
                severity = "warning"

        if not is_regression:
            continue

        # Find first occurrence
        first_seen = current_scores[0].timestamp[:10]
        for r in current_scores:
            if r.overall_score < baseline_mean:
                first_seen = r.timestamp[:10]
                break

        reg = Regression(
            metric=metric_key,
            current=round(current_avg, 3),
            baseline_mean=round(baseline_mean, 3),
            baseline_std=round(baseline_std, 3),
            drop_pct=round(drop_pct, 1),
            consecutive_below=consecutive_below,
            first_seen=first_seen,
            severity=severity,
        )

        # Try to correlate with changes
        reg.possible_causes = correlate_with_changes(reg)

        regressions.append(reg)

    # Sort by severity (alert > warning > watch), then drop_pct
    severity_order = {"alert": 0, "warning": 1, "watch": 2}
    regressions.sort(key=lambda r: (severity_order.get(r.severity, 3), -r.drop_pct))

    return regressions


# ---------------------------------------------------------------------------
# Change correlation
# ---------------------------------------------------------------------------

_WATCHED_PATHS = [
    "~/.claude/skills/",
    ".claude/",
    "CLAUDE.md",
    "~/.claude/settings.json",
    "~/.claude/settings.local.json",
]


def correlate_with_changes(regression: Regression) -> list[str]:
    """Run git log on skill files, CLAUDE.md, MCP configs to find possible causes."""
    causes: list[str] = []

    # Try git log in the current working directory
    since_date = regression.first_seen
    paths_to_check = [
        "CLAUDE.md",
        ".claude/",
    ]

    for path in paths_to_check:
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    f"--since={since_date}",
                    "--oneline",
                    "--",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().splitlines()[:5]:
                    causes.append(f"[{path}] {line.strip()}")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue

    # Check home directory skill changes
    home_skills = Path("~/.claude/skills").expanduser()
    if home_skills.is_dir():
        try:
            result = subprocess.run(
                [
                    "git", "log",
                    f"--since={since_date}",
                    "--oneline",
                    "--",
                    str(home_skills),
                ],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(Path.home()),
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().splitlines()[:5]:
                    causes.append(f"[skills] {line.strip()}")
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Check if any skill files were recently modified (filesystem check, not git)
    if home_skills.is_dir():
        since = datetime.strptime(regression.first_seen, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        try:
            for skill_dir in home_skills.iterdir():
                if skill_dir.is_dir():
                    for f in skill_dir.iterdir():
                        if f.is_file():
                            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                            if mtime >= since:
                                causes.append(f"[modified] {f.name} ({mtime.strftime('%Y-%m-%d')})")
        except OSError:
            pass

    return causes[:10]  # Cap at 10 causes


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def format_regression_report(regressions: list[Regression]) -> str:
    """Format a list of regressions as a markdown report."""
    lines: list[str] = []
    now = datetime.now(timezone.utc)
    lines.append(f"# Regression Report -- {now.strftime('%Y-%m-%d')}")
    lines.append("")

    if not regressions:
        lines.append("All metrics within normal range. No regressions detected.")
        lines.append("")
        lines.append(f"*Checked {now.isoformat()}*")
        return "\n".join(lines)

    # Summary
    alerts = sum(1 for r in regressions if r.severity == "alert")
    warnings = sum(1 for r in regressions if r.severity == "warning")
    watches = sum(1 for r in regressions if r.severity == "watch")

    lines.append(f"**{len(regressions)} regressions detected**: {alerts} alerts, {warnings} warnings, {watches} watches")
    lines.append("")

    # Detail table
    lines.append("| Severity | Metric | Current | Baseline | Drop | Consecutive Below | First Seen |")
    lines.append("|----------|--------|---------|----------|------|-------------------|------------|")

    severity_icon = {"alert": "ALERT", "warning": "WARN", "watch": "WATCH"}

    for r in regressions:
        icon = severity_icon.get(r.severity, "?")
        lines.append(
            f"| **{icon}** | {r.metric} | {r.current:.3f} | "
            f"{r.baseline_mean:.3f} +/- {r.baseline_std:.3f} | "
            f"{r.drop_pct:+.1f}% | {r.consecutive_below} | {r.first_seen} |"
        )

    lines.append("")

    # Possible causes
    causes_found = False
    for r in regressions:
        if r.possible_causes:
            if not causes_found:
                lines.append("## Possible Causes")
                lines.append("")
                causes_found = True
            lines.append(f"### {r.metric} ({r.severity})")
            for cause in r.possible_causes:
                lines.append(f"- {cause}")
            lines.append("")

    if not causes_found:
        lines.append("## Possible Causes")
        lines.append("")
        lines.append("No correlated changes found in git history. Consider checking:")
        lines.append("- MCP server configuration changes")
        lines.append("- Model version updates")
        lines.append("- External data source changes")
        lines.append("")

    lines.append(f"*Generated {now.isoformat()}*")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    import sys

    baselines = compute_baselines()
    print(f"Computed baselines for {len(baselines)} metrics\n")

    regressions = detect_regressions(baselines=baselines)
    print(format_regression_report(regressions))
