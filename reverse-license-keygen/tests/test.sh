#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

cd /app

# Compile the patched binary if the solver provided source
if [ -f /app/license_check_patched.c ]; then
    gcc -O2 -static -s -o /app/license_check_patched /app/license_check_patched.c 2>/app/compile_errors.txt
    if [ $? -ne 0 ]; then
        echo "Warning: patched binary compilation failed:"
        cat /app/compile_errors.txt
    fi
fi

RESULT=$(python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
