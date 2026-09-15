#!/usr/bin/env bash

export PIP_BREAK_SYSTEM_PACKAGES=1

# Ensure reward is written even on unexpected exit
cleanup() {
    if [ ! -f /logs/verifier/reward.txt ]; then
        mkdir -p /logs/verifier
        echo "0.0" > /logs/verifier/reward.txt
    fi
}
trap cleanup EXIT

python3 -m pip install pytest==8.3.4 cryptography==44.0.3 pyyaml==6.0.2 -q 2>&1

# Ensure test keys exist (fallback)
if [ ! -f /app/test_keys/private.pem ]; then
    mkdir -p /app/test_keys
    openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:prime256v1 -out /app/test_keys/private.pem 2>/dev/null
    openssl pkey -in /app/test_keys/private.pem -pubout -out /app/test_keys/public.pem 2>/dev/null
fi

cd /app

python3 -m pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
