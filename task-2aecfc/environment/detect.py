#!/usr/bin/env python3
"""Detect cascading cluster failures from per-cluster metrics."""
import json
import yaml
import os

METRICS_PATH = "/tmp/pipeline/metrics.json"
ALERTS_CONFIG = "/app/config/alerts.yaml"
OUTPUT_DIR = "/tmp/pipeline"


def main():
    with open(METRICS_PATH) as f:
        metrics = json.load(f)
    with open(ALERTS_CONFIG) as f:
        config = yaml.safe_load(f)

    threshold = config["failure_detection"]["error_rate_threshold"]
    consecutive_needed = config["failure_detection"]["consecutive_seconds"]
    max_t = metrics["max_timestamp"]
    clusters = metrics["clusters"]

    failures = []
    for cluster in clusters:
        consecutive = 0
        detected_at = None

        for t in range(max_t + 1):
            t_str = str(t)
            if t_str in metrics["per_cluster"] and cluster in metrics["per_cluster"][t_str]:
                data = metrics["per_cluster"][t_str][cluster]
                reqs = data["requests"]
                errs = data["errors"]
                if reqs > 0 and (errs / reqs) > threshold:
                    consecutive += 1
                    if consecutive >= consecutive_needed:
                        detected_at = t
                        break
                else:
                    consecutive = 0
            else:
                consecutive = 0

        if detected_at is not None:
            failures.append({
                "cluster": cluster,
                "detected_at_s": detected_at,
                "effective_from_s": detected_at + 1,
            })

    failures.sort(key=lambda x: x["detected_at_s"])
    cascade_seq = [f["cluster"] for f in failures]

    result = {
        "cluster_failures": failures,
        "cascade_sequence": cascade_seq,
    }

    with open(os.path.join(OUTPUT_DIR, "cascade.json"), "w") as f:
        json.dump(result, f, indent=2)

    print(f"Detected {len(failures)} failures, cascade: {cascade_seq}")


if __name__ == "__main__":
    main()
