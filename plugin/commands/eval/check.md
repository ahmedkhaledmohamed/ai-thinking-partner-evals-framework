---
name: eval:check
description: Quick quality check on a single file
argument-hint: [file-path]
---

# /eval:check

Run a quick quality evaluation on a specific file.

## Usage
- `/eval:check path/to/brief.md` — evaluate a specific document
- `/eval:check .` — evaluate the most recently written file

## Instructions

1. Read the target file
2. Detect the file type:
   - `.md` file >100 words → structural check (Tier 1) + LLM judge (Tier 2)
   - `.json` data file → schema validation + freshness check
   - `.html` prototype → check for required elements (phone frame, navigation)
   - `.py` script → syntax check + pattern conformance
3. For documents, auto-detect which skill produced it by scanning headings
4. Run the appropriate Tier 1 checks immediately
5. If the file is >200 words, also run the LLM judge with the matching rubric
6. Display a scorecard:

```
## Quick Check: brief.md
| Dimension | Score | Status |
|-----------|-------|--------|
| Completeness | 0.88 | GREEN |
| Evidence | 0.65 | YELLOW |
| **Overall** | **0.76** | **YELLOW** |

Weaknesses:
- Missing Dependencies section
- 2 claims without specific evidence
```

7. Append the result to the daily JSONL log
