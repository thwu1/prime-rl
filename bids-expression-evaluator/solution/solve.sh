#!/bin/bash

cd /app

# Install dependencies
npm install --legacy-peer-deps 2>&1

echo "Fixing BIDS expression language evaluator, inheritance resolver, and rule engine..."

# Verify all source files exist before attempting fixes
MISSING=0
for f in src/lexer.ts src/parser.ts src/evaluator.ts src/functions.ts src/rule_engine.ts src/types.ts src/index.ts src/inheritance.ts; do
  if [ ! -f "/app/$f" ]; then
    echo "ERROR: Missing source file: /app/$f"
    MISSING=1
  fi
done
if [ $MISSING -ne 0 ]; then
    echo "Directory listing of /app/src/:"
    ls -la /app/src/ 2>&1 || echo "/app/src/ does not exist"
    exit 1
fi
echo "All source files verified."

# Apply all fixes
python3 /solution/fix_evaluator.py
FIX_EXIT=$?
if [ $FIX_EXIT -ne 0 ]; then
    echo "Fix script failed with exit code $FIX_EXIT"
    exit 1
fi

# Verify the expression evaluator fixes
echo "=== Expression Evaluator Tests ==="
npx tsx run_tests.ts

# Verify the inheritance resolver fixes
echo "=== Inheritance Resolver Tests ==="
npx tsx resolve.ts spec/inheritance_tests.json

# Verify the rule engine fixes
echo "=== Validation Rule Engine Tests ==="
npx tsx validate.ts spec/test_contexts.json
