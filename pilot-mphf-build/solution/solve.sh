#!/bin/bash

set -e

# Ensure all key datasets exist (regenerate if missing from build layer)
python3 /app/generate_keys.py

# Copy solution sources into /app
cp /solution/mphf_impl.c     /app/mphf.c
cp /solution/mphf_tool_impl.py /app/mphf_tool.py

# Build the shared library
cd /app
make clean
make

# Smoke test: random_1k
echo "=== Smoke test: random_1k ==="
python3 /app/mphf_tool.py build /app/data/random_1k.txt /tmp/smoke_1k.mph
python3 /app/mphf_tool.py info  /tmp/smoke_1k.mph
python3 /app/mphf_tool.py query /tmp/smoke_1k.mph /app/data/random_1k.txt > /tmp/smoke_1k_out.txt
LINES=$(wc -l < /tmp/smoke_1k_out.txt)
UNIQUE=$(sort -u /tmp/smoke_1k_out.txt | wc -l)
echo "keys=$LINES  unique_values=$UNIQUE"
[ "$LINES" -eq "$UNIQUE" ] && echo "PASS: bijective" || echo "FAIL: not bijective"

# Smoke test: sequential keys
echo "=== Smoke test: sequential_10k ==="
python3 /app/mphf_tool.py build /app/data/sequential_10k.txt /tmp/smoke_seq.mph
python3 /app/mphf_tool.py query /tmp/smoke_seq.mph /app/data/sequential_10k.txt > /tmp/smoke_seq_out.txt
LINES=$(wc -l < /tmp/smoke_seq_out.txt)
UNIQUE=$(sort -u /tmp/smoke_seq_out.txt | wc -l)
echo "keys=$LINES  unique_values=$UNIQUE"
[ "$LINES" -eq "$UNIQUE" ] && echo "PASS: bijective" || echo "FAIL: not bijective"

# Smoke test: adversarial keys
echo "=== Smoke test: adversarial_20k ==="
python3 /app/mphf_tool.py build /app/data/adversarial_20k.txt /tmp/smoke_adv.mph
python3 /app/mphf_tool.py info  /tmp/smoke_adv.mph
python3 /app/mphf_tool.py query /tmp/smoke_adv.mph /app/data/adversarial_20k.txt > /tmp/smoke_adv_out.txt
LINES=$(wc -l < /tmp/smoke_adv_out.txt)
UNIQUE=$(sort -u /tmp/smoke_adv_out.txt | wc -l)
echo "keys=$LINES  unique_values=$UNIQUE"
[ "$LINES" -eq "$UNIQUE" ] && echo "PASS: bijective" || echo "FAIL: not bijective"

# Smoke test: 200k random keys
echo "=== Smoke test: random_200k ==="
START=$(date +%s)
python3 /app/mphf_tool.py build /app/data/random_200k.txt /tmp/smoke_200k.mph
END=$(date +%s)
echo "Build time: $((END - START))s"
python3 /app/mphf_tool.py info /tmp/smoke_200k.mph

# Smoke test: 1M random keys (timed)
echo "=== Smoke test: random_1m ==="
START=$(date +%s)
python3 /app/mphf_tool.py build /app/data/random_1m.txt /tmp/smoke_1m.mph
END=$(date +%s)
echo "Build time: $((END - START))s"
python3 /app/mphf_tool.py info /tmp/smoke_1m.mph
python3 /app/mphf_tool.py query /tmp/smoke_1m.mph /app/data/random_1m.txt > /tmp/smoke_1m_out.txt
LINES=$(wc -l < /tmp/smoke_1m_out.txt)
UNIQUE=$(sort -u /tmp/smoke_1m_out.txt | wc -l)
echo "keys=$LINES  unique_values=$UNIQUE"
[ "$LINES" -eq "$UNIQUE" ] && echo "PASS: bijective" || echo "FAIL: not bijective"

echo "=== All smoke tests completed ==="
