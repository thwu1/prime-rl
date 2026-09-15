#!/usr/bin/env python3
"""
Kafka partition reassignment optimizer.

Reconstructs cluster state from heterogeneous metadata files (broker configs,
kafka-topics --describe output, kafka-log-dirs JSON, disk quotas CSV, and
constraints YAML), then computes an optimal partition reassignment plan.

"""

import csv
import json
import os
import re
import sys
import yaml
from collections import defaultdict
from itertools import combinations


METADATA_DIR = "/app/metadata"


def parse_broker_configs():
    """Parse server-*.properties files for broker topology."""
    brokers = []
    config_dir = os.path.join(METADATA_DIR, "broker_configs")
    for fname in sorted(os.listdir(config_dir)):
        if not fname.endswith(".properties"):
            continue
        path = os.path.join(config_dir, fname)
        props = {}
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    props[k.strip()] = v.strip()
        if "broker.id" in props:
            brokers.append({
                "id": int(props["broker.id"]),
                "rack": props.get("broker.rack", "unknown"),
            })
    return sorted(brokers, key=lambda b: b["id"])


def parse_disk_quotas():
    """Parse disk_quotas.csv for broker capacities (bytes -> GB)."""
    quotas = {}
    path = os.path.join(METADATA_DIR, "disk_quotas.csv")
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            bid = int(row["broker_id"])
            cap_bytes = int(row["capacity_bytes"])
            quotas[bid] = cap_bytes / (1024 ** 3)
    return quotas


def parse_topic_descriptions():
    """Parse kafka-topics --describe output format."""
    topics = {}
    path = os.path.join(METADATA_DIR, "topic_descriptions.txt")
    current_topic = None

    with open(path) as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            if not line.startswith("\t"):
                fields = {}
                for part in line.split("\t"):
                    if ": " in part:
                        k, v = part.split(": ", 1)
                        fields[k.strip()] = v.strip()
                current_topic = fields.get("Topic")
                if current_topic:
                    topics[current_topic] = {
                        "name": current_topic,
                        "replication_factor": int(fields.get("ReplicationFactor", 1)),
                        "partitions": [],
                    }
            else:
                fields = {}
                for part in line.strip().split("\t"):
                    if ": " in part:
                        k, v = part.split(": ", 1)
                        fields[k.strip()] = v.strip()
                if current_topic and "Partition" in fields:
                    replicas = [int(r) for r in fields["Replicas"].split(",")]
                    topics[current_topic]["partitions"].append({
                        "partition": int(fields["Partition"]),
                        "leader": int(fields["Leader"]),
                        "replicas": replicas,
                    })
    return topics


def parse_log_dirs():
    """Parse kafka-log-dirs --describe JSON output for partition sizes in bytes."""
    path = os.path.join(METADATA_DIR, "log_dirs.json")
    with open(path) as f:
        data = json.load(f)

    sizes = {}
    for broker in data["brokers"]:
        for log_dir in broker["logDirs"]:
            for part_entry in log_dir["partitions"]:
                pname = part_entry["partition"]
                match = re.match(r'^(.+)-(\d+)$', pname)
                if match:
                    topic = match.group(1)
                    pid = int(match.group(2))
                    key = (topic, pid)
                    size_gb = part_entry["size"] / (1024 ** 3)
                    if key not in sizes:
                        sizes[key] = size_gb
    return sizes


def parse_constraints():
    """Parse constraints YAML."""
    path = os.path.join(METADATA_DIR, "constraints.yaml")
    with open(path) as f:
        data = yaml.safe_load(f)
    rebal = data.get("rebalancing", {})
    return {
        "max_concurrent_moves": rebal.get("throttling", {}).get("max_concurrent_partition_moves", 10),
        "rack_aware": rebal.get("rack_awareness", {}).get("enabled", True),
        "max_leader_imbalance": rebal.get("balance_limits", {}).get("max_leader_imbalance", 3),
        "max_replica_imbalance": rebal.get("balance_limits", {}).get("max_replica_imbalance", 3),
        "minimize_data_movement": rebal.get("optimization", {}).get("objective", "") == "minimize_data_movement",
    }


def build_cluster_state():
    """Reconstruct cluster state from all metadata files."""
    brokers = parse_broker_configs()
    quotas = parse_disk_quotas()
    topics_data = parse_topic_descriptions()
    sizes = parse_log_dirs()
    constraints = parse_constraints()

    for b in brokers:
        b["disk_capacity_gb"] = quotas.get(b["id"], 0)

    topics_list = []
    for tname in sorted(topics_data.keys()):
        tdata = topics_data[tname]
        parts = []
        for p in sorted(tdata["partitions"], key=lambda x: x["partition"]):
            key = (tname, p["partition"])
            p["size_gb"] = sizes.get(key, 0)
            parts.append(p)
        topics_list.append({
            "name": tname,
            "replication_factor": tdata["replication_factor"],
            "partitions": parts,
        })

    return {
        "cluster_id": "kafka-prod-east-1",
        "brokers": brokers,
        "topics": topics_list,
        "constraints": constraints,
    }


