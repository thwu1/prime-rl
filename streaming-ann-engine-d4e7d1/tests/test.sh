#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 pyyaml==6.0.2 -q

# Generate data (idempotent — overwrites if already present)
python3 /app/data/generate.py

# Compile the weighted-distance C library
gcc -shared -fPIC -O2 -o /app/lib/libwdist.so /app/lib/wdist.c

# Run the solver's streaming search engine
python3 /app/streaming_search.py \
  --data_dir /app/data \
  --lib_dir /app/lib \
  --output_dir /app/results \
  --k 10
ENGINE_EXIT=$?

# Run verification tests
pytest /tests/test_state.py -v
TEST_EXIT=$?

mkdir -p /logs/verifier
if [ $TEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $TEST_EXIT
