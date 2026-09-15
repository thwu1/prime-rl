#!/bin/bash

pip3 install pytest==8.3.4 -q

# Check that the encoder has been run and produced messages
if [ ! -f /app/messages.txt ]; then
    echo "ERROR: /app/messages.txt not found - encoder has not been run"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Re-run the decoder on the encoded messages for fresh verification
rm -f /app/output.json
python3 /app/decoder.py
DECODE_EXIT=$?

if [ $DECODE_EXIT -ne 0 ]; then
    echo "Decoder failed with exit code $DECODE_EXIT"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run compiled integrity validator
echo "=== Message Integrity Check ==="
/app/msgcheck -v /app/messages.txt
MSGCHECK_EXIT=$?
echo "msgcheck exit code: $MSGCHECK_EXIT"

# Run pytest
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
