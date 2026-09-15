#!/bin/bash

pip3 install pytest==8.3.4 numpy==2.1.3 -q

# Build baseline from stored copy (writes to /tmp so it won't overwrite agent output)
g++ -O2 -std=c++17 -o /tmp/baseline /tests/baseline.cpp -lm

# Run timing measurements via Python for precision
python3 << 'PYEOF'
import subprocess, time, json, sys

baseline_time = 0
optimized_time = 9999

# Time the naive baseline
try:
    start = time.perf_counter()
    subprocess.run(['/tmp/baseline'], timeout=180, check=True)
    baseline_time = time.perf_counter() - start
    print(f'Baseline completed in {baseline_time:.2f}s')
except Exception as e:
    print(f'Baseline failed: {e}', file=sys.stderr)

# Build agent's optimized version
try:
    subprocess.run(['make', '-C', '/app', '-B'], timeout=120, check=True)
    print('Optimized build succeeded')
except Exception as e:
    print(f'Build failed: {e}', file=sys.stderr)
    json.dump({'baseline_time': baseline_time, 'optimized_time': optimized_time},
              open('/app/timing.json', 'w'))
    sys.exit(0)

# Time the optimized version
try:
    start = time.perf_counter()
    subprocess.run(['/app/correlate'], timeout=120, check=True)
    optimized_time = time.perf_counter() - start
    print(f'Optimized completed in {optimized_time:.2f}s')
except Exception as e:
    print(f'Optimized run failed: {e}', file=sys.stderr)

if optimized_time > 0 and optimized_time < 9999:
    speedup = baseline_time / optimized_time
    print(f'Speedup: {speedup:.2f}x')

json.dump({'baseline_time': baseline_time, 'optimized_time': optimized_time},
          open('/app/timing.json', 'w'))
PYEOF

# Run pytest
pytest /tests/test_state.py -v
PYTEST_EXIT=$?

mkdir -p /logs/verifier
if [ $PYTEST_EXIT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $PYTEST_EXIT
