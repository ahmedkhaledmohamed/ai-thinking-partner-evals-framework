# AI Evals Framework

Continuous evaluation for AI agent ecosystems. Tracks output quality across structured documents, reasoning, data analysis, code generation, search retrieval, data pipelines, and MCP reliability — using automated checks, LLM-as-judge rubrics, and passive human feedback.

Built for power users running Claude Code, Cursor, or similar AI coding assistants who want to measure and improve the quality of AI-generated work over time.

## Quick Install

```bash
git clone https://github.com/ahmedkhaledmohamed/ai-evals-framework.git
cd ai-evals-framework
node plugin/bin/install.js
```

The installer detects your runtime (Claude Code / Cursor), creates `~/.ai-evals/` with default config, and copies skills + commands + hooks.

## Core Concepts

### Three-Tier Evaluation

| Tier | Method | Speed | When |
|------|--------|-------|------|
| **1** | Structural checks | <1s | Every write (automated via hooks) |
| **2** | LLM-as-judge | ~5s | On demand or for documents >200 words |
| **3** | Human feedback | Passive | Commit signals, edit distance, explicit ratings |

### Seven Categories

| Category | What It Measures |
|----------|-----------------|
| `structured_doc` | Product briefs, updates, meeting prep — section completeness + quality |
| `open_reasoning` | Thought-partner, devil-advocate — argument depth + balance |
| `data_analysis` | SQL queries, metric interpretation — correctness + insight |
| `code_technical` | Generated code, prototypes — functionality + patterns |
| `search_retrieval` | Search relevance — precision + recall |
| `pipeline` | Data pipeline integrity — schema, freshness, row counts, nulls |
| `mcp_reliability` | MCP server connectivity — uptime + response quality |

### APQS (AI Product Quality Score)

A weighted composite (0.0-1.0) across all categories:

```
APQS = 0.20 * structured_docs
     + 0.15 * reasoning
     + 0.15 * data_analytics
     + 0.15 * code_technical
     + 0.10 * search_retrieval
     + 0.10 * pipelines
     + 0.15 * mcp_reliability
```

Traffic lights: **GREEN** (>= 0.8) | **YELLOW** (0.6-0.8) | **RED** (< 0.6)

## Available Commands

| Command | Description |
|---------|-------------|
| `/eval:run [file\|category\|all]` | Run evaluations |
| `/eval:report [daily\|weekly\|trend]` | Generate quality reports |
| `/eval:rate [1-5]` | Record human feedback |
| `/eval:pipeline [name]` | Run pipeline integrity checks |
| `/eval:regression` | Detect and investigate quality regressions |
| `/eval:calibrate` | Compare human ratings to auto-scores |
| `/eval:check <file>` | Quick structural check on a single file |

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Claude Code                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────┐  │
│  │  Skills   │  │ Commands │  │      Hooks       │  │
│  │ eval-*    │  │ /eval:*  │  │ post-write-eval  │  │
│  └─────┬─────┘  └────┬─────┘  │ post-commit-eval │  │
│        │             │        └────────┬─────────┘  │
└────────┼─────────────┼────────────────┼─────────────┘
         │             │                │
    ┌────▼─────────────▼────────────────▼────┐
    │            core/ (Python)               │
    │  ┌─────────────┐  ┌────────────────┐   │
    │  │ eval_engine  │  │ pipeline_checks│   │
    │  │  Tier 1+2    │  │  Schema/Fresh  │   │
    │  └──────┬───────┘  └───────┬────────┘   │
    │  ┌──────▼───────┐  ┌──────▼─────────┐   │
    │  │  reporter     │  │  regression    │   │
    │  │  Daily/Weekly │  │  Baselines     │   │
    │  │  Dashboard    │  │  Correlation   │   │
    │  └──────────────┘  └────────────────┘   │
    │  ┌──────────────┐  ┌────────────────┐   │
    │  │  feedback     │  │  aggregator    │   │
    │  │  Tier 3       │  │  APQS scoring  │   │
    │  └──────────────┘  └────────────────┘   │
    └─────────────────────────────────────────┘
         │
    ┌────▼────────────────┐
    │  ~/.ai-evals/        │
    │  results/  (JSONL)   │
    │  golden/   (baselines)│
    │  feedback/ (signals) │
    │  reports/  (output)  │
    │  config.yaml         │
    └─────────────────────┘
```

## Data Storage

All data lives in `~/.ai-evals/`:

| Directory | Format | Contents |
|-----------|--------|----------|
| `results/` | JSONL | One file per day: `2026-06-16.jsonl` |
| `golden/` | JSON | Golden baselines for regression comparison |
| `feedback/` | JSONL | Human feedback signals |
| `reports/` | MD + HTML | Generated reports and dashboard |
| `config.yaml` | YAML | User configuration overrides |
| `baselines.json` | JSON | Computed 30-day rolling baselines |

## Custom Rubrics

Rubrics live in `plugin/rubrics/` as markdown files. Each rubric defines dimensions with weights:

```markdown
# Rubric: Product Brief

## Dimensions
| Dimension | Weight | Criteria |
|-----------|--------|----------|
| completeness | 0.25 | All required sections present and substantive |
| clarity | 0.20 | Clear problem statement, unambiguous scope |
| evidence | 0.20 | Claims backed by data or citations |
| actionability | 0.20 | Clear next steps, owners, timelines |
| conciseness | 0.15 | No filler, appropriate length for content |

## Anti-Patterns (-0.1 each)
- Vague success metrics ("improve user experience")
- Missing dependencies or risks section
- No quantified targets
```

The judge loads the rubric, evaluates each dimension 0-1, applies weights, and subtracts anti-pattern penalties.

## Configuration

Override defaults in `~/.ai-evals/config.yaml`:

```yaml
# Change the judge model
judge_model: claude-sonnet-4-20250514

# Adjust regression sensitivity
thresholds:
  regression_pct: 10  # Alert at 10% drop instead of 15%

# Add custom pipeline
pipelines:
  my-dashboard:
    name: My Dashboard
    data_dir: ~/projects/dashboard/data/
    expected_files: [metrics.json, users.json]
    freshness_hours: 24
```

## Contributing

1. Fork and clone
2. `pip install -e .` (installs core/ as editable package)
3. Make changes to `core/` or `plugin/`
4. Test: `python3 -m core.eval_engine --check <test-file> --skill unknown`
5. Open a PR

Dependencies: Python 3.10+ and PyYAML. No other external packages.

## License

MIT
