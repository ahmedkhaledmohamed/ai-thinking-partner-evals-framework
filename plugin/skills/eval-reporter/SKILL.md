---
name: eval-reporter
description: Generate eval quality reports and dashboards. Use when asked for "eval report", "quality summary", "weekly quality", or "eval dashboard".
argument-hint: [daily|weekly|trend|dashboard]
---

# Eval Reporter Mode

You generate quality reports from eval results stored in ~/.ai-evals/results/.

## Instructions

Parse the user's request and generate the appropriate report.

### Daily Report
1. Determine today's date (or the date the user specifies)
2. Load the JSONL file: `~/.ai-evals/results/{date}.jsonl`
3. Run: `python3 -c "from core.reporter import generate_daily_report; print(generate_daily_report('{date}'))"`
4. Display the markdown report inline
5. Save to `~/.ai-evals/reports/daily-{date}.md`

### Weekly Report
1. Determine the 7-day window (ending today or user-specified date)
2. Run: `python3 -c "from core.reporter import generate_weekly_report; print(generate_weekly_report('{end_date}'))"`
3. Display the markdown report inline
4. Highlight any APQS trend changes (improving, declining, stable)
5. Save to `~/.ai-evals/reports/weekly-{end_date}.md`

### Trend Report
1. Generate the weekly report (as above)
2. Run regression detection: `python3 -c "from core.regression import detect_regressions, format_regression_report; print(format_regression_report(detect_regressions()))"`
3. Display both reports
4. Generate the HTML dashboard (see below)

### Dashboard
1. Run: `python3 -c "from core.reporter import generate_dashboard_html; generate_dashboard_html()"`
2. The dashboard is saved to `~/.ai-evals/reports/dashboard.html`
3. Tell the user the path and offer to open it:
   `open ~/.ai-evals/reports/dashboard.html`

## Report Conventions

- Traffic lights: GREEN (>=0.8), YELLOW (0.6-0.8), RED (<0.6)
- APQS = AI Product Quality Score (weighted composite across all categories)
- All scores are 0.0-1.0 scale
- Regressions are flagged when scores drop >15% below 7-day rolling average
- Reports use markdown tables for structured data

## When No Data Exists

If there are no results yet:
1. Explain that evals need to run first
2. Suggest: "Run `/eval:run all` to generate initial baseline data"
3. Or: "The post-write hook will automatically capture evals as you work"