def compute_metrics(assignments, broker_rack, broker_ids):
    """Compute balance metrics for a given set of assignments."""
    num_racks = len(set(broker_rack.values()))
    replica_count = {bid: 0 for bid in broker_ids}
    leader_count = {bid: 0 for bid in broker_ids}
    disk_usage = {bid: 0.0 for bid in broker_ids}
    rack_violations = 0

    for key, val in assignments.items():
        replicas = val["replicas"]
        leader = replicas[0]
        leader_count[leader] += 1
        racks_used = set()
        for bid in replicas:
            replica_count[bid] += 1
            disk_usage[bid] += val["size_gb"]
            racks_used.add(broker_rack[bid])

        ideal_racks = min(val["rf"], num_racks)
        if len(racks_used) < ideal_racks:
            rack_violations += 1

    return {
        "replica_count_per_broker": {str(bid): replica_count[bid] for bid in broker_ids},
        "leader_count_per_broker": {str(bid): leader_count[bid] for bid in broker_ids},
        "disk_usage_gb_per_broker": {str(bid): disk_usage[bid] for bid in broker_ids},
        "rack_awareness_violations": rack_violations,
    }


def solve():
    state = build_cluster_state()

    brokers = state["brokers"]
    topics = state["topics"]
    constraints = state["constraints"]

    broker_ids = sorted([b["id"] for b in brokers])
    broker_rack = {b["id"]: b["rack"] for b in brokers}
    broker_capacity = {b["id"]: b["disk_capacity_gb"] for b in brokers}

    all_racks = sorted(set(broker_rack.values()))
    num_racks = len(all_racks)
    rack_to_brokers = defaultdict(list)
    for bid in broker_ids:
        rack_to_brokers[broker_rack[bid]].append(bid)

    # Build original assignments
    original = {}
    for topic in topics:
        rf = topic["replication_factor"]
        for part in topic["partitions"]:
            key = (topic["name"], part["partition"])
            original[key] = {
                "replicas": list(part["replicas"]),
                "leader": part["leader"],
                "size_gb": part["size_gb"],
                "rf": rf,
            }

    # Compute before metrics
    before_metrics = compute_metrics(original, broker_rack, broker_ids)

    # Phase 1: Determine rack assignments for each partition
    broker_replica_load = {bid: 0 for bid in broker_ids}
    broker_disk_load = {bid: 0.0 for bid in broker_ids}
    broker_leader_load = {bid: 0 for bid in broker_ids}

    new_assignments = {}

    # Sort partitions: RF=3 first (harder to place), then by size descending
    sorted_keys = sorted(original.keys(), key=lambda k: (-original[k]["rf"], -original[k]["size_gb"]))

    for key in sorted_keys:
        val = original[key]
        rf = val["rf"]
        size = val["size_gb"]
        old_replicas = val["replicas"]

        target_rack_count = min(rf, num_racks)

        best_assignment = None
        best_score = float("inf")

        rack_combos = list(combinations(all_racks, target_rack_count))

        for rack_combo in rack_combos:
            if rf > target_rack_count:
                continue

            candidate_replicas = []
            feasible = True

            for rack in rack_combo:
                available = rack_to_brokers[rack]
                best_broker = None
                best_broker_score = float("inf")

                for bid in available:
                    if bid in candidate_replicas:
                        continue
                    if broker_disk_load[bid] + size > broker_capacity[bid]:
                        continue

                    score = broker_replica_load[bid] * 10 + broker_disk_load[bid] / 100
                    if bid not in old_replicas:
                        score += 5
                    if score < best_broker_score:
                        best_broker_score = score
                        best_broker = bid

                if best_broker is None:
                    feasible = False
                    break
                candidate_replicas.append(best_broker)

            if not feasible:
                continue

            movement_cost = sum(size for bid in candidate_replicas if bid not in old_replicas)
            balance_cost = sum(broker_replica_load[bid] for bid in candidate_replicas)
            total_score = movement_cost + balance_cost * 0.5

            if total_score < best_score:
                best_score = total_score
                best_assignment = list(candidate_replicas)

        if best_assignment is None:
            best_assignment = []
            used_racks = set()
            for bid in sorted(broker_ids, key=lambda b: broker_replica_load[b]):
                if bid in best_assignment:
                    continue
                rack = broker_rack[bid]
                if len(used_racks) < target_rack_count and rack in used_racks:
                    continue
                if broker_disk_load[bid] + size > broker_capacity[bid]:
                    continue
                best_assignment.append(bid)
                used_racks.add(rack)
                if len(best_assignment) == rf:
                    break

        for bid in best_assignment:
            broker_replica_load[bid] += 1
            broker_disk_load[bid] += size

        new_assignments[key] = {
            "replicas": best_assignment,
            "size_gb": size,
            "rf": rf,
        }

    # Phase 2: Refine balance through local swaps
    for _iteration in range(50):
        counts = {bid: 0 for bid in broker_ids}
        for val in new_assignments.values():
            for bid in val["replicas"]:
                counts[bid] += 1

        max_broker = max(counts, key=counts.get)
        min_broker = min(counts, key=counts.get)
        if counts[max_broker] - counts[min_broker] <= constraints["max_replica_imbalance"]:
            break

        swapped = False
        for key, val in new_assignments.items():
            if max_broker not in val["replicas"]:
                continue
            if min_broker in val["replicas"]:
                continue

            new_replicas = [min_broker if b == max_broker else b for b in val["replicas"]]
            racks_used = {broker_rack[b] for b in new_replicas}
            ideal_racks = min(val["rf"], num_racks)
            if len(racks_used) < ideal_racks:
                continue

            disk_after = broker_disk_load[min_broker] + val["size_gb"]
            if disk_after > broker_capacity[min_broker]:
                continue

            broker_disk_load[max_broker] -= val["size_gb"]
            broker_disk_load[min_broker] += val["size_gb"]
            broker_replica_load[max_broker] -= 1
            broker_replica_load[min_broker] += 1
            val["replicas"] = new_replicas
            swapped = True
            break

        if not swapped:
            break

    # Phase 3: Assign leaders for balance
    leader_counts = {bid: 0 for bid in broker_ids}
    leader_keys = sorted(new_assignments.keys(), key=lambda k: -new_assignments[k]["size_gb"])

    for key in leader_keys:
        val = new_assignments[key]
        replicas = val["replicas"]
        best_leader = min(replicas, key=lambda b: (leader_counts[b], b))
        leader_counts[best_leader] += 1
        ordered = [best_leader] + [b for b in replicas if b != best_leader]
        val["replicas"] = ordered

    # Phase 4: Refine leader balance
    for _iteration in range(100):
        max_leader = max(leader_counts, key=leader_counts.get)
        min_leader = min(leader_counts, key=leader_counts.get)
        if leader_counts[max_leader] - leader_counts[min_leader] <= constraints["max_leader_imbalance"]:
            break

        swapped = False
        for key in new_assignments:
            val = new_assignments[key]
            if val["replicas"][0] != max_leader:
                continue
            if min_leader not in val["replicas"]:
                continue

            replicas = val["replicas"]
            replicas.remove(min_leader)
            replicas.remove(max_leader)
            val["replicas"] = [min_leader, max_leader] + replicas
            leader_counts[max_leader] -= 1
            leader_counts[min_leader] += 1
            swapped = True
            break

        if not swapped:
            break

    # Phase 5: Generate reassignment plan batches
    moves = []
    for key in sorted(new_assignments.keys()):
        new_replicas = new_assignments[key]["replicas"]
        old_replicas = original[key]["replicas"]
        if new_replicas != old_replicas:
            moves.append({
                "topic": key[0],
                "partition": key[1],
                "replicas": new_replicas,
                "log_dirs": ["any"] * len(new_replicas),
                "size_gb": new_assignments[key]["size_gb"],
            })

    moves.sort(key=lambda m: -m["size_gb"])

    max_batch = constraints["max_concurrent_moves"]
    batches = []
    for i in range(0, len(moves), max_batch):
        batch_moves = moves[i : i + max_batch]
        batches.append(
            {
                "batch_id": len(batches) + 1,
                "partitions": [
                    {
                        "topic": m["topic"],
                        "partition": m["partition"],
                        "replicas": m["replicas"],
                        "log_dirs": m["log_dirs"],
                    }
                    for m in batch_moves
                ],
            }
        )

    # Compute after metrics
    final_for_metrics = {}
    for key, val in original.items():
        final_for_metrics[key] = {
            "replicas": list(new_assignments[key]["replicas"]),
            "size_gb": val["size_gb"],
            "rf": val["rf"],
        }
    after_metrics = compute_metrics(final_for_metrics, broker_rack, broker_ids)

    # Compute movement statistics
    total_replica_moves = 0
    total_data_moved = 0
    for key in new_assignments:
        old_set = set(original[key]["replicas"])
        new_set = set(new_assignments[key]["replicas"])
        added = new_set - old_set
        total_replica_moves += len(added)
        total_data_moved += len(added) * original[key]["size_gb"]

    # Write outputs
    plan = {"version": 1, "batches": batches}

    report = {
        "before": before_metrics,
        "after": after_metrics,
        "total_replica_moves": total_replica_moves,
        "total_data_moved_gb": total_data_moved,
        "num_batches": len(batches),
        "partitions_reassigned": len(moves),
    }

    with open("/app/reassignment_plan.json", "w") as f:
        json.dump(plan, f, indent=2)

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Reassignment plan written: {len(moves)} partitions across {len(batches)} batches")
    print(f"Total replica moves: {total_replica_moves}, data moved: {total_data_moved}GB")
    print(f"Rack violations: {before_metrics['rack_awareness_violations']} -> {after_metrics['rack_awareness_violations']}")
    print(f"Replica counts: {after_metrics['replica_count_per_broker']}")
    print(f"Leader counts: {after_metrics['leader_count_per_broker']}")
    print(f"Disk usage: {after_metrics['disk_usage_gb_per_broker']}")


if __name__ == "__main__":
    solve()
