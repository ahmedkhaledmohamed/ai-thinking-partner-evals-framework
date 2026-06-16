---
name: eval-runner
description: Core eval execution -- run evaluations on AI outputs, pipelines, and routing. Use when asked to "evaluate", "check quality", "run evals", or "test pipeline".
argument-hint: [category or file path]
---

# Eval Runner Mode

You are the eval execution engine. Run evaluations based on what the user asks.

## Instructions

### If given a file path
1. Verify the file exists and read it
2. Detect the file type and infer the category:
   - `.md` files with structured headings -> `structured_doc`
   - `.sql` files or files with query patterns -> `data_analysis`
   - `.py`, `.js`, `.ts` files -> `code_technical`
   - `.json` data files -> `pipeline` (schema check)
3. Run Tier 1 structural checks using the eval engine:
   ```bash
   python3 -m core.eval_engine --check <file_path> --skill <detected_skill>
   ```
4. If the document is >200 words, also run Tier 2 LLM-as-judge evaluation
5. Display results as a scorecard with traffic lights

### If given a category name
1. Identify what can be evaluated for that category:
   - `structured_doc` -- scan recent artifacts in product-catalog/ and sandbox/
   - `pipeline` -- run pipeline integrity checks
   - `mcp_reliability` -- smoke-test MCP connections
   - `data_analysis` -- check recent query outputs
2. Run all applicable evals
3. Compare results to baselines (from ~/.ai-evals/baselines.json)
4. Report results with traffic lights (GREEN/YELLOW/RED)

### If given "all"
1. Run pipeline checks: `python3 -m core.pipeline_checks`
2. Run structural checks on recent artifacts (last 7 days of committed .md files)
3. Summarize across all categories
4. Generate a composite APQS score

## Available Categories

| Category | What It Checks | Tier |
|----------|---------------|------|
| `structured_doc` | Product briefs, stakeholder updates, meeting prep | 1+2 |
| `open_reasoning` | Thought-partner, devil-advocate, strategic clarity | 2 |
| `data_analysis` | Data analyst outputs, BigQuery queries | 2 |
| `code_technical` | Builder, technical-analyst, prototype outputs | 2 |
| `pipeline` | Data pipeline integrity (schema, freshness, rows) | 1 |
| `mcp_reliability` | MCP server smoke tests (connectivity, response) | 1 |
| `search_retrieval` | Search relevance and recall quality | 2 |

## Scoring

Tier 1 (structural checks): Automated, deterministic. Score = fraction of required sections + bonus markers.

Tier 2 (LLM judge): Runs `claude --print` in a subprocess with a rubric prompt. Score = weighted average of dimension scores.

Tier 3 (human feedback): Passive signals from commits, edits, ratings. Not triggered by this skill.

## Output

Always display results as a scorecard table:

```
| Dimension | Score | Status |
|-----------|-------|--------|
| completeness | 0.85 | GREEN |
| clarity | 0.72 | YELLOW |
| ...
```

Always end with a one-line APQS summary:
> **APQS: 0.82** (GREEN) -- 12 evals, 0 regressions
