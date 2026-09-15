#!/usr/bin/env bash

pip3 install pytest==8.3.4 protobuf==5.29.3 numpy==2.1.3 -q

# Compile proto for test deserialization
mkdir -p /tmp/test_proto_out
protoc --proto_path=/app/protos --python_out=/tmp/test_proto_out /app/protos/game.proto

RESULT=$(PYTHONPATH=/tmp/test_proto_out python3 -m pytest /tests/test_state.py -v 2>&1)
EXIT_CODE=$?

echo "$RESULT"

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $EXIT_CODE
