#!/bin/bash


pip3 install pytest==8.3.4 -q

cd /app

# Install npm dependencies
npm install 2>&1

# Copy test runner into source directory for compilation
cp /tests/test_runner.ts /app/src/test_runner.ts

# Verify key source files exist
echo "Checking source files..."
ls -la /app/src/*.ts 2>&1

# Compile TypeScript
npx tsc > /tmp/tsc_output.txt 2>&1
TSC_EXIT=$?

if [ $TSC_EXIT -ne 0 ]; then
  echo "TypeScript compilation failed:"
  cat /tmp/tsc_output.txt
  echo '[{"name":"compilation","passed":false,"error":"TypeScript compilation failed"}]' > /tmp/crdt_test_results.json
fi

# Run test runner if compilation succeeded
if [ $TSC_EXIT -eq 0 ]; then
  node /app/dist/test_runner.js > /tmp/crdt_test_results.json 2>/tmp/node_stderr.txt
  NODE_EXIT=$?
  if [ $NODE_EXIT -ne 0 ] && [ ! -s /tmp/crdt_test_results.json ]; then
    echo "Runtime error:"
    cat /tmp/node_stderr.txt
    echo '[{"name":"runtime","passed":false,"error":"Runtime error"}]' > /tmp/crdt_test_results.json
  fi
fi

# Run pytest validation
pytest /tests/test_state.py -v 2>&1
PYTEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
  echo "1.0" > /logs/verifier/reward.txt
else
  echo "0.0" > /logs/verifier/reward.txt
fi
exit $PYTEST_EXIT
