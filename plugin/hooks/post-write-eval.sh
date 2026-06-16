#!/usr/bin/env bash
# Post-write quality capture hook.
# Receives JSON on stdin from Claude Code PostToolUse event.
# Runs a structural eval on markdown files produced by skills.
# Silent on success (score >= 0.6); prints a one-liner on low quality.

set -euo pipefail

FRAMEWORK_DIR="${AI_EVALS_FRAMEWORK_DIR:-/Users/ahmedm/Developer/ai-evals-framework}"

# Read file_path from stdin JSON
FILE_PATH=$(cat | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null) || exit 0

if [[ -z "$FILE_PATH" ]]; then
    exit 0
fi

# Only evaluate markdown files
if [[ "$FILE_PATH" != *.md ]]; then
    exit 0
fi

if [[ ! -f "$FILE_PATH" ]]; then
    exit 0
fi

# Skip files under 100 words
WORD_COUNT=$(wc -w < "$FILE_PATH" | tr -d ' ')
if [[ "$WORD_COUNT" -lt 100 ]]; then
    exit 0
fi

# Detect skill from section patterns
SKILL="unknown"
if grep -qiE '(problem statement|proposed solution|success metrics|user value)' "$FILE_PATH"; then
    SKILL="product-brief"
elif grep -qiE '(tl;dr|key metrics|risks|asks|next period)' "$FILE_PATH"; then
    SKILL="stakeholder-update"
elif grep -qiE '(talking points|anticipated questions|preparation checklist)' "$FILE_PATH"; then
    SKILL="meeting-prep"
fi

# Run the structural check
RESULT=$(python3 -c "
import sys, json
sys.path.insert(0, '${FRAMEWORK_DIR}')
from core.eval_engine import EvalRunner
runner = EvalRunner()
result = runner.run_structural_check('${FILE_PATH}', '${SKILL}')
runner.append_result(result)
print(json.dumps({'score': result.overall_score, 'eval_name': result.eval_name, 'skill': result.skill}))
" 2>/dev/null) || exit 0

SCORE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['score'])" 2>/dev/null) || exit 0

# Only print if score is below threshold
if python3 -c "exit(0 if $SCORE < 0.6 else 1)" 2>/dev/null; then
    EVAL_NAME=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['eval_name'])" 2>/dev/null)
    echo "[eval] ${EVAL_NAME}: score=${SCORE} (below 0.6 threshold) — ${FILE_PATH}"
fi
