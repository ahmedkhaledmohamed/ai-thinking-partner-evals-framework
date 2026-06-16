---
name: eval:calibrate
description: Calibrate the LLM judge against human ratings
argument-hint: 
---

# /eval:calibrate

Calibrate the LLM judge by comparing its scores to human ratings.

## Instructions

### Step 1: Load Human Feedback
1. Scan `~/.ai-evals/feedback/` for all JSONL files
2. Extract entries with `signal_type` of `quick_rating` or `retrospective` — these contain explicit human scores
3. Also include `committed` (0.8) and `abandoned` (0.1) as implicit signals
4. Build a list of `(artifact_path, human_score)` pairs

### Step 2: Match with Judge Scores
1. Load results from `~/.ai-evals/results/` for the same date range
2. For each human-rated artifact, find the corresponding judge evaluation by matching:
   - `artifact_path` or `input_summary` contains the same filename
   - Same date (within 24 hours)
3. Build paired list: `(human_score, judge_score)`
4. Report how many pairs were found vs how many feedback entries exist

### Step 3: Compute Correlation
1. Run `core/judge.calibration_check(human_scores, judge_scores)`
2. This computes Spearman rank correlation (rho) from scratch

### Step 4: Report Results
```
### Calibration Report

**Paired samples:** 23 / 31 feedback entries matched
**Spearman rho:** 0.74
**P-value:** 0.0003
**Status:** CALIBRATED

**Bias:** Lenient (+0.08 average)
  - Judge tends to score 0.08 higher than human ratings
  - Strongest on structured docs (+0.12), closest on data analysis (+0.02)

**Per-category calibration:**
| Category | Pairs | Rho | Bias | Status |
|----------|-------|-----|------|--------|
| Structured Doc | 12 | 0.81 | +0.12 lenient | CALIBRATED |
| Reasoning | 6 | 0.65 | +0.05 lenient | PARTIAL |
| Data Analysis | 5 | 0.78 | +0.02 neutral | CALIBRATED |

**Recommendation:** Reasoning category needs prompt tuning — rho below 0.7 threshold.
```

### Step 5: Save Calibration State
Write to `~/.ai-evals/calibration.json`:
```json
{
  "last_calibrated": "2026-06-16T12:00:00Z",
  "overall_rho": 0.74,
  "overall_status": "calibrated",
  "bias_direction": "lenient",
  "bias_magnitude": 0.08,
  "per_category": {
    "structured_doc": {"rho": 0.81, "bias": 0.12, "status": "calibrated", "n": 12},
    "open_reasoning": {"rho": 0.65, "bias": 0.05, "status": "partial", "n": 6},
    "data_analysis": {"rho": 0.78, "bias": 0.02, "status": "calibrated", "n": 5}
  },
  "total_pairs": 23,
  "total_feedback": 31
}
```

### Calibration Status Thresholds
| Rho | Status | Meaning |
|-----|--------|---------|
| >= 0.7 | CALIBRATED | Judge scores are trustworthy |
| 0.5 - 0.69 | PARTIAL | Use with caution, consider adjusting rubric prompts |
| < 0.5 | UNCALIBRATED | Judge scores should not be trusted alone |

### When to Re-calibrate
- After changing rubric prompts
- After switching judge models
- Weekly as part of `/eval:rate week`
- When a user reports a score that feels wrong (add as feedback, then re-calibrate)
