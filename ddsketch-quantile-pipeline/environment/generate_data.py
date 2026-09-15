#!/usr/bin/env python3
"""Generate deterministic latency data and validation reference for pipeline task."""
import csv
import json
import math
import os
import random

random.seed(20240315)

NUM_HOSTS = 5
NUM_WINDOWS = 20
SAMPLES_PER_HOST_WINDOW = 10000

data_dir = "/app/data"
os.makedirs(data_dir, exist_ok=True)

all_window_data = {}

for host_id in range(NUM_HOSTS):
    rows = []
    for window_id in range(NUM_WINDOWS):
        if window_id not in all_window_data:
            all_window_data[window_id] = []

        mu, sigma = 4.0, 0.5
        samples = []
        if host_id == 3 and window_id == 12:
            for _ in range(SAMPLES_PER_HOST_WINDOW):
                samples.append(round(math.exp(random.gauss(5.1, 0.5)), 4))
        elif host_id == 1 and window_id == 17:
            for _ in range(8000):
                samples.append(round(math.exp(random.gauss(mu, sigma)), 4))
            for _ in range(2000):
                samples.append(round(math.exp(random.gauss(6.0, 0.3)), 4))
        else:
            for _ in range(SAMPLES_PER_HOST_WINDOW):
                samples.append(round(math.exp(random.gauss(mu, sigma)), 4))

        all_window_data[window_id].extend(samples)
        for s in samples:
            rows.append((window_id, s))

    with open(os.path.join(data_dir, "host_{}.csv".format(host_id)), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["window_id", "latency_ms"])
        w.writerows(rows)

config_content = """sketch:
  accuracy: 0.01
  max_buckets: 128

quantiles:
  - 0.5
  - 0.9
  - 0.95
  - 0.99

anomaly_detection:
  threshold: 0.5

slo:
  target_p99_ms: 200.0
  ewma_decay: 0.3

benchmark:
  alpha_values: [0.005, 0.01, 0.02, 0.05]
  max_buckets_values: [64, 128, 256]

data:
  input_dir: /app/data
  output_path: /app/output/report.json
  evaluation_path: /app/output/evaluation.json
  benchmark_db: /app/output/benchmark.db
"""
with open("/app/config.yaml", "w") as f:
    f.write(config_content)


def exact_quantile(data, q):
    sorted_data = sorted(data)
    n = len(sorted_data)
    rank = int(math.ceil(q * n))
    return sorted_data[min(rank - 1, n - 1)]


os.makedirs("/app/expected", exist_ok=True)
validation = {}
for wid in [0, 5, 10, 15]:
    data = all_window_data[wid]
    validation[str(wid)] = {
        "total_count": len(data),
        "exact_quantiles": {
            "0.5": round(exact_quantile(data, 0.5), 4),
            "0.9": round(exact_quantile(data, 0.9), 4),
            "0.95": round(exact_quantile(data, 0.95), 4),
            "0.99": round(exact_quantile(data, 0.99), 4),
        }
    }

with open("/app/expected/reference_quantiles.json", "w") as f:
    json.dump(validation, f, indent=2)
