# AI Evals Framework

## What This Is
Continuous evaluation framework for AI agent ecosystems. Measures output quality across 7 categories using automated checks, LLM-as-judge rubrics, and passive human feedback.

## Project Structure
- `core/` -- Python eval engine (the library)
- `plugin/` -- Claude Code plugin (skills, commands, hooks, rubrics)
- `framework/` -- Documentation for external users

## Development
- Python 3.10+, stdlib + PyYAML only
- Run evals: `python3 -m core.eval_engine --check <file>`
- Run pipeline checks: `python3 -m core.pipeline_checks --pipeline <name>`
- Run reports: `python3 -c "from core.reporter import generate_daily_report; print(generate_daily_report('2026-06-16'))"`
- Run regression detection: `python3 -c "from core.regression import detect_regressions, format_regression_report; print(format_regression_report(detect_regressions()))"`
- Generate dashboard: `python3 -c "from core.reporter import generate_dashboard_html; generate_dashboard_html()"`

## Key Patterns
- Results stored as JSONL in ~/.ai-evals/results/
- Golden files in ~/.ai-evals/golden/
- Baselines computed and saved to ~/.ai-evals/baselines.json
- Rubrics are markdown files in plugin/rubrics/
- Judge uses `claude --print` subprocess (separate context)
- Reports saved to ~/.ai-evals/reports/
- Dashboard is a self-contained HTML file (no external deps)

## When Editing
- Keep rubric dimension weights summing to 1.0
- Anti-pattern penalties are additive (each -0.1)
- Pipeline configs are defaults -- users override in config.yaml
- Don't add external dependencies beyond PyYAML
- Traffic light thresholds: GREEN >= 0.8, YELLOW >= 0.6, RED < 0.6
- Regression threshold: >15% below 7-day rolling average
- All dates use UTC and YYYY-MM-DD format
- JSONL files are one JSON object per line, named {date}.jsonl
