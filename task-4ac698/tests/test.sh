#!/usr/bin/env bash

# Install test dependencies
pip3 install pytest==8.3.4 -q

# Compile additional test programs that the agent hasn't seen
mkdir -p /tmp/test_programs
cp /tests/test_programs/*.c /tmp/test_programs/

clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -c /tmp/test_programs/test_multi_prog.c -o /tmp/test_programs/test_multi_prog.o
clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -c /tmp/test_programs/test_minimal.c -o /tmp/test_programs/test_minimal.o
clang -O2 -target bpf -I/usr/include/x86_64-linux-gnu -c /tmp/test_programs/test_many_maps.c -o /tmp/test_programs/test_many_maps.o

# Run pytest
pytest /tests/test_state.py -v
TEST_EXIT=$?

# Write reward
mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $TEST_EXIT
