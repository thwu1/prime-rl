#!/usr/bin/env python3
"""
Evaluate all five defense strategies against traffic capture and produce
/app/output/evaluation.json with per-strategy metrics and best strategy.
"""

import json
import os
import subprocess


STRATEGIES = [
    "subnet_block",
    "dns_src_block",
    "udp_block_all",
    "combined_basic",
    "dns_payload_filter",
]


def evaluate_all():
    results = {}
    best_strategy = None
    best_f1 = -1.0

    for name in STRATEGIES:
        strategy_path = "/app/strategies/{}.json".format(name)
        output_path = "/tmp/eval_{}.json".format(name)

        subprocess.run([
            "python3", "/app/evaluate.py",
            "--pcap", "/app/captures/traffic.pcap",
            "--strategy", strategy_path,
            "--classification", "/app/output/classification.json",
            "--output", output_path
        ], check=True)

        with open(output_path) as f:
            result = json.load(f)

        metrics = result["metrics"]
        results[name] = metrics

        print("  {}: precision={:.4f} recall={:.4f} f1={:.4f} (tp={} fp={} fn={} tn={})".format(
            name, metrics["precision"], metrics["recall"], metrics["f1"],
            metrics["tp"], metrics["fp"], metrics["fn"], metrics["tn"]))

        if metrics["f1"] > best_f1:
            best_f1 = metrics["f1"]
            best_strategy = name

    evaluation = {
        "strategies": results,
        "best_strategy": best_strategy,
        "deficiency_count": results[best_strategy]["fn"]
    }

    os.makedirs("/app/output", exist_ok=True)
    with open("/app/output/evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)

    print("\nBest strategy: {} (f1={:.4f})".format(best_strategy, best_f1))
    print("Deficiency count: {} attack packets missed".format(
        evaluation["deficiency_count"]))


if __name__ == "__main__":
    evaluate_all()
