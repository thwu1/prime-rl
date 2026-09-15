#!/usr/bin/env bash

set -u

pip3 install pytest==8.3.4 -q 2>/dev/null

cd /app

# Build the vtable engine
make -C /app 2>&1
BUILD_RC=$?

if [ $BUILD_RC -ne 0 ]; then
    echo "Build failed with exit code $BUILD_RC"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Generate candidate JSON output from the solution for each test header
mkdir -p /app/candidate_output

for header in /app/test_headers/test*.h; do
    base=$(basename "$header" .h)
    /app/vtable_engine "$header" > "/app/candidate_output/${base}.json" 2>/dev/null || true
done

# Generate runtime introspection reference data
# For each test header, compile a C++ program that inspects actual
# object layout and vtable contents at runtime
mkdir -p /app/reference_output

python3 /tests/generate_introspection.py

# Run pytest
RESULT=0
python3 -m pytest /tests/test_state.py -v --tb=short 2>&1 || RESULT=$?

mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
