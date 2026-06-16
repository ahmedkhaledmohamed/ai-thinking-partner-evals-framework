---
name: eval:report
description: Generate eval quality reports (daily, weekly, or trend)
argument-hint: [daily|weekly|trend]
---

# /eval:report

Generate AI quality reports at different time scales.

## Usage
- `/eval:report` or `/eval:report daily` -- today's report
- `/eval:report weekly` -- this week's rollup
- `/eval:report trend` -- 30-day trend with regression analysis

## Instructions

Parse the argument (default: "daily") and generate the appropriate report.

### Daily (default)
1. Determine today's date (UTC)
2. Load results from `~/.ai-evals/results/{date}.jsonl`
3. Run `generate_daily_report(date)` from `core/reporter.py`
4. Save output to `~/.ai-evals/reports/daily-{date}.md`
5. Display the report inline

### Weekly
1. Determine the end date (today) and start date (7 days ago)
2. Run `generate_weekly_report(end_date)` from `core/reporter.py`
3. Save output to `~/.ai-evals/reports/weekly-{end_date}.md`
4. Display the report inline
5. Highlight regressions and improvements

### Trend
1. Run `generate_weekly_report(today)` for the narrative
2. Run `generate_dashboard_html()` from `core/reporter.py` to create the HTML dashboard
3. Save dashboard to `~/.ai-evals/reports/dashboard.html`
4. Run regression detection via `detect_regressions()` from `core/regression.py`
5. Display the weekly report inline
6. If regressions found, show the regression report
7. Tell the user the dashboard path and offer to open it

## Output Format

Reports use markdown with traffic light indicators:
- **GREEN** (>=0.8): healthy
- **YELLOW** (0.6-0.8): needs attention
- **RED** (<0.6): action required

Always end with a summary line:
> **APQS: {score}** ({status}) -- {count} evals, {regressions} regressions
