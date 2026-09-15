#!/bin/bash

pip3 install pytest==8.3.4 cryptography==43.0.1 -q

# Run Python tests (includes CMAC, XAES-256-GCM, interop, and file tool tests)
RESULT_PY=$(pytest /tests/test_state.py -v 2>&1)
PY_EXIT=$?
echo "$RESULT_PY"

# Run Go unit tests
cp /tests/xaes_test.go /app/go_impl/xaes_test.go
cd /app/go_impl
RESULT_GO=$(go test -v -count=1 -timeout=120s 2>&1)
GO_EXIT=$?
echo "$RESULT_GO"

mkdir -p /logs/verifier
if [ $PY_EXIT -eq 0 ] && [ $GO_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $(( PY_EXIT + GO_EXIT ))
