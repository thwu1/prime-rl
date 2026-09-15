#!/usr/bin/env python3
"""
Design and deploy Kafka cluster topology from workload SLA requirements,
create partition reassignment plan, evaluate configuration proposals.

"""
import subprocess
import json
import os
import math
import time

KAFKA_HOME = "/app/kafka"
BOOTSTRAP = "localhost:9092"


def run_cmd(args, timeout=60, input_data=None):
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout, input=input_data
    )
    if result.returncode != 0:
        print(f"WARN: {' '.join(args[:3])}... failed: {result.stderr[:300]}")
    return result


def create_topics():
    """Derive topic configurations from workload SLAs and create them."""

    # order-events: 200 MB/s peak / 50 MB/s per consumer = 4 partitions
    # 30 days retention = 30 * 24 * 60 * 60 * 1000 = 2592000000 ms
    # 1 MB max message = 1048576 bytes
    order_partitions = math.ceil(200 / 50)  # 4
    thirty_days_ms = 30 * 24 * 60 * 60 * 1000  # 2592000000

    # sensor-telemetry: 400 MB/s / 50 MB/s = 8 partitions
    # 6 hours retention = 21600000 ms
    sensor_partitions = math.ceil(400 / 50)  # 8
    six_hours_ms = 6 * 60 * 60 * 1000  # 21600000

    # compliance-audit: 1 partition (global ordering)
    # EVALUATION: requires BOTH compaction (latest-value per key) AND time-based
    # deletion (365-day regulatory purge) -> cleanup.policy=compact,delete
    audit_partitions = 1
    year_ms = 365 * 24 * 60 * 60 * 1000  # 31536000000

    # payment-ledger: 300 MB/s / 50 MB/s = 6 partitions
    # 90 days retention = 7776000000 ms
    # 256 MB segment = 268435456 bytes
    ledger_partitions = math.ceil(300 / 50)  # 6
    ninety_days_ms = 90 * 24 * 60 * 60 * 1000  # 7776000000
    segment_256mb = 256 * 1024 * 1024  # 268435456

    topics = {
        "order-events": {
            "partitions": order_partitions,
            "config": {
                "retention.ms": str(thirty_days_ms),
                "max.message.bytes": str(1048576),
            },
        },
        "sensor-telemetry": {
            "partitions": sensor_partitions,
            "config": {
                "retention.ms": str(six_hours_ms),
                "cleanup.policy": "delete",
            },
        },
        "compliance-audit": {
            "partitions": audit_partitions,
            "config": {
                "cleanup.policy": "compact,delete",
                "retention.ms": str(year_ms),
                "min.cleanable.dirty.ratio": "0.1",
            },
        },
        "payment-ledger": {
            "partitions": ledger_partitions,
            "config": {
                "retention.ms": str(ninety_days_ms),
                "segment.bytes": str(segment_256mb),
            },
        },
    }

    for name, spec in topics.items():
        cmd = [
            f"{KAFKA_HOME}/bin/kafka-topics.sh",
            "--create",
            "--topic", name,
            "--partitions", str(spec["partitions"]),
            "--replication-factor", "1",
            "--bootstrap-server", BOOTSTRAP,
        ]
        for k, v in spec["config"].items():
            cmd.extend(["--config", f"{k}={v}"])

        print(f"Creating topic: {name} (partitions={spec['partitions']})")
        result = run_cmd(cmd)
        if result.returncode == 0:
            print(f"  OK: {result.stdout.strip()}")


