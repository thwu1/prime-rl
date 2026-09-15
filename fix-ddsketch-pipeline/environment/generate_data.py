#!/usr/bin/env python3
"""Generate deterministic latency data in SQLite format for multi-tier monitoring."""

import sqlite3
import random
import os


def generate_data():
    random.seed(42)

    os.makedirs('/app/data', exist_ok=True)
    db_path = '/app/data/metrics.db'

    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS latency_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        service_tier TEXT NOT NULL,
        host_id TEXT NOT NULL,
        latency_ms REAL NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS service_metadata (
        tier TEXT PRIMARY KEY,
        description TEXT,
        num_hosts INTEGER,
        distribution_type TEXT
    )''')

    tiers = {
        'web': {
            'description': 'User-facing web application endpoints',
            'num_hosts': 5,
            'dist': 'lognormal',
            'params': {'mu': 2.0, 'sigma': 0.5},
        },
        'batch': {
            'description': 'Background batch processing jobs',
            'num_hosts': 3,
            'dist': 'uniform_wide',
            'params': {'low': 50.0, 'high': 5000.0},
        },
        'realtime': {
            'description': 'Real-time event streaming services',
            'num_hosts': 4,
            'dist': 'bimodal',
            'params': {'mu1': 0.5, 'sigma1': 0.2, 'mu2': 3.0, 'sigma2': 0.3, 'mix': 0.7},
        },
    }

    for tier_name, cfg in tiers.items():
        c.execute('INSERT INTO service_metadata VALUES (?, ?, ?, ?)',
                  (tier_name, cfg['description'], cfg['num_hosts'], cfg['dist']))

    num_windows = 20
    window_size = 10
    points_per_host_per_window = 100

    records = []
    for tier_name, cfg in tiers.items():
        for host_idx in range(cfg['num_hosts']):
            host_id = f"{tier_name}-host-{host_idx}"
            for window in range(num_windows):
                for _ in range(points_per_host_per_window):
                    timestamp = window * window_size + random.uniform(0, window_size)

                    dist = cfg['dist']
                    params = cfg['params']

                    if dist == 'lognormal':
                        latency = random.lognormvariate(params['mu'], params['sigma'])
                    elif dist == 'uniform_wide':
                        latency = random.uniform(params['low'], params['high'])
                    elif dist == 'bimodal':
                        if random.random() < params['mix']:
                            latency = random.lognormvariate(params['mu1'], params['sigma1'])
                        else:
                            latency = random.lognormvariate(params['mu2'], params['sigma2'])
                    else:
                        latency = 1.0

                    if random.random() < 0.02:
                        latency *= random.uniform(5, 20)

                    records.append((timestamp, tier_name, host_id, latency))

    c.executemany(
        'INSERT INTO latency_samples (timestamp, service_tier, host_id, latency_ms) VALUES (?, ?, ?, ?)',
        records
    )

    c.execute('CREATE INDEX IF NOT EXISTS idx_tier ON latency_samples(service_tier)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_window ON latency_samples(timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_host ON latency_samples(host_id)')

    conn.commit()
    conn.close()
    print(f"Generated {len(records)} records in {db_path}")


if __name__ == '__main__':
    generate_data()
