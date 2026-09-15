#!/usr/bin/env python3
"""
Reference solution: HTB Qdisc Statistics Analyzer.


Reads tc qdisc snapshots, computes traffic metrics, detects anomalies,
and writes a structured report to /app/report.json.
"""
import json
import glob
import os


def load_snapshots(snap_dir):
    snaps = []
    for fpath in sorted(glob.glob(os.path.join(snap_dir, "snapshot_*.json"))):
        with open(fpath) as f:
            snaps.append(json.load(f))
    return snaps


def load_json(path):
    with open(path) as f:
        return json.load(f)


def compute_per_class_metrics(snapshots, hierarchy, config):
    interval = config["snapshot_interval_seconds"]
    sat_thresh = config["saturation_threshold"]
    cong_thresh = config["congestion_drop_rate_threshold"]
    bb_consec = config["bufferbloat_consecutive_snapshots"]

    all_class_ids = list(hierarchy.keys())
    results = {}

    for cid in all_class_ids:
        info = hierarchy[cid]
        rate_bps = info["rate_bps"]

        # Compute per-interval metrics
        throughputs = []
        drop_rates = []
        backlogs = []

        for i in range(len(snapshots)):
            backlogs.append(snapshots[i]["classes"][cid]["backlog"])

        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]["classes"][cid]
            curr = snapshots[i]["classes"][cid]

            delta_bytes = curr["bytes"] - prev["bytes"]
            delta_packets = curr["packets"] - prev["packets"]
            delta_drops = curr["drops"] - prev["drops"]

            tp_bps = delta_bytes * 8 / interval
            throughputs.append(tp_bps)

            total_pkts = delta_packets + delta_drops
            dr = delta_drops / total_pkts if total_pkts > 0 else 0.0
            drop_rates.append(dr)

        avg_tp = sum(throughputs) / len(throughputs) if throughputs else 0
        max_tp = max(throughputs) if throughputs else 0
        avg_dr = sum(drop_rates) / len(drop_rates) if drop_rates else 0
        peak_dr = max(drop_rates) if drop_rates else 0
        avg_bl = sum(backlogs) / len(backlogs) if backlogs else 0
        max_bl = max(backlogs) if backlogs else 0

        is_saturated = any(tp > sat_thresh * rate_bps for tp in throughputs)
        is_congested = any(dr > cong_thresh for dr in drop_rates)

        # Backlog trend detection
        backlog_trend = "stable"
        has_increasing = False
        has_decreasing = False

        inc_count = 0
        for i in range(1, len(backlogs)):
            if backlogs[i] > backlogs[i - 1]:
                inc_count += 1
                if inc_count >= bb_consec:
                    has_increasing = True
            else:
                inc_count = 0

        dec_count = 0
        for i in range(1, len(backlogs)):
            if backlogs[i] < backlogs[i - 1]:
                dec_count += 1
                if dec_count >= bb_consec:
                    has_decreasing = True
            else:
                dec_count = 0

        if has_increasing:
            backlog_trend = "increasing"
        elif has_decreasing:
            backlog_trend = "decreasing"

        results[cid] = {
            "avg_throughput_bps": avg_tp,
            "max_throughput_bps": max_tp,
            "avg_drop_rate": avg_dr,
            "peak_drop_rate": peak_dr,
            "avg_backlog_bytes": avg_bl,
            "max_backlog_bytes": max_bl,
            "is_saturated": is_saturated,
            "is_congested": is_congested,
            "backlog_trend": backlog_trend,
        }

    return results


def compute_hierarchy_analysis(per_class, hierarchy):
    results = {}
    for cid, info in hierarchy.items():
        if info["is_leaf"]:
            continue
        children = [c for c, ci in hierarchy.items() if ci["parent"] == cid]
        leaf_children = [c for c in children if c in per_class]
        children_sum = sum(per_class[c]["avg_throughput_bps"] for c in leaf_children)
        results[cid] = {
            "children_avg_throughput_sum_bps": children_sum,
            "parent_rate_bps": info["rate_bps"],
            "oversubscribed": children_sum > info["rate_bps"],
        }
    return results


def compute_fairness(per_class, hierarchy):
    results = {}
    for cid, info in hierarchy.items():
        if info["is_leaf"]:
            continue
        children = [c for c, ci in hierarchy.items()
                    if ci["parent"] == cid and ci["is_leaf"]]
        if len(children) < 2:
            continue
        children_sorted = sorted(children)
        utilizations = []
        for c in children_sorted:
            rate = hierarchy[c]["rate_bps"]
            avg_tp = per_class[c]["avg_throughput_bps"]
            utilizations.append(avg_tp / rate if rate > 0 else 0)
        n = len(utilizations)
        s = sum(utilizations)
        sq = sum(u * u for u in utilizations)
        jains = (s * s) / (n * sq) if sq > 0 else 1.0
        results[cid] = {
            "jains_index": jains,
            "children_utilizations": utilizations,
        }
    return results


