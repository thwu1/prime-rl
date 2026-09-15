#!/usr/bin/env python3
"""Generate transaction test data for streaming consistency benchmarks."""

import random
import json
import sys

MAX_ID = 100000
NUM_ACCOUNTS = 10
NUM_SECONDS = 60


def generate_random(seed=42):
    random.seed(seed)
    transactions = []
    for txn_id in range(MAX_ID):
        second = (NUM_SECONDS * txn_id) // MAX_ID
        delay = random.uniform(0, 10)
        txn = {
            'id': txn_id,
            'from_account': random.randint(0, NUM_ACCOUNTS - 1),
            'to_account': random.randint(0, NUM_ACCOUNTS - 1),
            'amount': 1,
            'ts': second,
        }
        transactions.append((second + delay, txn_id, txn))
    transactions.sort(key=lambda x: (x[0], x[1]))
    for arrival_time, _, txn in transactions:
        txn['arrival_time'] = arrival_time
        print(json.dumps(txn))


def generate_simplified():
    for txn_id in range(MAX_ID):
        second = (NUM_SECONDS * txn_id) // MAX_ID
        txn = {
            'id': txn_id,
            'from_account': txn_id % NUM_ACCOUNTS,
            'to_account': (txn_id % NUM_ACCOUNTS + 1) % NUM_ACCOUNTS,
            'amount': 1,
            'ts': second,
            'arrival_time': float(second),
        }
        print(json.dumps(txn))


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'random'
    if mode == 'random':
        generate_random()
    elif mode == 'simplified':
        generate_simplified()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
