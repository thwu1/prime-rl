#!/usr/bin/env bash

pip3 install pytest==8.3.4 -q

cd /app

# Run the Makefile pipeline (non-fatal so pytest can still report specifics)
make all > /tmp/make_all.log 2>&1 || true

pytest /tests/test_state.py -v
RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
