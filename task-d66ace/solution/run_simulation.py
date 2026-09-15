#!/usr/bin/env python3
"""Run the queue-position fill simulation with multiple probability models."""
import json
import sys
import numpy as np

sys.path.insert(0, '/app')

from simulator import (
    PowerProbQueueFunc, LogProbQueueFunc, LogProbQueueFunc2,
    PowerProbQueueFunc2, PowerProbQueueFunc3, run_simulation
)

data = np.load('/app/market_data.npz')['data']
with open('/app/orders.json') as f:
    orders = json.load(f)
with open('/app/config.json') as f:
    config = json.load(f)

# Probability test values: prob(front=10, back=5)
results = {
    'probabilities': {
        'power2_front10_back5': PowerProbQueueFunc(2).prob(10, 5),
        'power3_3_front10_back5': PowerProbQueueFunc3(3).prob(10, 5),
        'log_front10_back5': LogProbQueueFunc().prob(10, 5),
        'log2_front10_back5': LogProbQueueFunc2().prob(10, 5),
        'power2_2_front10_back5': PowerProbQueueFunc2(2).prob(10, 5),
    }
}

# Run with PowerProb n=2
fills_p2, snapshots = run_simulation(data, orders, config, PowerProbQueueFunc(2))

# Run with PowerProb n=3
fills_p3, _ = run_simulation(data, orders, config, PowerProbQueueFunc(3))

# Run with LogProb
fills_lg, _ = run_simulation(data, orders, config, LogProbQueueFunc())

results['fills'] = {
    'power_n2': fills_p2,
    'power_n3': fills_p3,
    'log': fills_lg,
}
results['book_snapshots'] = snapshots

with open('/app/results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("Results written to /app/results.json")