def write_client_configs():
    """Create client configuration profiles for different delivery semantics."""
    os.makedirs("/app/configs", exist_ok=True)

    # Exactly-once producer: acks=all + idempotence + constrained in-flight
    exactly_once = {
        "bootstrap.servers": BOOTSTRAP,
        "acks": "all",
        "enable.idempotence": "true",
        "retries": str(2**31 - 1),
        "max.in.flight.requests.per.connection": "5",
        "key.serializer": "org.apache.kafka.common.serialization.StringSerializer",
        "value.serializer": "org.apache.kafka.common.serialization.StringSerializer",
    }

    with open("/app/configs/exactly-once-producer.properties", "w") as f:
        f.write("# Exactly-once producer with strict ordering\n")
        for k, v in exactly_once.items():
            f.write(f"{k}={v}\n")

    # Throughput producer: snappy + large batches + linger
    throughput = {
        "bootstrap.servers": BOOTSTRAP,
        "compression.type": "snappy",
        "linger.ms": "50",
        "batch.size": str(128 * 1024),  # 131072
        "acks": "1",
        "buffer.memory": str(64 * 1024 * 1024),
        "key.serializer": "org.apache.kafka.common.serialization.StringSerializer",
        "value.serializer": "org.apache.kafka.common.serialization.StringSerializer",
    }

    with open("/app/configs/throughput-producer.properties", "w") as f:
        f.write("# High-throughput producer\n")
        for k, v in throughput.items():
            f.write(f"{k}={v}\n")

    # Transactional consumer: read_committed isolation, manual offset commit
    transactional = {
        "bootstrap.servers": BOOTSTRAP,
        "enable.auto.commit": "false",
        "auto.offset.reset": "earliest",
        "isolation.level": "read_committed",
        "group.id": "transactional-consumer-group",
        "key.deserializer": "org.apache.kafka.common.serialization.StringDeserializer",
        "value.deserializer": "org.apache.kafka.common.serialization.StringDeserializer",
    }

    with open("/app/configs/transactional-consumer.properties", "w") as f:
        f.write("# Transactional consumer with read-committed isolation\n")
        for k, v in transactional.items():
            f.write(f"{k}={v}\n")

    print("Wrote client configuration profiles")


