#!/usr/bin/env python3
"""Kafka Cluster Health Analyzer.

Reads /app/cluster_state.json, detects configuration anti-patterns and
operational issues, and produces /app/report.json and /app/remediation.sh.
"""

import json
from collections import defaultdict


def load_cluster_state(path="/app/cluster_state.json"):
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Individual health checks
# ---------------------------------------------------------------------------

def check_replication_factor(topics):
    """Topics with RF=1 have no fault tolerance."""
    issues = []
    for t in topics:
        if t["replication_factor"] == 1:
            issues.append({
                "severity": "CRITICAL",
                "category": "replication",
                "entity_type": "topic",
                "entity": t["name"],
                "description": (
                    f"Topic '{t['name']}' has replication.factor=1. "
                    "A single broker failure causes data loss and partition "
                    "unavailability."
                ),
                "recommendation": (
                    "Increase replication factor to at least 3 using "
                    "kafka-reassign-partitions.sh."
                ),
            })
    return issues


def check_insync_replicas_vs_rf(topics):
    """min.insync.replicas >= RF blocks writes on any broker failure."""
    issues = []
    for t in topics:
        rf = t["replication_factor"]
        min_isr = t.get("config", {}).get("min.insync.replicas")
        if min_isr is not None and int(min_isr) >= rf:
            issues.append({
                "severity": "CRITICAL",
                "category": "availability",
                "entity_type": "topic",
                "entity": t["name"],
                "description": (
                    f"Topic '{t['name']}' has min.insync.replicas={min_isr} "
                    f"which equals replication.factor={rf}. Any single broker "
                    "failure will cause producers to receive "
                    "NOT_ENOUGH_REPLICAS and be unable to write."
                ),
                "recommendation": (
                    f"Set min.insync.replicas to {rf - 1} via kafka-configs.sh."
                ),
            })
    return issues


def check_rack_awareness(topics, brokers):
    """Detect partitions with multiple replicas on the same rack."""
    broker_rack = {b["id"]: b["rack"] for b in brokers}
    issues = []
    for t in topics:
        for pa in t["partition_assignments"]:
            rack_counts = defaultdict(list)
            for rid in pa["replicas"]:
                rack_counts[broker_rack.get(rid, "unknown")].append(rid)
            for rack, bids in rack_counts.items():
                if len(bids) > 1:
                    issues.append({
                        "severity": "WARNING",
                        "category": "rack_awareness",
                        "entity_type": "topic_partition",
                        "entity": f"{t['name']}-{pa['partition']}",
                        "description": (
                            f"Topic '{t['name']}' partition {pa['partition']} "
                            f"has {len(bids)} replicas (brokers {bids}) on "
                            f"rack '{rack}'. A rack failure would lose "
                            "multiple replicas simultaneously."
                        ),
                        "recommendation": (
                            "Reassign replicas to spread across racks using "
                            "kafka-reassign-partitions.sh."
                        ),
                    })
    return issues


def check_under_replicated(topics):
    """Detect partitions where ISR < replica set."""
    issues = []
    for t in topics:
        for pa in t["partition_assignments"]:
            if len(pa["isr"]) < len(pa["replicas"]):
                out = sorted(set(pa["replicas"]) - set(pa["isr"]))
                issues.append({
                    "severity": "WARNING",
                    "category": "under_replicated",
                    "entity_type": "topic_partition",
                    "entity": f"{t['name']}-{pa['partition']}",
                    "description": (
                        f"Topic '{t['name']}' partition {pa['partition']} is "
                        f"under-replicated: ISR has {len(pa['isr'])} of "
                        f"{len(pa['replicas'])} replicas. Brokers {out} are "
                        "out of sync."
                    ),
                    "recommendation": (
                        "Investigate broker health and network connectivity "
                        "for out-of-sync replicas."
                    ),
                })
    return issues


