---
name: eval:run
description: Run evals for a category or all categories
argument-hint: [category|all]
---

# /eval:run

Run evaluations across categories.

## Usage
- `/eval:run all` — run all enabled evals
- `/eval:run structured_doc` — run structural document checks
- `/eval:run pipeline` — alias for `/eval:pipeline all`
- `/eval:run routing` — run routing golden file comparison
- `/eval:run golden_staleness` — check for stale golden files

## Instructions

1. Parse the category argument from `$ARGUMENTS`.  If empty, default to `all`.

2. Load config from `~/.ai-evals/config.yaml`:

```bash
cd /Users/ahmedm/Developer/ai-evals-framework
python3 -c "
from core.config import load_config
import json
config = load_config()
print(json.dumps(config, indent=2))
"
```

3. Route to the appropriate handler based on category:

### `pipeline` (or when `all` includes it)

Delegate to `/eval:pipeline all`.  Alternatively run directly:

```bash
cd /Users/ahmedm/Developer/ai-evals-framework
python3 -c "
from core.pipeline_checks import run_all_pipelines, format_pipeline_report
results = run_all_pipelines()
print(format_pipeline_report(results))
"
```

### `structured_doc`

Scan recent artifacts (last 7 days) in `product-catalog/` and `sandbox/` for eval-eligible documents.  For each:
- Check markdown structure (has H1, sections, non-empty body)
- Check length (>200 chars for non-trivial docs)
- Check for stale date references
- Report findings as a table

```bash
find ~/Developer/ClientMessaging/product-catalog -name "*.md" -mtime -7 -type f 2>/dev/null
find ~/Developer/ClientMessaging/sandbox -name "*.md" -mtime -7 -type f 2>/dev/null
```

### `routing`

Load the routing golden file and compare against the current skill list:

```bash
cd /Users/ahmedm/Developer/ai-evals-framework
python3 -c "
from core.golden import load_golden, compare_to_golden
golden = load_golden('routing', 'skill-routing')
if golden:
    # Compare against current skill list (extracted from settings)
    print('Golden loaded, ready for comparison')
else:
    print('No routing golden file found. Run /eval:pipeline --snapshot to create one.')
"
```

### `golden_staleness`

Check all golden files for staleness:

```bash
cd /Users/ahmedm/Developer/ai-evals-framework
python3 -c "
from core.golden import check_golden_staleness, list_golden_files
stale = check_golden_staleness(max_days=30)
all_golden = list_golden_files()
print(f'Total golden files: {len(all_golden)}')
print(f'Stale (>30 days): {len(stale)}')
for g in stale:
    print(f'  {g[\"category\"]}/{g[\"name\"]} — {g[\"age_days\"]}d old')
"
```

### `all`

Run all enabled categories in sequence.  Check config to see which are enabled:

```python
for cat_name, cat_config in config["categories"].items():
    if cat_config.get("enabled", True):
        # run that category
```

Order: `pipeline` -> `structured_doc` -> `routing` -> `golden_staleness`

Skip categories that aren't implemented yet (e.g. `open_reasoning`, `data_analysis`) with an INFO note.

4. Generate a summary report combining all category results:

```
## Eval Summary — YYYY-MM-DD

| Category | Status | Checks Run | Passed | Issues |
|----------|--------|------------|--------|--------|
| pipeline | PASS   | 24         | 22     | 2 WARN |
| structured_doc | PASS | 5     | 5      | -      |
| routing  | SKIP   | -          | -      | No golden file |

**APQS Impact**: pipeline checks contribute 10% of the overall AI Product Quality Score.
```

5. Append results to `~/.ai-evals/results/YYYY-MM-DD.jsonl`.

## Categories Reference

| Category | Tier | What It Checks |
|----------|------|----------------|
| `pipeline` | 1 | Data file integrity (schema, freshness, row counts, nulls) |
| `structured_doc` | 1 | Document structural quality (recent artifacts) |
| `mcp_reliability` | 1 | MCP tool call success rates (not yet implemented) |
| `open_reasoning` | 2 | Thought-partner / devil-advocate quality (not yet implemented) |
| `data_analysis` | 2 | BigQuery / data-analyst output quality (not yet implemented) |
| `code_technical` | 2 | Builder / technical-analyst output quality (not yet implemented) |
| `search_retrieval` | 2 | Nestor search relevance (not yet implemented) |
| `routing` | - | Skill routing golden comparison |
| `golden_staleness` | - | Audit golden file freshness |
