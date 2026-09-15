#!/usr/bin/env python3
"""Kafka Deployment Health Auditor.

Reads multiple diagnostic exports from /app/, identifies configuration
anti-patterns, operational risks, and security gaps across the full
Kafka ecosystem, and produces a structured audit report, partition
reassignment plan, and remediation script.
"""

import json
import re
from collections import defaultdict


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_text(path):
    with open(path) as f:
        return f.read()


def parse_acl_dump(text):
    """Parse kafka-acls.sh --list raw output into structured entries."""
    acls = []
    current_resource = None
    for line in text.strip().split("\n"):
        line = line.strip()
        resource_match = re.match(
            r'Current ACLs for resource `ResourcePattern\('
            r'resourceType=(\w+), name=([^,]+), patternType=(\w+)\)`:',
            line,
        )
        if resource_match:
            current_resource = {
                "resource_type": resource_match.group(1),
                "resource_name": resource_match.group(2),
                "pattern_type": resource_match.group(3),
            }
            continue
        acl_match = re.match(
            r'\(principal=([^,]+), host=([^,]+), '
            r'operation=(\w+), permissionType=(\w+)\)',
            line,
        )
        if acl_match and current_resource:
            acls.append({
                **current_resource,
                "principal": acl_match.group(1),
                "host": acl_match.group(2),
                "operation": acl_match.group(3),
                "permission": acl_match.group(4),
            })
    return acls


# ---------------------------------------------------------------------------
# Individual health checks
# ---------------------------------------------------------------------------

def check_replication_factor(topics):
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
                    "A single broker failure causes complete data loss and "
                    "partition unavailability."
                ),
                "recommendation": (
                    "Increase replication factor to at least 3 using "
                    "kafka-reassign-partitions.sh."
                ),
            })
    return issues


def check_insync_replicas_vs_rf(topics):
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
                    "failure will cause producers using acks=all to receive "
                    "NOT_ENOUGH_REPLICAS and become unable to write."
                ),
                "recommendation": (
                    f"Set min.insync.replicas to {rf - 1} via kafka-configs.sh."
                ),
            })
    return issues


def check_rack_awareness(topics, brokers):
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
                            "Reassign replicas using "
                            "kafka-reassign-partitions.sh to spread across racks."
                        ),
                    })
    return issues


def check_under_replicated(topics):
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
    issues = []
    for t in topics:
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
                    "leader, causing uneven read/write load."
                ),
                "recommendation": (
                    "Run preferred leader election via "
                    "kafka-leader-election.sh --election-type PREFERRED."
                ),
            })
    return issues


def check_consumer_lag_vs_retention(consumer_groups, topics):
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
                        "the consumer can process them — active data loss."
                    ),
                    "recommendation": (
                        f"Increase retention.ms for topic '{topic_name}' "
                        "and/or add more consumers to reduce processing lag."
                    ),
                })
    return issues


def check_producer_acks(producers):
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
                    f"Producer '{p['client_id']}' uses acks=0 "
                    f"(fire-and-forget) for topic(s) {p['target_topics']}. "
                    "Messages may be silently lost without any notification."
                ),
                "recommendation": (
                    "Set acks=all and enable.idempotence=true for reliable "
                    "message delivery."
                ),
            })
    return issues


def check_idle_consumers(consumer_groups, topics):
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


def check_unclean_leader_election(brokers):
    issues = []
    affected = []
    for b in brokers:
        cfg = b.get("config", {})
        val = str(cfg.get("unclean.leader.election.enable", "false")).lower()
        if val == "true":
            affected.append(b["id"])
    if affected:
        issues.append({
            "severity": "CRITICAL",
            "category": "data_integrity",
            "entity_type": "broker",
            "entity": f"brokers-{','.join(str(b) for b in affected)}",
            "description": (
                f"Brokers {affected} have unclean.leader.election.enable=true. "
                "This allows out-of-sync replicas to become leaders, risking "
                "data loss and message divergence across consumers."
            ),
            "recommendation": (
                "Disable unclean.leader.election.enable on all brokers via "
                "kafka-configs.sh --entity-type brokers --alter "
                "--add-config unclean.leader.election.enable=false."
            ),
        })
    return issues


