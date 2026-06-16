---
name: eval:rate
description: Multi-level quality rating (PR, day, week)
argument-hint: [pr|day|week]
---

# /eval:rate

Rate AI output quality at different granularity levels.

## Usage
- `/eval:rate pr` — evaluate all artifacts in the current PR/last commit
- `/eval:rate day` — aggregate today's work quality
- `/eval:rate week` — weekly quality summary with trends

## Instructions

### PR Level
1. Get files from last commit: `git diff --name-only HEAD~1 HEAD`
2. Filter to eval-eligible files:
   - Markdown files (`.md`) with >200 words
   - HTML files (`.html`)
   - JSON data files where content was AI-generated
   - Exclude: CLAUDE.md, CHANGELOG, package-lock.json, config files
3. For each eligible file:
   - Run structural check (Tier 1) via `core/eval_engine.py`
   - Detect artifact type and select rubric
   - If the file is a document (>500 words), run LLM judge (Tier 2) with appropriate rubric via `core/judge.py`
4. Generate PR scorecard:
   ```
   ### PR Quality: [branch name]
   | File | Tier 1 | Tier 2 | Overall | Status |
   |------|--------|--------|---------|--------|
   | brief.md | 0.85 | 0.72 | 0.78 | YELLOW |
   | update.md | 0.90 | 0.88 | 0.89 | GREEN |
   | **PR Average** | | | **0.84** | **GREEN** |
   ```
5. Store result at `~/.ai-evals/reports/pr/{repo}_{commit-sha}.md`

### Day Level
1. Load all JSONL entries from today: `~/.ai-evals/results/YYYY-MM-DD.jsonl`
2. Compute daily APQS (AI Product Quality Score):
   - Weighted composite across categories using weights from `core/config.py`
   - structured_docs: 0.20, reasoning: 0.15, data_analytics: 0.15
   - code_technical: 0.15, search_retrieval: 0.10, pipelines: 0.10, mcp_reliability: 0.15
3. Show skill usage distribution (which skills were used most)
4. Highlight best and worst scoring outputs with context
5. Generate daily report at `~/.ai-evals/reports/YYYY-MM-DD.md`:
   ```
   ### Daily Quality Report: YYYY-MM-DD
   **APQS: 0.76** (YELLOW)

   | Category | Score | Count | Status |
   |----------|-------|-------|--------|
   | Structured Docs | 0.82 | 3 | GREEN |
   | Reasoning | 0.68 | 2 | YELLOW |
   | Data Analysis | 0.75 | 1 | YELLOW |

   **Best:** stakeholder-update (0.92) - weekly report to leadership
   **Worst:** thought-partner (0.55) - missed challenging flawed premise

   **Skill Usage:** product-brief (3), thought-partner (2), data-analyst (1)
   ```

### Week Level
1. Aggregate last 7 days of daily reports
2. Compute weekly APQS trend (show each day's score)
3. Detect regressions vs prior week:
   - Flag any category that dropped >15% week-over-week
   - Highlight any skill with consistent low scores (<0.6 for 3+ outputs)
4. Surface unrated outputs for batch rating (files created but not evaluated)
5. Generate weekly report at `~/.ai-evals/reports/week/YYYY-WNN.md`:
   ```
   ### Weekly Quality Report: Week 24 (Jun 10-16)
   **APQS Trend:** 0.72 -> 0.75 -> 0.71 -> 0.78 -> 0.80 -> 0.76 -> 0.79
   **Weekly Average:** 0.76 (YELLOW, +0.03 vs last week)

   **Regressions:** None
   **Improvements:** Reasoning +12% (from 0.61 to 0.68)

   **Unrated outputs:** 4 files not yet evaluated
   ```
6. If running inside `/pm:plan-week`, inject a "Last Week's AI Quality" section into the planning output
