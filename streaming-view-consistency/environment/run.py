#!/usr/bin/env python3
"""Run the reconciliation pipeline and check consistency invariants."""

import json
import sys
from engine import IncrementalViewEngine


def main():
    data_path = '/app/data/transactions.jsonl'
    delay = 5

    engine = IncrementalViewEngine(watermark_delay=delay)

    with open(data_path) as f:
        for line in f:
            event = json.loads(line)
            engine.ingest(event['arrival_time'], event)

    engine.finalize()

    checkpoints = engine.get_checkpoints()
    rejected = engine.get_rejected_count()

    print(f"Pipeline complete: {len(checkpoints)} checkpoints, {rejected} rejected")

    # Check consistency invariants
    failed = 0
    max_dev = 0
    for cp in checkpoints:
        if cp['total'] != 0:
            failed += 1
            max_dev = max(max_dev, abs(cp['total']))

    if failed:
        print(f"FAILED: {failed}/{len(checkpoints)} checkpoints have non-zero total")
        print(f"Maximum |total| deviation: {max_dev}")
        sys.exit(1)

    print("OK: all checkpoints satisfy consistency invariants")


if __name__ == '__main__':
    main()