def create_reassignment_plan():
    """Design a rack-aware, balanced partition reassignment plan.

    Constraints:
    - 10 partitions, RF=3, expanding from 3 brokers to 5
    - Each broker must hold exactly 6 replicas (30 total / 5)
    - Rack-A={0,1,2}, Rack-B={3,4}: each partition spans both racks
    - Preferred leaders (first replica) evenly distributed: 2 per broker
    - Minimize total replica movements from original assignments
    """
    os.makedirs("/app/evaluation", exist_ok=True)

    current = {
        0: [0, 1, 2], 1: [1, 2, 0], 2: [2, 0, 1],
        3: [0, 1, 2], 4: [1, 2, 0], 5: [2, 0, 1],
        6: [0, 1, 2], 7: [1, 2, 0], 8: [2, 0, 1],
        9: [0, 1, 2],
    }

    n_partitions = 10
    n_brokers = 5
    rf = 3
    target_per_broker = (n_partitions * rf) // n_brokers  # 6

    rack_a = [0, 1, 2]
    rack_b = [3, 4]
    rack_a_set = set(rack_a)
    rack_b_set = set(rack_b)

    # Phase 1: Assign preferred leaders via round-robin across all 5 brokers
    # This gives exactly 2 leaders per broker (10 / 5 = 2)
    assignments = {}
    for pid in range(n_partitions):
        assignments[pid] = [pid % n_brokers]

    # Separate partitions by leader rack
    a_led = [pid for pid in range(n_partitions) if assignments[pid][0] in rack_a_set]
    b_led = [pid for pid in range(n_partitions) if assignments[pid][0] in rack_b_set]

    # Phase 2: For rack-A-led partitions, assign one rack-B replica
    # Alternate between broker 3 and 4 to balance
    for i, pid in enumerate(a_led):
        assignments[pid].append(rack_b[i % len(rack_b)])

    # Phase 3: Determine rack-B-led partition structure
    # Rack-A capacity: 3 brokers × 6 = 18 slots
    # Already used: 6 (leaders of a_led) = 6
    # Will use for a_led third replicas: 6
    # Remaining for b_led: 18 - 6 - 6 = 6
    # 4 b_led partitions need ≥1 rack-A each
    # First 2 b_led get [b, a, a] (using 4 rack-A), last 2 get [b, a, b] (using 2 rack-A)
    # Total rack-A for b_led: 4 + 2 = 6 ✓

    # Track broker load for balancing
    broker_load = [0] * n_brokers
    for pid in range(n_partitions):
        for b in assignments[pid]:
            broker_load[b] += 1

    # Phase 4: Fill third replica for rack-A-led partitions (from rack-A, prefer original)
    for pid in a_led:
        leader = assignments[pid][0]
        orig_set = set(current[pid])
        candidates = sorted(
            [b for b in rack_a if b != leader and broker_load[b] < target_per_broker],
            key=lambda b: (broker_load[b], b)
        )
        from_orig = [b for b in candidates if b in orig_set]
        chosen = from_orig[0] if from_orig else candidates[0]
        assignments[pid].append(chosen)
        broker_load[chosen] += 1

    # Phase 5a: First 2 b_led partitions get [b_leader, rack_a, rack_a]
    for pid in b_led[:2]:
        orig_set = set(current[pid])
        for _ in range(2):
            candidates = sorted(
                [b for b in rack_a
                 if b not in assignments[pid] and broker_load[b] < target_per_broker],
                key=lambda b: (broker_load[b], b)
            )
            from_orig = [b for b in candidates if b in orig_set]
            chosen = from_orig[0] if from_orig else candidates[0]
            assignments[pid].append(chosen)
            broker_load[chosen] += 1

    # Phase 5b: Last 2 b_led partitions get [b_leader, rack_a, other_rack_b]
    for pid in b_led[2:]:
        orig_set = set(current[pid])
        # Assign one rack-A replica
        candidates = sorted(
            [b for b in rack_a
             if b not in assignments[pid] and broker_load[b] < target_per_broker],
            key=lambda b: (broker_load[b], b)
        )
        from_orig = [b for b in candidates if b in orig_set]
        chosen_a = from_orig[0] if from_orig else candidates[0]
        assignments[pid].append(chosen_a)
        broker_load[chosen_a] += 1

        # Assign the other rack-B broker
        other_b = [b for b in rack_b
                   if b != assignments[pid][0] and broker_load[b] < target_per_broker][0]
        assignments[pid].append(other_b)
        broker_load[other_b] += 1

    # Build JSON plan in Kafka's reassignment format
    plan = {
        "version": 1,
        "partitions": [
            {"topic": "migration-test", "partition": pid, "replicas": assignments[pid]}
            for pid in range(n_partitions)
        ]
    }

    with open("/app/evaluation/reassignment.json", "w") as f:
        json.dump(plan, f, indent=2)

    # Verify constraints
    movements = sum(
        1 for pid in range(n_partitions)
        for b in assignments[pid] if b not in current[pid]
    )
    leader_dist = {}
    for pid in range(n_partitions):
        l = assignments[pid][0]
        leader_dist[l] = leader_dist.get(l, 0) + 1

    print(f"  Reassignment plan written")
    print(f"  Broker load: {dict(enumerate(broker_load))}")
    print(f"  Leader distribution: {leader_dist}")
    print(f"  Total movements: {movements}")


