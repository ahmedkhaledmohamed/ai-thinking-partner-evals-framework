#!/usr/bin/env bash
# Post-write quality capture hook.
# Receives JSON on stdin from Claude Code PostToolUse event.
# Runs a structural eval on markdown files produced by skills.
# Silent on success (score >= 0.6); shows missing sections on low quality.

set -euo pipefail

FRAMEWORK_DIR="${AI_EVALS_FRAMEWORK_DIR:-/Users/ahmedm/Developer/ai-evals-framework}"

# Read file_path from stdin JSON
FILE_PATH=$(cat | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null) || exit 0

if [[ -z "$FILE_PATH" ]]; then exit 0; fi
if [[ "$FILE_PATH" != *.md ]]; then exit 0; fi
if [[ ! -f "$FILE_PATH" ]]; then exit 0; fi

WORD_COUNT=$(wc -w < "$FILE_PATH" | tr -d ' ')
if [[ "$WORD_COUNT" -lt 100 ]]; then exit 0; fi

# Let the eval engine detect the skill (don't duplicate detection here)
RESULT=$(python3 -c "
import sys, json
sys.path.insert(0, '${FRAMEWORK_DIR}')
from core.eval_engine import EvalRunner, SKILL_SECTIONS
runner = EvalRunner()
result = runner.run_structural_check('${FILE_PATH}', 'auto')
runner.append_result(result)
missing = []
if result.skill in SKILL_SECTIONS:
    missing = [k for k, v in result.scores.items() if not k.startswith('bonus_') and v == 0.0]
print(json.dumps({
    'score': result.overall_score,
    'skill': result.skill,
    'missing': missing[:4],
}))
" 2>/dev/null) || exit 0

SCORE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['score'])" 2>/dev/null) || exit 0

if python3 -c "exit(0 if $SCORE < 0.6 else 1)" 2>/dev/null; then
    SKILL=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['skill'])" 2>/dev/null)
    MISSING=$(echo "$RESULT" | python3 -c "import sys,json; m=json.load(sys.stdin)['missing']; print(', '.join(m) if m else 'general structure')" 2>/dev/null)
    echo "[eval] ${SKILL}: ${SCORE} — missing: ${MISSING}"
fi
