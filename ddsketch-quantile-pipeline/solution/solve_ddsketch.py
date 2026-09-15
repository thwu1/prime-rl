#!/usr/bin/env python3
"""
DDSketch implementation and analysis pipeline.

Implements the DDSketch algorithm with logarithmic bucket mapping for
relative-error quantile estimation, including a collapsing variant
that bounds memory. Processes multi-host latency data, merges sketches
per time window, computes quantiles, and detects anomalous windows.
"""

import csv
import json
import math
import os


class DDSketch:
    """DDSketch with logarithmic index mapping and relative-error guarantee.

    For relative error parameter alpha:
    - gamma = (1 + alpha) / (1 - alpha)
    - A positive value v maps to bucket key ceil(log(v) / log(gamma))
    - Bucket key k covers values in [gamma^(k-1), gamma^k)
    - Representative value for key k: 2 * gamma^k / (1 + gamma)
    - Max relative error for any value in a bucket: alpha
    """

    def __init__(self, alpha=0.01):
        self.alpha = alpha
        self.gamma = (1.0 + alpha) / (1.0 - alpha)
        self._ln_gamma = math.log(self.gamma)
        self.store = {}
        self.zero_count = 0
        self.count = 0
        self.min_val = float("inf")
        self.max_val = float("-inf")

    def _bucket_key(self, v):
        """Map a positive value to its bucket key."""
        return math.ceil(math.log(v) / self._ln_gamma)

    def _bucket_value(self, key):
        """Return the representative value for a bucket key."""
        return 2.0 * (self.gamma ** key) / (1.0 + self.gamma)

    def add(self, v):
        """Add a non-negative value to the sketch."""
        if v < 0:
            raise ValueError("DDSketch only supports non-negative values")
        self.count += 1
        if v == 0:
            self.zero_count += 1
            self.min_val = min(self.min_val, 0.0)
            return
        self.min_val = min(self.min_val, v)
        self.max_val = max(self.max_val, v)
        key = self._bucket_key(v)
        self.store[key] = self.store.get(key, 0) + 1

    def merge(self, other):
        """Merge another DDSketch into this one. Both must have the same alpha."""
        if abs(self.alpha - other.alpha) > 1e-12:
            raise ValueError("Cannot merge sketches with different alpha values")
        self.count += other.count
        self.zero_count += other.zero_count
        if other.count > 0:
            if other.min_val < self.min_val:
                self.min_val = other.min_val
            if other.max_val > self.max_val:
                self.max_val = other.max_val
        for key, cnt in other.store.items():
            self.store[key] = self.store.get(key, 0) + cnt

    def quantile(self, q):
        """Compute the q-th quantile (0 <= q <= 1)."""
        if self.count == 0:
            raise ValueError("Cannot compute quantile of empty sketch")
        if q <= 0:
            return self.min_val
        if q >= 1:
            return self.max_val

        rank = int(math.ceil(q * self.count))

        # Account for zeros first
        running = self.zero_count
        if running >= rank:
            return 0.0

        for key in sorted(self.store.keys()):
            running += self.store[key]
            if running >= rank:
                return self._bucket_value(key)

        return self.max_val

    def num_buckets(self):
        """Return the number of active buckets."""
        return len(self.store)


class CollapsingDDSketch(DDSketch):
    """DDSketch variant with bounded memory via bucket collapsing.

    When the number of active buckets exceeds max_buckets, the two
    lowest-key buckets are merged (the lower key's count is added to
    the higher key, and the lower key is removed). This increases
    effective error for lower quantiles but bounds memory usage.
    """

    def __init__(self, alpha=0.01, max_buckets=128):
        super().__init__(alpha)
        self.max_buckets = max_buckets

    def _collapse_if_needed(self):
        """Collapse lowest-key buckets until within max_buckets."""
        while len(self.store) > self.max_buckets:
            keys = sorted(self.store.keys())
            low_key = keys[0]
            next_key = keys[1]
            self.store[next_key] += self.store[low_key]
            del self.store[low_key]

    def add(self, v):
        super().add(v)
        if len(self.store) > self.max_buckets:
            self._collapse_if_needed()

    def merge(self, other):
        super().merge(other)
        if len(self.store) > self.max_buckets:
            self._collapse_if_needed()