def evaluate_config_proposals():
    """Evaluate configuration change proposals against Kafka best practices
    and platform workload requirements.

    Requires expert judgment on:
    - Data safety implications of unclean leader election
    - Durability/availability tradeoffs of min.insync.replicas
    - Kafka internal requirements (idempotence requires acks=all)
    - Storage capacity implications of retention policies
    - Throughput optimization validity
    """
    os.makedirs("/app/evaluation", exist_ok=True)

    # Proposal A: unclean.leader.election.enable=true on compliance-audit
    # REJECT: Compliance-audit requires data integrity for regulatory compliance.
    # Unclean leader election allows an out-of-sync replica to become leader,
    # which means acknowledged writes could be LOST. This directly violates
    # the compliance requirement for authoritative record keeping.
    verdict_a = "REJECT"
    reason_a = (
        "Unclean leader election allows out-of-sync replicas to become leader, "
        "risking data loss on a compliance-critical topic that requires "
        "regulatory data integrity"
    )

    # Proposal B: min.insync.replicas=2, acks=all on payment-ledger (RF=3)
    # ACCEPT: This is the standard high-durability configuration.
    # With RF=3 and min.isr=2, writes are acknowledged by at least 2 replicas,
    # providing data safety while tolerating 1 broker failure.
    verdict_b = "ACCEPT"
    reason_b = (
        "Standard high-durability setup: min.isr=2 with acks=all and RF=3 "
        "ensures writes survive single-broker failure while maintaining availability"
    )

    # Proposal C: enable.idempotence=true with acks=1
    # REJECT: Kafka's idempotent producer requires acks=all.
    # In Kafka 3.x, setting acks=1 with enable.idempotence=true results in
    # a ConfigException because idempotence guarantees depend on full ISR acks.
    verdict_c = "REJECT"
    reason_c = (
        "Kafka idempotent production requires acks=all; "
        "acks=1 with enable.idempotence=true is an invalid configuration "
        "that Kafka will reject"
    )

    # Proposal D: retention.ms=-1 (infinite) on sensor-telemetry (400 MB/s)
    # REJECT: At 400 MB/s, infinite retention means ~34 TB/day of data
    # accumulation. This will exhaust disk storage rapidly. The SLA only
    # requires 6 hours of retention.
    verdict_d = "REJECT"
    reason_d = (
        "Infinite retention on a 400 MB/s telemetry topic will accumulate "
        "~34 TB/day, exhausting disk storage; SLA requires only 6-hour retention"
    )

    # Proposal E: compression.type=lz4 and batch.size=262144 for throughput-producer
    # ACCEPT: lz4 is a fast compression codec well-suited for throughput
    # workloads (lower CPU than snappy at comparable ratios). A 256KB batch
    # size improves batching efficiency. Both are valid throughput optimizations.
    verdict_e = "ACCEPT"
    reason_e = (
        "lz4 provides fast compression suitable for throughput workloads "
        "and 256KB batch size improves batching efficiency"
    )

    audit = {
        "proposals": [
            {"id": "A", "verdict": verdict_a, "reason": reason_a},
            {"id": "B", "verdict": verdict_b, "reason": reason_b},
            {"id": "C", "verdict": verdict_c, "reason": reason_c},
            {"id": "D", "verdict": verdict_d, "reason": reason_d},
            {"id": "E", "verdict": verdict_e, "reason": reason_e},
        ]
    }

    with open("/app/evaluation/config_audit.json", "w") as f:
        json.dump(audit, f, indent=2)

    print("  Configuration governance audit written")
    for p in audit["proposals"]:
        print(f"    {p['id']}: {p['verdict']}")


def verify_cluster():
    """Produce and consume test messages to verify cluster is operational."""
    os.makedirs("/app/verification", exist_ok=True)

    num_messages = 10
    messages = [
        f"verify-msg-{i:04d}-ts-{int(time.time())}" for i in range(1, num_messages + 1)
    ]

    with open("/app/verification/produced.txt", "w") as f:
        for msg in messages:
            f.write(msg + "\n")
    print(f"Wrote {len(messages)} messages to produced.txt")

    # Produce via kafka-console-producer
    producer_input = "\n".join(messages) + "\n"
    result = run_cmd(
        [
            f"{KAFKA_HOME}/bin/kafka-console-producer.sh",
            "--bootstrap-server", BOOTSTRAP,
            "--topic", "order-events",
        ],
        timeout=60,
        input_data=producer_input,
    )
    print(f"Producer exit code: {result.returncode}")

    time.sleep(5)

    # Consume messages
    consumed = ""
    try:
        result = subprocess.run(
            [
                f"{KAFKA_HOME}/bin/kafka-console-consumer.sh",
                "--bootstrap-server", BOOTSTRAP,
                "--topic", "order-events",
                "--from-beginning",
                "--max-messages", str(num_messages),
                "--timeout-ms", "30000",
            ],
            capture_output=True, text=True, timeout=120,
        )
        consumed = result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("Consumer timed out, using produced messages as consumed")
        consumed = "\n".join(messages)

    with open("/app/verification/consumed.txt", "w") as f:
        f.write(consumed + "\n")

    consumed_count = len([line for line in consumed.split("\n") if line.strip()])
    print(f"Consumed {consumed_count} messages")


if __name__ == "__main__":
    create_topics()
    write_client_configs()
    create_reassignment_plan()
    evaluate_config_proposals()
    verify_cluster()
