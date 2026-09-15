#!/bin/bash

# Build drat-trim for independent proof verification in tests
if [ ! -f /usr/local/bin/drat-trim ]; then
    wget -q https://raw.githubusercontent.com/marijnheule/drat-trim/master/drat-trim.c -O /tmp/drat-trim_test.c 2>/dev/null ||  wget -q https://raw.githubusercontent.com/marijnheule/drat-trim/main/drat-trim.c -O /tmp/drat-trim_test.c 2>/dev/null
    if [ -f /tmp/drat-trim_test.c ]; then
        gcc -O2 -o /usr/local/bin/drat-trim /tmp/drat-trim_test.c 2>/dev/null
    fi
fi

cd /app
pytest /tests/test_state.py -v
exit_code=$?

mkdir -p /logs/verifier
if [ $exit_code -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $exit_code
