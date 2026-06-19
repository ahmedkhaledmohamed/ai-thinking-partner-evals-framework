---
name: eval:improve
description: Analyze eval patterns and propose improvements to skills, CLAUDE.md, and config
argument-hint: [--apply|--dry-run]
---

# /eval:improve

Analyze accumulated eval data, identify quality gaps, and propose specific improvements to your AI ecosystem.

## Usage
- `/eval:improve` — analyze and show recommendations
- `/eval:improve --apply` — analyze, propose, and apply changes (with confirmation per change)
- `/eval:improve --dry-run` — show what would change without modifying anything

## Instructions

1. Run the insights engine:

```bash
cd /Users/ahmedm/Developer/ai-evals-framework
python3 -m core.insights
```

2. Present the findings organized by impact:
   - **HIGH impact**: changes that would fix >20% of low scores
   - **MEDIUM impact**: changes that improve measurement accuracy
   - **LOW impact**: cosmetic or minor improvements

3. For each recommendation, show:
   - What's wrong (with evidence from eval data)
   - What to change (specific file and content)
   - Expected impact

4. If `--apply` is passed, for each HIGH/MEDIUM recommendation:
   - Show the proposed change (diff-style)
   - Ask for confirmation before applying
   - Apply the change via Edit tool
   - Re-run affected evals to verify improvement

5. After applying changes, re-run `python3 -m core.retro_eval --dry-run` to estimate how scores would change.

## What It Can Improve

| Target | How |
|--------|-----|
| **Skill SKILL.md files** | Add Required Output Structure enforcement blocks |
| **Eval engine detection** | Tighten skill matching thresholds |
| **Eval engine scoring** | Improve general/fallback scoring heuristics |
| **Rubric dimensions** | Adjust weights or add new dimensions |
| **Config thresholds** | Tune regression sensitivity per skill |
| **Hook behavior** | Improve hook output (show missing sections) |
| **CLAUDE.md** | Add document quality standards |

## Output Format

```
## AI Evals Improvement Report

### 1. [HIGH] Tighten stakeholder-update detection
**Problem**: 33 files misclassified as stakeholder-update, avg score 0.13
**Evidence**: 85% of these files have 0/7 required sections as headings
**Fix**: Require 3+ heading matches instead of 2 body-text matches
**File**: core/eval_engine.py

### 2. [HIGH] Add enforcement to product-brief SKILL.md  
**Problem**: Product briefs average 0.17 — sections described but not enforced
**Fix**: Add Required Output Structure block
**File**: ~/.claude/skills/product-brief/SKILL.md

Applied: 2/3 recommendations
Re-eval estimate: stakeholder-update 0.13 → 0.65, product-brief 0.17 → 0.80
```