def check_connect_status(connect_data):
    issues = []
    for conn in connect_data.get("connectors", []):
        failed_tasks = [
            t for t in conn.get("tasks", []) if t.get("state") == "FAILED"
        ]
        if failed_tasks:
            task_ids = [str(t["id"]) for t in failed_tasks]
            trace_snippet = ""
            for t in failed_tasks:
                if t.get("trace"):
                    trace_snippet = t["trace"][:200]
                    break
            issues.append({
                "severity": "WARNING",
                "category": "connector_failure",
                "entity_type": "connector",
                "entity": conn["name"],
                "description": (
                    f"Kafka Connect connector '{conn['name']}' has "
                    f"{len(failed_tasks)} failed task(s) (IDs: "
                    f"{', '.join(task_ids)}). {trace_snippet}"
                ),
                "recommendation": (
                    f"Investigate task failure, fix root cause, then restart "
                    f"failed tasks via the Connect REST API."
                ),
            })
        if conn.get("state") == "FAILED":
            issues.append({
                "severity": "CRITICAL",
                "category": "connector_failure",
                "entity_type": "connector",
                "entity": conn["name"],
                "description": (
                    f"Kafka Connect connector '{conn['name']}' is in FAILED "
                    "state."
                ),
                "recommendation": "Investigate and restart the connector.",
            })
    return issues


def check_acl_security(acls):
    issues = []
    for acl in acls:
        if (
            acl.get("resource_type") == "TOPIC"
            and "User:*" in acl.get("principal", "")
            and acl.get("operation") in ("WRITE", "ALL")
            and acl.get("permission") == "ALLOW"
        ):
            issues.append({
                "severity": "WARNING",
                "category": "acl_security",
                "entity_type": "acl",
                "entity": f"acl/{acl['resource_name']}",
                "description": (
                    f"Wildcard principal (User:*) has {acl['operation']} "
                    f"access to topic '{acl['resource_name']}'. Any "
                    "authenticated user can write to this topic, which is a "
                    "significant security risk."
                ),
                "recommendation": (
                    f"Remove wildcard ACL and grant WRITE access only to "
                    f"specific service principals using kafka-acls.sh."
                ),
            })
    return issues


def check_schema_compatibility(schema_registry):
    issues = []
    for subj in schema_registry.get("subjects", []):
        if subj.get("compatibility") == "NONE":
            issues.append({
                "severity": "WARNING",
                "category": "schema_compatibility",
                "entity_type": "schema",
                "entity": subj["subject"],
                "description": (
                    f"Schema Registry subject '{subj['subject']}' has "
                    f"compatibility set to NONE. Schema changes are not "
                    "validated, risking consumer deserialization failures "
                    "on incompatible schema evolution."
                ),
                "recommendation": (
                    "Set compatibility to BACKWARD or FULL via the Schema "
                    "Registry REST API."
                ),
            })
    return issues


# ---------------------------------------------------------------------------
# Partition reassignment plan generation
# ---------------------------------------------------------------------------

def generate_reassignment_plan(topics, brokers):
    broker_rack = {b["id"]: b["rack"] for b in brokers}
    racks = sorted(set(broker_rack.values()))
    rack_to_brokers = defaultdict(list)
    for bid, rack in broker_rack.items():
        rack_to_brokers[rack].append(bid)

    reassignments = []
    for t in topics:
        for pa in t["partition_assignments"]:
            replica_racks = [broker_rack[r] for r in pa["replicas"]]
            if len(replica_racks) != len(set(replica_racks)):
                # Rack violation — generate new assignment
                rf = len(pa["replicas"])
                new_replicas = []
                used_racks = set()
                rack_idx = defaultdict(int)

                for rack in racks:
                    if len(new_replicas) >= rf:
                        break
                    if rack not in used_racks:
                        candidates = rack_to_brokers[rack]
                        broker = candidates[rack_idx[rack] % len(candidates)]
                        new_replicas.append(broker)
                        used_racks.add(rack)
                        rack_idx[rack] += 1

                # If RF > racks, add more from least-used racks
                while len(new_replicas) < rf:
                    for rack in racks:
                        if len(new_replicas) >= rf:
                            break
                        candidates = rack_to_brokers[rack]
                        idx = rack_idx[rack]
                        if idx < len(candidates):
                            broker = candidates[idx]
                            if broker not in new_replicas:
                                new_replicas.append(broker)
                                rack_idx[rack] += 1

                reassignments.append({
                    "topic": t["name"],
                    "partition": pa["partition"],
                    "replicas": new_replicas,
                })

    return {"version": 1, "partitions": reassignments}


# ---------------------------------------------------------------------------
# Remediation script generation
# ---------------------------------------------------------------------------

