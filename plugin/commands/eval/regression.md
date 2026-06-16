---
name: eval:regression
description: Detect quality regressions and correlate with changes
argument-hint:
---

# /eval:regression

Detect and investigate quality regressions in AI output quality.

## Instructions

1. Compute baselines from the last 30 days of results using `compute_baselines()` from `core/regression.py`
2. Run `detect_regressions()` to compare recent scores against baselines
3. Format the results using `format_regression_report()`

### For each regression found:
a. Show the metric name, current score, baseline mean +/- std
b. Show the severity (alert / warning / watch) and drop percentage
c. Show how many consecutive evaluations fell below the baseline
d. Check git log for recent changes to:
   - `~/.claude/skills/` (skill definition changes)
   - `CLAUDE.md` and `.claude/` (project instruction changes)
   - MCP config files (tool availability changes)
e. List possible causes from correlated changes
f. Suggest investigation steps based on severity

### Severity levels:
- **alert**: >30% below baseline or critical pipeline failure. Investigate immediately.
- **warning**: >15% below baseline or 3+ consecutive below-mean scores. Investigate soon.
- **watch**: Notable decline but within tolerance. Monitor over next few days.

### If no regressions:
Report "All metrics within normal range" with a brief summary of current baselines.

## Output

Always end with a one-line status:
> **Regression check**: {count} issues ({alerts} alerts, {warnings} warnings) or "All clear"
