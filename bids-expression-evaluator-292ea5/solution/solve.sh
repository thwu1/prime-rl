#!/bin/bash


set -e

cd /app

# Install node dependencies
npm install --silent 2>/dev/null

# Apply fixes: replace buggy lexer and evaluator with corrected versions
cp /solution/fixed_lexer.ts /app/src/lexer.ts
cp /solution/fixed_evaluator.ts /app/src/evaluator.ts

# Verify TypeScript compiles
npx tsc --noEmit

# Run expression test suite and verify all pass
RESULT=$(npx ts-node src/run_tests.ts)
echo "$RESULT"

FAILED=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['failed'])")
if [ "$FAILED" -ne 0 ]; then
  echo "ERROR: $FAILED tests still failing"
  exit 1
fi

echo "All expression tests pass."
