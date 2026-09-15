#!/bin/bash


# Copy reference implementation to /app/
cp /solution/egraph_impl.py /app/egraph_opt.py

# Verify the optimizer works on all benchmarks
python3 -c "
import json, sys
sys.path.insert(0, '/app')
from egraph_opt import optimize

with open('/app/benchmarks.json') as f:
    data = json.load(f)

for bench in data['benchmarks']:
    result = optimize(bench['expr'])
    print('Benchmark {}: {} => {}'.format(bench['id'], bench['expr'], result))
print('All benchmarks processed successfully.')
"