def main():
    # Load configuration
    with open("/app/config.json") as f:
        config = json.load(f)

    alpha = config["relative_error"]
    quantiles = config["quantiles"]
    max_buckets = config["max_buckets"]
    anomaly_threshold = config["anomaly_threshold"]
    data_dir = config["data_dir"]
    output_path = config["output_path"]

    # Discover host data files
    host_files = sorted(
        f for f in os.listdir(data_dir) if f.endswith(".csv")
    )

    # Build per-host per-window sketches and merge into global window sketches
    window_sketches = {}
    window_collapsed = {}
    total_ingested = 0
    max_buckets_used = 0
    max_collapsed_buckets = 0

    for hf in host_files:
        filepath = os.path.join(data_dir, hf)
        host_sketches = {}
        host_collapsed = {}

        with open(filepath) as f:
            reader = csv.DictReader(f)
            for row in reader:
                wid = int(row["window_id"])
                lat = float(row["latency_ms"])
                total_ingested += 1

                if wid not in host_sketches:
                    host_sketches[wid] = DDSketch(alpha)
                    host_collapsed[wid] = CollapsingDDSketch(alpha, max_buckets)

                host_sketches[wid].add(lat)
                host_collapsed[wid].add(lat)

        # Merge host sketches into global window sketches
        for wid in host_sketches:
            if wid not in window_sketches:
                window_sketches[wid] = DDSketch(alpha)
                window_collapsed[wid] = CollapsingDDSketch(alpha, max_buckets)

            window_sketches[wid].merge(host_sketches[wid])
            bcount = window_sketches[wid].num_buckets()
            if bcount > max_buckets_used:
                max_buckets_used = bcount

            window_collapsed[wid].merge(host_collapsed[wid])
            cbcount = window_collapsed[wid].num_buckets()
            if cbcount > max_collapsed_buckets:
                max_collapsed_buckets = cbcount

    # Compute quantiles per window
    windows_output = {}
    window_p99 = {}

    for wid in sorted(window_sketches.keys()):
        sketch = window_sketches[wid]
        collapsed = window_collapsed[wid]

        q_values = {}
        cq_values = {}
        for q in quantiles:
            q_str = str(q)
            q_values[q_str] = round(sketch.quantile(q), 4)
            cq_values[q_str] = round(collapsed.quantile(q), 4)

        window_p99[wid] = q_values["0.99"]

        windows_output[str(wid)] = {
            "total_count": sketch.count,
            "quantiles": q_values,
            "collapsed_quantiles": cq_values,
        }

    # Detect anomalies via p99 relative change
    anomalies = []
    sorted_windows = sorted(window_sketches.keys())
    for i in range(1, len(sorted_windows)):
        wid = sorted_windows[i]
        prev_wid = sorted_windows[i - 1]
        prev_p99 = window_p99[prev_wid]
        curr_p99 = window_p99[wid]

        if prev_p99 > 0:
            rel_change = abs(curr_p99 - prev_p99) / prev_p99
            if rel_change > anomaly_threshold:
                anomalies.append({
                    "window_id": wid,
                    "quantile": "0.99",
                    "previous_value": prev_p99,
                    "current_value": curr_p99,
                    "relative_change": round(rel_change, 4),
                })

    # Build result
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
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    print("Results written to {}".format(output_path))
    print("Total values ingested: {}".format(total_ingested))
    print("Max buckets (uncollapsed): {}".format(max_buckets_used))
    print("Max buckets (collapsed): {}".format(max_collapsed_buckets))
    print("Anomalies detected: {}".format(len(anomalies)))
    for a in anomalies:
        print("  Window {}: p99 changed {:.1%} ({:.2f} -> {:.2f})".format(
            a["window_id"], a["relative_change"],
            a["previous_value"], a["current_value"]))


if __name__ == "__main__":
    main()
