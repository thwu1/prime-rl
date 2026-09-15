#!/usr/bin/env python3
"""Convert Prometheus text exposition format files to JSON snapshots."""

import json
import re
from pathlib import Path


def parse_prom_to_json(text, timestamp):
    """Parse Prometheus text format and return structured JSON."""
    counters = {}
    histograms = {}
    gauges = {}
    types = {}

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("# TYPE "):
            parts = line[7:].rsplit(" ", 1)
            if len(parts) == 2:
                types[parts[0]] = parts[1]
            continue
        if line.startswith("#"):
            continue

        m = re.match(
            r'([a-zA-Z_:][a-zA-Z0-9_:]*)\{([^}]*)\}\s+([\d.eE+\-]+)',
            line,
        )
        if not m:
            continue

        full_name = m.group(1)
        labels_raw = m.group(2)
        val = float(m.group(3))

        suffix = ""
        base = full_name
        for s in ("_bucket", "_sum", "_count"):
            if full_name.endswith(s):
                base = full_name[: -len(s)]
                suffix = s
                break

        metric_type = types.get(base, "")

        if metric_type == "counter" and not suffix:
            counters[base] = val
        elif metric_type == "gauge" and not suffix:
            gauges[base] = val
        elif metric_type == "histogram":
            if base not in histograms:
                histograms[base] = {"buckets": [], "sum": 0.0, "count": 0.0}
            if suffix == "_bucket":
                labels = dict(re.findall(r'(\w+)="([^"]*)"', labels_raw))
                le = labels.get("le", "0")
                histograms[base]["buckets"].append({
                    "upper_bound": le if le == "+Inf" else float(le),
                    "cumulative_count": val,
                })
            elif suffix == "_sum":
                histograms[base]["sum"] = val
            elif suffix == "_count":
                histograms[base]["count"] = val

    for h in histograms.values():
        h["buckets"].sort(
            key=lambda b: float("inf") if b["upper_bound"] == "+Inf" else b["upper_bound"]
        )

    return {
        "timestamp": timestamp,
        "counters": counters,
        "histograms": histograms,
        "gauges": gauges,
    }


def main():
    metrics_dir = Path("/app/metrics")
    output_dir = Path("/app/json_snapshots")
    output_dir.mkdir(parents=True, exist_ok=True)

    prom_files = sorted(metrics_dir.glob("*.prom"))
    for pf in prom_files:
        ts = int(pf.stem)
        data = parse_prom_to_json(pf.read_text(), ts)
        out = output_dir / f"{ts}.json"
        with open(out, "w") as f:
            json.dump(data, f, indent=2)

    print(f"Converted {len(prom_files)} scrapes to JSON in {output_dir}")


if __name__ == "__main__":
    main()
