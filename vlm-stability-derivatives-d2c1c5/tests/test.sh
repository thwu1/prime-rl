#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Ensure config.json is at /app (may have been shadowed by volume mount)
cp /data/config.json /app/config.json 2>/dev/null || true

# Build C shared library if Makefile exists (compiles current source state)
if [ -f /app/libvortex/Makefile ]; then
    make -C /app/libvortex -s 2>/dev/null || true
fi

cd /app
pytest /tests/test_state.py -v --tb=short
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
