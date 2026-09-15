#!/usr/bin/env bash


# Install the solution scheduler
cp /solution/scheduler_solution.py /app/scheduler.py

# Verify with a quick sanity check
cd /app && python3 -c "
from scheduler import compute_schedule
c1, t1 = compute_schedule([10, 20])
assert c1 == 30, f'Expected 30, got {c1}'
c2, t2 = compute_schedule([1, 1, 100])
assert c2 == 104, f'Expected 104, got {c2}'
c3, t3 = compute_schedule([10, 10, 10, 10])
assert c3 == 80, f'Expected 80, got {c3}'
import random
rng = random.Random(42)
big = [rng.randint(1, 1000) for _ in range(10000)]
c, t = compute_schedule(big)
assert c > 0
print(f'All sanity checks passed. 10k-run cost: {c}')
"
