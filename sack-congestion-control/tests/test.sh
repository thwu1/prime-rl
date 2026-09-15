#!/bin/bash

# Ensure infrastructure files exist in /app/ (backup from /opt/starter/)
for f in packet.py emulator.py run_transfer.py; do
    if [ ! -f "/app/$f" ]; then
        cp "/opt/starter/$f" "/app/$f"
    fi
done

pip3 install pytest==8.3.4 -q

pytest /tests/test_state.py -v --tb=short
rc=$?

mkdir -p /logs/verifier
if [ $rc -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $rc