def check_leader_imbalance(topics, brokers):
    """Detect topics where leader distribution is heavily skewed."""
    issues = []
    for t in topics:
        # Compute which brokers host replicas for this topic
        brokers_with_replicas = set()
        for pa in t["partition_assignments"]:
            brokers_with_replicas.update(pa["replicas"])

        if len(brokers_with_replicas) <= 2:
            continue

        leader_counts = defaultdict(int)
        for bid in brokers_with_replicas:
            leader_counts[bid] = 0
        for pa in t["partition_assignments"]:
            leader_counts[pa["leader"]] += 1

        max_l = max(leader_counts[b] for b in brokers_with_replicas)
        ideal = t["partitions"] / len(brokers_with_replicas)
        zero_leaders = sum(
            1 for b in brokers_with_replicas if leader_counts[b] == 0
        )

        # Only flag when the topic has enough partitions that better
        # distribution is actually possible.
        if (
            t["partitions"] >= len(brokers_with_replicas)
            and max_l > 2 * ideal
            and zero_leaders >= 2
        ):
            dist = {b: leader_counts[b] for b in sorted(brokers_with_replicas)}
            issues.append({
                "severity": "WARNING",
                "category": "leader_imbalance",
                "entity_type": "topic",
                "entity": t["name"],
                "description": (
                    f"Topic '{t['name']}' has heavily skewed leader "
                    f"distribution. Leader counts per broker: {dist}. "
                    f"{zero_leaders} brokers with replicas never serve as "
                    "leader, causing uneven load."
                ),
                "recommendation": (
                    "Run preferred leader election via "
                    "kafka-leader-election.sh --election-type PREFERRED "
                    "or reassign partitions to balance leaders."
                ),
            })
    return issues


def check_consumer_lag_vs_retention(consumer_groups, topics):
    """Consumer lag_ms exceeding topic retention.ms means data loss."""
    topic_retention = {}
    for t in topics:
        topic_retention[t["name"]] = int(
            t.get("config", {}).get("retention.ms", 604800000)
        )

    issues = []
    seen = set()
    for cg in consumer_groups:
        for lag in cg.get("partition_lag", []):
            topic_name = lag["topic"]
            lag_ms = lag.get("lag_ms")
            if lag_ms is None:
                continue
            retention = topic_retention.get(topic_name)
            if retention is None:
                continue
            key = (cg["name"], topic_name)
            if lag_ms > retention and key not in seen:
                seen.add(key)
                max_lag = max(
                    l.get("lag_ms", 0)
                    for l in cg["partition_lag"]
                    if l["topic"] == topic_name and l.get("lag_ms") is not None
                )
                issues.append({
                    "severity": "CRITICAL",
                    "category": "data_loss",
                    "entity_type": "consumer_group",
                    "entity": f"{cg['name']}/{topic_name}",
                    "description": (
                        f"Consumer group '{cg['name']}' lag on topic "
                        f"'{topic_name}' exceeds the topic's retention period. "
                        f"Max consumer lag: {max_lag}ms vs retention: "
                        f"{retention}ms. Messages are being deleted before "
                        "the consumer can process them -- active data loss."
                    ),
                    "recommendation": (
                        f"Increase retention.ms for topic '{topic_name}' "
                        "and/or add more consumers to reduce processing lag."
                    ),
                })
    return issues


def check_producer_acks(producers):
    """Producers with acks=0 risk silent data loss."""
    issues = []
    for p in producers:
        acks = str(p["config"].get("acks", ""))
        if acks == "0":
            issues.append({
                "severity": "CRITICAL",
                "category": "durability",
                "entity_type": "producer",
                "entity": p["client_id"],
                "description": (
                    f"Producer '{p['client_id']}' uses acks=0 (fire-and-forget)"
                    f" for topic(s) {p['target_topics']}. Messages may be "
                    "silently lost without any notification."
                ),
                "recommendation": (
                    "Set acks=all and enable.idempotence=true for reliable "
                    "message delivery."
                ),
            })
    return issues


def check_idle_consumers(consumer_groups, topics):
    """More consumers than partitions wastes resources."""
    topic_parts = {t["name"]: t["partitions"] for t in topics}
    issues = []
    for cg in consumer_groups:
        total_parts = sum(
            topic_parts.get(t, 0) for t in cg.get("subscribed_topics", [])
        )
        num_members = len(cg.get("members", []))
        idle = num_members - total_parts
        if idle > 0:
            issues.append({
                "severity": "WARNING",
                "category": "resource_waste",
                "entity_type": "consumer_group",
                "entity": cg["name"],
                "description": (
                    f"Consumer group '{cg['name']}' has {num_members} "
                    f"consumers but only {total_parts} total partitions across "
                    f"subscribed topics. {idle} consumer(s) are idle and "
                    "wasting resources."
                ),
                "recommendation": (
                    f"Reduce consumer count to at most {total_parts} or "
                    "increase partitions on subscribed topics."
                ),
            })
    return issues


