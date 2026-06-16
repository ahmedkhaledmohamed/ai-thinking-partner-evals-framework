---
name: eval-feedback
description: Capture quality feedback on AI outputs. Use when user rates work, says "that was good/bad", or wants to review past quality.
argument-hint: [rating 1-5 or feedback text]
---

# Eval Feedback Mode

You capture and manage human feedback signals for calibrating eval quality.

## Instructions

### Quick Rating (number 1-5)
If the user provides a number (1-5):
1. Map to 0-1 scale: 1=0.2, 2=0.4, 3=0.6, 4=0.8, 5=1.0
2. Identify the most recent artifact (last file written or discussed)
3. Infer the skill that produced it
4. Record the feedback signal:
   ```python
   from core.feedback import FeedbackSignal, append_feedback
   signal = FeedbackSignal(
       timestamp=..., signal_type="quick_rating",
       skill=..., artifact_path=..., value=...
   )
   append_feedback(signal)
   ```
5. Confirm: "Recorded rating {n}/5 for {artifact} ({skill})"

### Text Feedback
If the user provides descriptive text (e.g., "that brief was weak on evidence"):
1. Parse the feedback to identify:
   - **Skill**: Which skill produced the work (product-brief, writer, etc.)
   - **Dimension**: What aspect was affected (completeness, clarity, evidence, etc.)
   - **Polarity**: Positive or negative signal
   - **Severity**: How strong the feedback is (minor, moderate, significant)
2. Map to a numeric value:
   - Strong positive: 0.9-1.0
   - Mild positive: 0.7-0.8
   - Mild negative: 0.3-0.5
   - Strong negative: 0.1-0.2
3. Save to feedback JSONL with the parsed metadata
4. Confirm what was captured and ask if the interpretation is correct

### Retrospective
If the user asks to review past work:
1. Load the current week's results from `~/.ai-evals/results/`
2. Find outputs that have eval scores but no human feedback
3. Present them in a list:
   ```
   Unrated outputs this week:
   1. product-brief: rich-media-brief.md (auto-score: 0.82)
   2. stakeholder-update: weekly-update.md (auto-score: 0.75)
   3. meeting-prep: 1on1-prep.md (auto-score: 0.88)

   Rate each 1-5, or skip with Enter:
   ```
4. Collect ratings for each
5. Save all feedback signals
6. Report calibration: how human ratings compare to auto-scores

## Feedback Storage

Feedback is stored as JSONL in `~/.ai-evals/feedback/{date}.jsonl`.

Each signal contains:
- `timestamp`: ISO datetime
- `signal_type`: "quick_rating", "text_feedback", "retrospective", "committed", "deployed"
- `skill`: Which skill produced the output
- `artifact_path`: Path to the artifact
- `value`: 0.0-1.0 score
- `meta`: Additional context (parsed text, dimension, polarity)

## Passive Signals

The framework also captures passive signals automatically:
- **committed** (0.8): File was committed to git (implicit approval)
- **deployed** (0.9): File was deployed to production
- **heavy_edit** (0.3): File was significantly edited after generation (implicit dissatisfaction)
- **abandoned** (0.1): File was deleted or never committed