def generate_remediation(issues, state, acls):
    lines = [
        "#!/bin/bash",
        "# Kafka Cluster Remediation Script",
        "# Generated by Kafka Health Auditor",
        "",
        'BOOTSTRAP_SERVER="${BOOTSTRAP_SERVER:-broker-0.kafka.svc:9092}"',
        "",
    ]

    topic_map = {t["name"]: t for t in state["topics"]}

    for issue in issues:
        lines.append(f"# [{issue['severity']}] {issue['entity']}")
        lines.append(f"# {issue['description'][:120]}")

        if (issue["category"] == "availability"
                and "min.insync.replicas" in issue.get("description", "")):
            entity = issue["entity"]
            t = topic_map.get(entity)
            if t:
                new_val = t["replication_factor"] - 1
                lines.append(
                    f"kafka-configs.sh --bootstrap-server $BOOTSTRAP_SERVER "
                    f"--entity-type topics --entity-name {entity} "
                    f"--alter --add-config min.insync.replicas={new_val}"
                )

        elif (issue["category"] == "data_loss"
              and "retention" in issue.get("description", "").lower()):
            parts = issue["entity"].split("/")
            topic_name = parts[1] if len(parts) > 1 else issue["entity"]
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
                f"# Requires partition reassignment JSON — use "
                f"kafka-reassign-partitions.sh --reassignment-json-file "
                f"reassignment.json --bootstrap-server $BOOTSTRAP_SERVER "
                f"--execute  # to increase RF for {issue['entity']}"
            )

        elif issue["category"] == "rack_awareness":
            lines.append(
                f"kafka-reassign-partitions.sh --bootstrap-server "
                f"$BOOTSTRAP_SERVER --reassignment-json-file "
                f"/app/reassignment.json --execute"
            )

        elif issue["category"] == "data_integrity" and "unclean" in issue.get("description", "").lower():
            for b in state["brokers"]:
                lines.append(
                    f"kafka-configs.sh --bootstrap-server $BOOTSTRAP_SERVER "
                    f"--entity-type brokers --entity-name {b['id']} "
                    f"--alter --add-config "
                    f"unclean.leader.election.enable=false"
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

        elif issue["category"] == "connector_failure":
            lines.append(
                f"# Restart failed connector tasks: "
                f"curl -X POST http://connect-0.svc:8083/connectors/"
                f"{issue['entity']}/restart?includeTasks=true"
            )

        elif issue["category"] == "acl_security":
            resource_name = issue["entity"].replace("acl/", "")
            lines.append(
                f"kafka-acls.sh --bootstrap-server $BOOTSTRAP_SERVER "
                f"--remove --allow-principal 'User:*' "
                f"--operation Write --topic {resource_name}"
            )

        elif issue["category"] == "schema_compatibility":
            lines.append(
                f"# Set schema compatibility via Schema Registry REST API: "
                f"curl -X PUT -H 'Content-Type: application/json' "
                f"-d '{{\"compatibility\":\"BACKWARD\"}}' "
                f"http://schema-registry.svc:8081/config/{issue['entity']}"
            )

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    state = load_json("/app/cluster_state.json")
    jmx = load_json("/app/broker_jmx.json")
    connect = load_json("/app/connect_status.json")
    acl_text = load_text("/app/acl_dump.txt")
    acls = parse_acl_dump(acl_text)

    all_issues = []

    # Cluster state checks
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
    all_issues.extend(check_unclean_leader_election(state["brokers"]))

    # Kafka Connect checks
    all_issues.extend(check_connect_status(connect))

    # ACL security checks
    all_issues.extend(check_acl_security(acls))

    # Schema registry checks
    all_issues.extend(
        check_schema_compatibility(state.get("schema_registry", {}))
    )

    # Assign IDs
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

    with open("/app/audit_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Generate reassignment plan
    reassignment = generate_reassignment_plan(state["topics"], state["brokers"])
    with open("/app/reassignment.json", "w") as f:
        json.dump(reassignment, f, indent=2)

    # Generate remediation script
    remediation = generate_remediation(all_issues, state, acls)
    with open("/app/remediation.sh", "w") as f:
        f.write(remediation)

    print(
        f"Audit complete. Found {len(all_issues)} issues "
        f"({critical_count} critical, {warning_count} warnings)."
    )
    print(f"Cluster health score: {health_score}/100")
    print("Report: /app/audit_report.json")
    print("Reassignment plan: /app/reassignment.json")
    print("Remediation: /app/remediation.sh")


if __name__ == "__main__":
    main()
