"""
Multi-tier metric aggregation pipeline that processes latency data
from distributed hosts using DDSketch quantile sketches.

The pipeline:
1. Reads per-tier DDSketch parameters from /app/output/tier_config.json
2. Queries latency data from SQLite database
3. Groups records by time window and service tier
4. Creates per-host DDSketch instances, merges per tier per window
5. Computes percentiles and writes results to JSON
"""

import json
import os
import sqlite3
from collections import defaultdict
from sketch import DDSketch


def load_sla_config():
    with open('/app/sla_config.json') as f:
        return json.load(f)


def load_tier_config():
    with open('/app/output/tier_config.json') as f:
        return json.load(f)


def process_pipeline():
    sla = load_sla_config()
    tier_config = load_tier_config()

    window_size = sla['constraints']['window_size_sec']
    percentiles = sla['constraints']['percentiles']

    conn = sqlite3.connect('/app/data/metrics.db')
    c = conn.cursor()
    c.execute(
        'SELECT timestamp, service_tier, host_id, latency_ms '
        'FROM latency_samples ORDER BY timestamp'
    )

    window_tier_data = defaultdict(lambda: defaultdict(list))
    for ts, tier, host, latency in c.fetchall():
        window_id = int(ts / window_size)
        window_tier_data[window_id][tier].append((host, latency))

    conn.close()

    results = {}
    for window_id in sorted(window_tier_data.keys()):
        window_result = {}
        for tier in sorted(window_tier_data[window_id].keys()):
            tc = tier_config[tier]
            alpha = tc['alpha']
            max_bins = tc['max_num_bins']

            host_data = defaultdict(list)
            for host, latency in window_tier_data[window_id][tier]:
                host_data[host].append(latency)

            merged = DDSketch(alpha=alpha, max_num_bins=max_bins)
            for host, values in host_data.items():
                s = DDSketch(alpha=alpha, max_num_bins=max_bins)
                for v in values:
                    s.add(v)
                merged.merge(s)

            tier_result = {}
            for p in percentiles:
                tier_result[str(p)] = merged.quantile(p)

            window_result[tier] = tier_result
        results[str(window_id)] = window_result

    os.makedirs('/app/output', exist_ok=True)
    with open('/app/output/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == '__main__':
    results = process_pipeline()
    print(json.dumps(results, indent=2))