def detect_anomalies(snapshots, per_class, hierarchy, config):
    interval = config["snapshot_interval_seconds"]
    sat_thresh = config["saturation_threshold"]
    cong_thresh = config["congestion_drop_rate_threshold"]
    bb_consec = config["bufferbloat_consecutive_snapshots"]

    anomalies = []

    for cid, info in hierarchy.items():
        rate_bps = info["rate_bps"]

        # Compute per-interval flags
        sat_flags = []
        cong_flags = []
        for i in range(1, len(snapshots)):
            prev = snapshots[i - 1]["classes"][cid]
            curr = snapshots[i]["classes"][cid]
            delta_bytes = curr["bytes"] - prev["bytes"]
            tp_bps = delta_bytes * 8 / interval
            sat_flags.append(tp_bps > sat_thresh * rate_bps)

            delta_drops = curr["drops"] - prev["drops"]
            delta_packets = curr["packets"] - prev["packets"]
            total = delta_packets + delta_drops
            dr = delta_drops / total if total > 0 else 0
            cong_flags.append(dr > cong_thresh)

        # Find contiguous runs for saturation
        _add_runs(anomalies, sat_flags, "saturation", cid)
        _add_runs(anomalies, cong_flags, "congestion", cid)

        # Bufferbloat: contiguous increasing backlog runs
        backlogs = [snapshots[i]["classes"][cid]["backlog"]
                    for i in range(len(snapshots))]
        inc_flags = []
        for i in range(1, len(backlogs)):
            inc_flags.append(backlogs[i] > backlogs[i - 1])

        # Find runs of True of length >= bb_consec
        run_start = None
        run_len = 0
        for idx, flag in enumerate(inc_flags):
            if flag:
                if run_start is None:
                    run_start = idx
                run_len += 1
            else:
                if run_len >= bb_consec:
                    # Snapshot indices: the window starts at run_start (0-indexed
                    # in inc_flags, which corresponds to the transition from
                    # snapshot run_start to run_start+1).
                    # first_snapshot = run_start + 1 (1-based snapshot where
                    # the window begins)
                    # last_snapshot = run_start + run_len + 1 (1-based, last
                    # snapshot in the increasing window)
                    first = run_start + 1
                    last = run_start + run_len + 1
                    anomalies.append({
                        "type": "bufferbloat",
                        "class_id": cid,
                        "first_snapshot": first,
                        "last_snapshot": last,
                    })
                run_start = None
                run_len = 0
        if run_len >= bb_consec:
            first = run_start + 1
            last = run_start + run_len + 1
            anomalies.append({
                "type": "bufferbloat",
                "class_id": cid,
                "first_snapshot": first,
                "last_snapshot": last,
            })

    return anomalies


def _add_runs(anomalies, flags, atype, class_id):
    """Find contiguous True runs in flags and add anomalies.

    flags[i] corresponds to the interval between snapshot i+1 and i+2
    (1-based). So the anomaly snapshot is i+2 (1-based).
    """
    run_start = None
    for idx, flag in enumerate(flags):
        if flag:
            if run_start is None:
                run_start = idx
        else:
            if run_start is not None:
                first = run_start + 2  # 1-based snapshot
                last = idx + 1  # 1-based: last True was idx-1, snapshot = idx-1+2 = idx+1
                anomalies.append({
                    "type": atype,
                    "class_id": class_id,
                    "first_snapshot": first,
                    "last_snapshot": last,
                })
                run_start = None
    if run_start is not None:
        first = run_start + 2
        last = len(flags) + 1  # last flag index is len-1, snapshot = len-1+2 = len+1
        anomalies.append({
            "type": atype,
            "class_id": class_id,
            "first_snapshot": first,
            "last_snapshot": last,
        })


def main():
    snapshots = load_snapshots("/app/snapshots")
    hierarchy = load_json("/app/hierarchy.json")
    config = load_json("/app/config.json")

    per_class = compute_per_class_metrics(snapshots, hierarchy, config)
    hier = compute_hierarchy_analysis(per_class, hierarchy)
    fair = compute_fairness(per_class, hierarchy)
    anomalies = detect_anomalies(snapshots, per_class, hierarchy, config)

    report = {
        "per_class": per_class,
        "hierarchy": hier,
        "fairness": fair,
        "anomalies": anomalies,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Report written to /app/report.json")


if __name__ == "__main__":
    main()
