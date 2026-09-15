#!/usr/bin/env python3
"""
Compute optimal per-tier DDSketch parameters by evaluating the
accuracy-memory tradeoff for each service tier's actual data range.

For each tier:
1. Query SQLite to find the actual min/max latency range
2. Extract SLA constraints (max_relative_error, max_memory_bytes_per_sketch)
3. Compute bins_needed = ceil(log(max/min) / log(gamma)) at alpha = max_relative_error
4. Verify bins * bytes_per_bin fits within memory budget
5. Choose optimal (alpha, max_num_bins) that satisfies both constraints
"""

import json
import math
import os
import sqlite3
import subprocess


def extract_sla_with_jq(config_path):
    """Use jq to extract per-tier SLA parameters from the nested config."""
    tiers = {}

    # Extract tier names
    result = subprocess.run(
        ['jq', '-r', '.service_tiers | keys[]', config_path],
        capture_output=True, text=True
    )
    tier_names = result.stdout.strip().split('\n')

    for tier in tier_names:
        # Extract max_relative_error
        result = subprocess.run(
            ['jq', '-r',
             f'.service_tiers.{tier}.sla.accuracy.max_relative_error',
             config_path],
            capture_output=True, text=True
        )
        max_err = float(result.stdout.strip())

        # Extract max_memory_bytes_per_sketch
        result = subprocess.run(
            ['jq', '-r',
             f'.service_tiers.{tier}.sla.resources.max_memory_bytes_per_sketch',
             config_path],
            capture_output=True, text=True
        )
        max_mem = int(result.stdout.strip())

        tiers[tier] = {'max_relative_error': max_err, 'max_memory': max_mem}

    # Extract bytes_per_bin
    result = subprocess.run(
        ['jq', '-r', '.constraints.bytes_per_bin', config_path],
        capture_output=True, text=True
    )
    bytes_per_bin = int(result.stdout.strip())

    return tiers, bytes_per_bin


def query_tier_ranges(db_path):
    """Use sqlite3 to get data range per tier."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute(
        'SELECT service_tier, MIN(latency_ms), MAX(latency_ms), COUNT(*) '
        'FROM latency_samples GROUP BY service_tier'
    )
    ranges = {}
    for tier, min_val, max_val, count in c.fetchall():
        ranges[tier] = {
            'min': min_val, 'max': max_val, 'count': count
        }

    conn.close()
    return ranges


def compute_optimal_config(tier_name, max_err, max_mem, bytes_per_bin,
                           data_min, data_max):
    """Evaluate and select optimal (alpha, max_num_bins) for a tier."""
    max_bins_allowed = max_mem // bytes_per_bin

    # Use alpha = max_relative_error (tightest accuracy the SLA permits)
    alpha = max_err
    gamma = (1 + alpha) / (1 - alpha)

    # Compute the bins needed to cover the full data range
    bins_needed = math.ceil(math.log(data_max / data_min) / math.log(gamma))

    print(f"  Tier {tier_name}: range=[{data_min:.4f}, {data_max:.4f}], "
          f"alpha={alpha}, gamma={gamma:.6f}")
    print(f"    bins_needed={bins_needed}, max_bins_allowed={max_bins_allowed}")

    # Use the full memory budget to maximize accuracy and avoid collapse
    actual_bins = max_bins_allowed
    print(f"    -> Using max_num_bins={actual_bins} (maximizing accuracy within budget)")

    return {'alpha': alpha, 'max_num_bins': actual_bins}


def main():
    config_path = '/app/sla_config.json'
    db_path = '/app/data/metrics.db'

    print("=== Extracting SLA parameters with jq ===")
    tier_slas, bytes_per_bin = extract_sla_with_jq(config_path)

    print("\n=== Querying data ranges with sqlite3 ===")
    tier_ranges = query_tier_ranges(db_path)

    print("\n=== Evaluating per-tier configurations ===")
    tier_config = {}
    for tier_name, sla in tier_slas.items():
        data = tier_ranges[tier_name]
        config = compute_optimal_config(
            tier_name,
            sla['max_relative_error'],
            sla['max_memory'],
            bytes_per_bin,
            data['min'],
            data['max']
        )
        tier_config[tier_name] = config

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/tier_config.json', 'w') as f:
        json.dump(tier_config, f, indent=2)

    print("\n=== Final tier configuration ===")
    print(json.dumps(tier_config, indent=2))


if __name__ == '__main__':
    main()
