#!/usr/bin/env bash
# Post-commit eval hook.
# Evaluates markdown and JSON files from the last commit.

set -euo pipefail

COMMIT_SHA=$(git rev-parse HEAD 2>/dev/null) || exit 0

# Get files changed in last commit
CHANGED_FILES=$(git diff --name-only HEAD~1 HEAD 2>/dev/null) || exit 0

if [[ -z "$CHANGED_FILES" ]]; then
    exit 0
fi

FRAMEWORK_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
EVAL_COUNT=0
LOW_SCORES=""

while IFS= read -r FILE_PATH; do
    # Skip empty lines
    [[ -z "$FILE_PATH" ]] && continue

    # Make path absolute if relative
    if [[ "$FILE_PATH" != /* ]]; then
        FILE_PATH="$(git rev-parse --show-toplevel 2>/dev/null)/$FILE_PATH"
    fi

    # Skip if file doesn't exist (deleted files)
    [[ ! -f "$FILE_PATH" ]] && continue

    case "$FILE_PATH" in
        *.md)
            # Only evaluate markdown files with 200+ words
            WORD_COUNT=$(wc -w < "$FILE_PATH" | tr -d ' ')
            if [[ "$WORD_COUNT" -lt 200 ]]; then
                continue
            fi

            RESULT=$(python3 -c "
import sys, json
sys.path.insert(0, '${FRAMEWORK_DIR}')
from core.eval_engine import EvalRunner
runner = EvalRunner()
result = runner.run_structural_check('${FILE_PATH}', 'unknown')
result.meta['commit_sha'] = '${COMMIT_SHA}'
runner.append_result(result)
print(json.dumps({'score': result.overall_score, 'name': result.eval_name}))
" 2>/dev/null) || continue

            EVAL_COUNT=$((EVAL_COUNT + 1))

            SCORE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['score'])" 2>/dev/null) || continue
            if python3 -c "exit(0 if $SCORE < 0.6 else 1)" 2>/dev/null; then
                NAME=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])" 2>/dev/null)
                LOW_SCORES="${LOW_SCORES}\n  ${NAME}: ${SCORE}"
            fi
            ;;

        *.json)
            # Schema check: verify it's valid JSON
            if ! python3 -c "import json; json.load(open('${FILE_PATH}'))" 2>/dev/null; then
                LOW_SCORES="${LOW_SCORES}\n  invalid-json: ${FILE_PATH}"
            fi
            EVAL_COUNT=$((EVAL_COUNT + 1))
            ;;
    esac

done <<< "$CHANGED_FILES"

# Summary output
if [[ -n "$LOW_SCORES" ]]; then
    echo "[eval] Commit ${COMMIT_SHA:0:7}: ${EVAL_COUNT} artifacts evaluated, issues found:${LOW_SCORES}"
elif [[ "$EVAL_COUNT" -gt 0 ]]; then
    echo "[eval] Commit ${COMMIT_SHA:0:7}: ${EVAL_COUNT} artifacts evaluated, all passed."
fi
