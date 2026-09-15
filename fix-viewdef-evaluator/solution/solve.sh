#!/bin/bash

cd /app

# Install dependencies
npm install --quiet 2>/dev/null

# Apply fixes to the evaluator
python3 /solution/apply_fixes.py

# Verify the fixes work
npx tsx /app/runner.ts 2>/dev/null | python3 -c "
import sys, json
r = json.load(sys.stdin)
print(f\"Tests: {r['passed']}/{r['total']} passed, {r['failed']} failed\")
if r['failed'] > 0:
    for t in r['results']:
        if not t['passed']:
            print(f\"  FAIL {t['file']}::{t['title']}: {t.get('error','?')}\")
sys.exit(0 if r['failed'] == 0 else 1)
"
