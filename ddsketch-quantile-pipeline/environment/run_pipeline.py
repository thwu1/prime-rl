#!/usr/bin/env python3
"""Main pipeline orchestrator for latency percentile monitoring."""
import json
import os
import yaml

from sketch_engine import QuantileSketch, CollapsingQuantileSketch
from data_loader import load_host_data
from aggregator import merge_sketches
from reporter import detect_anomalies


def main():
    with open('/app/config.yaml') as f:
        config = yaml.safe_load(f)

    accuracy = config['sketch']['accuracy']
    max_buckets = config['sketch']['max_buckets']
    quantile_levels = config['quantiles']
    anomaly_threshold = config['anomaly_detection']['threshold']
    data_dir = config['data']['input_dir']
    output_path = config['data']['output_path']

    host_data = load_host_data(data_dir)

    window_sketches = {}
    window_collapsed = {}
    total_ingested = 0
    max_buckets_used = 0
    max_collapsed_buckets = 0

    for host, windows in sorted(host_data.items()):
        for wid, latencies in sorted(windows.items()):
            total_ingested += len(latencies)

            host_sketch = QuantileSketch(accuracy)
            host_collapsed = CollapsingQuantileSketch(accuracy, max_buckets)
            for lat in latencies:
                host_sketch.add(lat)
                host_collapsed.add(lat)

            if wid not in window_sketches:
                window_sketches[wid] = QuantileSketch(accuracy)
                window_collapsed[wid] = CollapsingQuantileSketch(accuracy, max_buckets)

            merge_sketches(window_sketches[wid], host_sketch)
            bcount = window_sketches[wid].num_buckets()
            if bcount > max_buckets_used:
                max_buckets_used = bcount

            merge_sketches(window_collapsed[wid], host_collapsed)
            cbcount = window_collapsed[wid].num_buckets()
            if cbcount > max_collapsed_buckets:
                max_collapsed_buckets = cbcount

    windows_output = {}
    window_p99 = {}

    for wid in sorted(window_sketches.keys()):
        sketch = window_sketches[wid]
        collapsed = window_collapsed[wid]

        q_values = {}
        cq_values = {}
        for q in quantile_levels:
            q_str = str(q)
            q_values[q_str] = round(sketch.quantile(q), 4)
            cq_values[q_str] = round(collapsed.quantile(q), 4)

        window_p99[wid] = q_values.get("0.99", 0)

        windows_output[str(wid)] = {
            "total_count": sketch.count,
            "quantiles": q_values,
            "collapsed_quantiles": cq_values,
        }

    anomalies = detect_anomalies(window_p99, anomaly_threshold)

    result = {
        "windows": windows_output,
        "anomalies": anomalies,
        "sketch_stats": {
            "max_buckets_used": max_buckets_used,
            "collapsed_max_buckets_used": max_collapsed_buckets,
            "total_values_ingested": total_ingested,
        },
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print("Report written to", output_path)
    print("Total values ingested:", total_ingested)
    print("Max buckets (uncollapsed):", max_buckets_used)
    print("Max buckets (collapsed):", max_collapsed_buckets)
    print("Anomalies detected:", len(anomalies))
    for a in anomalies:
        print("  Window {}: p99 change {:.4f} ({:.2f} -> {:.2f})".format(
            a["window_id"], a["relative_change"],
            a["previous_value"], a["current_value"]))


if __name__ == '__main__':
    main()
