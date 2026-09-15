#!/bin/bash

pip3 install pytest==8.3.4 -q

# Build reference Go verifier from tamper-proof test-bundled source
mkdir -p /tmp/btree-verify-ref
cp /tests/reference_btree_tool/go.mod /tmp/btree-verify-ref/go.mod
cp /tests/reference_btree_tool/main.go /tmp/btree-verify-ref/main.go
cd /tmp/btree-verify-ref && go build -o /tmp/btverify_ref . 2>/dev/null || true

cd /app
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
