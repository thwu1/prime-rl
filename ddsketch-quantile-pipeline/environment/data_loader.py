"""Data loader for host latency CSV files."""
import csv
import os
from collections import defaultdict


def load_host_data(data_dir):
    """Load per-host CSV data.

    Returns dict mapping host_name -> {window_id: [latencies]}.
    """
    host_data = {}
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith('.csv'):
            continue
        host = fname.replace('.csv', '')
        windows = defaultdict(list)
        with open(os.path.join(data_dir, fname)) as f:
            reader = csv.DictReader(f)
            for row in reader:
                wid = int(row['window_id'])
                lat = float(row['latency_ms'])
                windows[wid].append(lat)
        host_data[host] = dict(windows)
    return host_data