# ---------------------------------------------------------------------------
# Remediation script generation
# ---------------------------------------------------------------------------

def generate_remediation(issues, state):
    lines = [
        "#!/bin/bash",
        "# Kafka Cluster Remediation Script",
        "# Generated by Kafka Health Analyzer",
        "",
        'BOOTSTRAP_SERVER="broker-0.kafka.svc:9092"',
        "",
    ]

    topic_map = {t["name"]: t for t in state["topics"]}

    for issue in issues:
        lines.append(f"# [{issue['severity']}] {issue['entity']}")
        lines.append(f"# {issue['description'][:120]}")

        if issue["category"] == "availability" and "min.insync.replicas" in issue.get("description", ""):
            entity = issue["entity"]
            t = topic_map.get(entity)
            if t:
                new_val = t["replication_factor"] - 1
                lines.append(
                    f"kafka-configs.sh --bootstrap-server $BOOTSTRAP_SERVER "
                    f"--entity-type topics --entity-name {entity} "
                    f"--alter --add-config min.insync.replicas={new_val}"
                )

        elif issue["category"] == "data_loss" and "retention" in issue.get("description", "").lower():
            topic_name = issue["entity"].split("/")[1] if "/" in issue["entity"] else issue["entity"]
            lines.append(
                f"kafka-configs.sh --bootstrap-server $BOOTSTRAP_SERVER "
                f"--entity-type topics --entity-name {topic_name} "
                f"--alter --add-config retention.ms=604800000"
            )

        elif issue["category"] == "leader_imbalance":
            lines.append(
                f"kafka-leader-election.sh --bootstrap-server $BOOTSTRAP_SERVER "
                f"--election-type PREFERRED --topic {issue['entity']}"
            )

        elif issue["category"] == "replication":
            lines.append(
                f"# Requires partition reassignment JSON -- use "
                f"kafka-reassign-partitions.sh --reassignment-json-file "
                f"<plan.json> --execute to increase RF for {issue['entity']}"
            )

        elif issue["category"] == "rack_awareness":
            lines.append(
                f"# Requires partition reassignment to fix rack placement "
                f"for {issue['entity']}"
            )

        elif issue["category"] == "durability":
            lines.append(
                f"# Update producer client '{issue['entity']}' config: "
                f"acks=all, enable.idempotence=true"
            )

        elif issue["category"] == "resource_waste":
            lines.append(
                f"# Scale down consumer group '{issue['entity']}' or add "
                f"partitions to subscribed topics"
            )

        elif issue["category"] == "under_replicated":
            lines.append(
                f"# Investigate broker health for {issue['entity']}"
            )

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    state = load_cluster_state()

    all_issues = []
    all_issues.extend(check_replication_factor(state["topics"]))
    all_issues.extend(check_insync_replicas_vs_rf(state["topics"]))
    all_issues.extend(check_rack_awareness(state["topics"], state["brokers"]))
    all_issues.extend(check_under_replicated(state["topics"]))
    all_issues.extend(check_leader_imbalance(state["topics"], state["brokers"]))
    all_issues.extend(
        check_consumer_lag_vs_retention(state["consumer_groups"], state["topics"])
    )
    all_issues.extend(check_producer_acks(state["producers"]))
    all_issues.extend(
        check_idle_consumers(state["consumer_groups"], state["topics"])
    )

    for i, issue in enumerate(all_issues):
        issue["id"] = f"ISS-{i + 1:03d}"

    critical_count = sum(1 for x in all_issues if x["severity"] == "CRITICAL")
    warning_count = sum(1 for x in all_issues if x["severity"] == "WARNING")
    health_score = max(0, 100 - 15 * critical_count - 5 * warning_count)

    report = {
        "cluster_id": state["cluster_id"],
        "total_issues": len(all_issues),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "health_score": health_score,
        "issues": all_issues,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    remediation = generate_remediation(all_issues, state)
    with open("/app/remediation.sh", "w") as f:
        f.write(remediation)

    print(
        f"Analysis complete. Found {len(all_issues)} issues "
        f"({critical_count} critical, {warning_count} warnings)."
    )
    print(f"Cluster health score: {health_score}/100")
    print("Report: /app/report.json")
    print("Remediation: /app/remediation.sh")


if __name__ == "__main__":
    main()
