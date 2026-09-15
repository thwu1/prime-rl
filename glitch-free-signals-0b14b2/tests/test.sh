#!/bin/bash

set +e

cd /app
npm install 2>/dev/null 1>/dev/null

# Run TypeScript test harness
npx tsx /tests/test_harness.ts > /tmp/test_results.json 2>/tmp/test_stderr.txt
TSX_EXIT=$?

if [ $TSX_EXIT -ne 0 ] && [ ! -s /tmp/test_results.json ]; then
    echo "[]" > /tmp/test_results.json
    echo "tsx failed with exit code $TSX_EXIT" >> /tmp/test_stderr.txt
fi

pip3 install pytest==8.3.4 -q 2>/dev/null

python3 -m pytest /tests/test_state.py -v
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit 0
