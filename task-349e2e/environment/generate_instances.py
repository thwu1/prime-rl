#!/usr/bin/env python3
"""Generate deterministic test instances for the Optimal Touring puzzle."""

import json
import os
import sys

sys.path.insert(0, '/app')
from game import generate_instance

SEEDS = [42, 137, 271, 593, 1009]
INSTANCES_DIR = '/app/instances'


def main():
    os.makedirs(INSTANCES_DIR, exist_ok=True)
    for i, seed in enumerate(SEEDS, 1):
        sites_data = generate_instance(seed, num_sites=40)
        # JSON requires string keys
        json_data = {str(k): v for k, v in sites_data.items()}
        outpath = os.path.join(INSTANCES_DIR, f'instance_{i}.json')
        with open(outpath, 'w') as fh:
            json.dump(json_data, fh, indent=2)
        print(f"Generated {outpath}  (seed={seed}, sites={len(sites_data)})")


if __name__ == '__main__':
    main()
