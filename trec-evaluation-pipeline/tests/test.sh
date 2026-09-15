#!/usr/bin/env bash

# Build trec_eval for reference metric computation (non-fatal if it fails)
if [ -d /app/trec_eval ] && [ -f /app/trec_eval/Makefile ]; then
    cd /app/trec_eval && make -s 2>/dev/null || true
fi

pip3 install pytest==8.3.4 -q

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
