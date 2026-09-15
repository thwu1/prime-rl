"""
Test suite for Kafka cluster migration and governance design task.

"""
import subprocess
import socket
import json
import os
import re
import pytest

KAFKA_HOME = "/app/kafka"
BOOTSTRAP_SERVER = "localhost:9092"


def kafka_is_reachable(timeout=5):
    """Check if Kafka broker port is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("localhost", 9092))
        sock.close()
        return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def run_kafka_topics(args, timeout=30):
    """Run kafka-topics.sh with given args."""
    cmd = [f"{KAFKA_HOME}/bin/kafka-topics.sh", "--bootstrap-server", BOOTSTRAP_SERVER] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_kafka_configs(args, timeout=30):
    """Run kafka-configs.sh with given args."""
    cmd = [f"{KAFKA_HOME}/bin/kafka-configs.sh", "--bootstrap-server", BOOTSTRAP_SERVER] + args
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def get_topic_info(topic_name):
    result = run_kafka_topics(["--describe", "--topic", topic_name])
    return result.stdout


def get_topic_config(topic_name):
    result = run_kafka_configs(
        ["--entity-type", "topics", "--entity-name", topic_name, "--describe"]
    )
    return result.stdout


def get_combined_topic_info(topic_name):
    return get_topic_info(topic_name) + "\n" + get_topic_config(topic_name)


def read_properties(filepath):
    props = {}
    if not os.path.exists(filepath):
        return props
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    props[key.strip()] = value.strip()
    return props


# ============================================================
# Broker Tests
# ============================================================


class TestBroker:
    def test_broker_port_reachable(self):
        assert kafka_is_reachable(), "Cannot connect to Kafka broker on localhost:9092"

    def test_broker_process_running(self):
        result = subprocess.run(
            ["pgrep", "-f", "kafka.Kafka"], capture_output=True, text=True
        )
        assert result.returncode == 0, "No Kafka broker process found"

    def test_can_list_topics(self):
        result = run_kafka_topics(["--list"])
        assert result.returncode == 0, f"Failed to list topics: {result.stderr}"


# ============================================================
# Topic: order-events (200 MB/s / 50 MB/s = 4 partitions, 30d retention, 1MB max msg)
# ============================================================


class TestOrderEventsTopic:
    def test_exists(self):
        info = get_topic_info("order-events")
        assert "order-events" in info, "Topic 'order-events' not found"

    def test_partition_count(self):
        info = get_topic_info("order-events")
        match = re.search(r"PartitionCount:\s*(\d+)", info)
        assert match, "Could not parse PartitionCount for order-events"
        assert int(match.group(1)) == 4, f"Expected 4 partitions, got {match.group(1)}"

    def test_retention_30_days(self):
        combined = get_combined_topic_info("order-events")
        # 30 days = 30 * 24 * 60 * 60 * 1000 = 2592000000
        assert "2592000000" in combined, (
            "retention.ms should be 2592000000 (30 days) for order-events"
        )

    def test_max_message_bytes(self):
        combined = get_combined_topic_info("order-events")
        # 1 MB = 1048576
        assert "1048576" in combined, (
            "max.message.bytes should be 1048576 (1MB) for order-events"
        )


# ============================================================
# Topic: sensor-telemetry (400 MB/s / 50 MB/s = 8 partitions, 6h retention, delete)
# ============================================================


class TestSensorTelemetryTopic:
    def test_exists(self):
        info = get_topic_info("sensor-telemetry")
        assert "sensor-telemetry" in info, "Topic 'sensor-telemetry' not found"

    def test_partition_count(self):
        info = get_topic_info("sensor-telemetry")
        match = re.search(r"PartitionCount:\s*(\d+)", info)
        assert match and int(match.group(1)) == 8, (
            "sensor-telemetry should have 8 partitions"
        )

    def test_retention_6_hours(self):
        combined = get_combined_topic_info("sensor-telemetry")
        # 6 hours = 6 * 60 * 60 * 1000 = 21600000
        assert "21600000" in combined, (
            "retention.ms should be 21600000 (6 hours) for sensor-telemetry"
        )


# ============================================================
# Topic: compliance-audit (1 partition, compact+delete, 365d retention, dirty ratio 0.1)
# ============================================================


class TestComplianceAuditTopic:
    def test_exists(self):
        info = get_topic_info("compliance-audit")
        assert "compliance-audit" in info, "Topic 'compliance-audit' not found"

    def test_partition_count(self):
        info = get_topic_info("compliance-audit")
        match = re.search(r"PartitionCount:\s*(\d+)", info)
        assert match and int(match.group(1)) == 1, (
            "compliance-audit should have 1 partition for global ordering"
        )

    def test_cleanup_policy_compact_and_delete(self):
        config = get_topic_config("compliance-audit")
        match = re.search(r"cleanup\.policy=(\S+)", config)
        assert match, "cleanup.policy not found in compliance-audit config"
        policy = match.group(1)
        assert "compact" in policy and "delete" in policy, (
            f"cleanup.policy must include both 'compact' and 'delete' "
            f"to satisfy compaction + time-based purging, got '{policy}'"
        )

    def test_retention_365_days(self):
        combined = get_combined_topic_info("compliance-audit")
        # 365 days = 365 * 24 * 60 * 60 * 1000 = 31536000000
        assert "31536000000" in combined, (
            "retention.ms should be 31536000000 (365 days) for compliance-audit"
        )

    def test_min_cleanable_dirty_ratio(self):
        config = get_topic_config("compliance-audit")
        assert "0.1" in config, (
            "min.cleanable.dirty.ratio should be 0.1 for compliance-audit"
        )


# ============================================================
# Topic: payment-ledger (300 MB/s / 50 MB/s = 6 partitions, 90d retention, 256MB segment)
# ============================================================


class TestPaymentLedgerTopic:
    def test_exists(self):
        info = get_topic_info("payment-ledger")
        assert "payment-ledger" in info, "Topic 'payment-ledger' not found"

    def test_partition_count(self):
        info = get_topic_info("payment-ledger")
        match = re.search(r"PartitionCount:\s*(\d+)", info)
        assert match and int(match.group(1)) == 6, (
            "payment-ledger should have 6 partitions"
        )

    def test_retention_90_days(self):
        combined = get_combined_topic_info("payment-ledger")
        # 90 days = 90 * 24 * 60 * 60 * 1000 = 7776000000
        assert "7776000000" in combined, (
            "retention.ms should be 7776000000 (90 days) for payment-ledger"
        )

    def test_segment_bytes(self):
        combined = get_combined_topic_info("payment-ledger")
        # 256 MB = 268435456
        assert "268435456" in combined, (
            "segment.bytes should be 268435456 (256MB) for payment-ledger"
        )


# ============================================================
# Exactly-Once Producer Configuration
# ============================================================


class TestExactlyOnceProducer:
    def test_file_exists(self):
        assert os.path.exists("/app/configs/exactly-once-producer.properties"), (
            "exactly-once-producer.properties not found"
        )

    def test_acks_all(self):
        props = read_properties("/app/configs/exactly-once-producer.properties")
        assert props.get("acks") == "all", (
            f"acks should be 'all', got '{props.get('acks')}'"
        )

    def test_idempotence_enabled(self):
        props = read_properties("/app/configs/exactly-once-producer.properties")
        assert props.get("enable.idempotence") == "true", (
            "enable.idempotence should be 'true'"
        )

    def test_max_in_flight_for_ordering(self):
        props = read_properties("/app/configs/exactly-once-producer.properties")
        val = props.get("max.in.flight.requests.per.connection")
        assert val is not None and int(val) <= 5, (
            "max.in.flight.requests.per.connection should be <= 5 for ordering guarantee"
        )


# ============================================================
# Throughput Producer Configuration
# ============================================================


class TestThroughputProducer:
    def test_file_exists(self):
        assert os.path.exists("/app/configs/throughput-producer.properties"), (
            "throughput-producer.properties not found"
        )

    def test_compression_snappy(self):
        props = read_properties("/app/configs/throughput-producer.properties")
        assert props.get("compression.type") == "snappy", (
            "compression.type should be 'snappy'"
        )

    def test_linger_ms(self):
        props = read_properties("/app/configs/throughput-producer.properties")
        val = props.get("linger.ms")
        assert val is not None and int(val) >= 50, (
            "linger.ms should be >= 50"
        )

    def test_batch_size(self):
        props = read_properties("/app/configs/throughput-producer.properties")
        val = props.get("batch.size")
        assert val is not None and int(val) >= 131072, (
            "batch.size should be >= 131072 (128KB)"
        )


# ============================================================
# Transactional Consumer Configuration
# ============================================================


class TestTransactionalConsumer:
    def test_file_exists(self):
        assert os.path.exists("/app/configs/transactional-consumer.properties"), (
            "transactional-consumer.properties not found"
        )

    def test_auto_commit_disabled(self):
        props = read_properties("/app/configs/transactional-consumer.properties")
        assert props.get("enable.auto.commit") == "false", (
            "enable.auto.commit should be 'false'"
        )

    def test_offset_reset_earliest(self):
        props = read_properties("/app/configs/transactional-consumer.properties")
        assert props.get("auto.offset.reset") == "earliest", (
            "auto.offset.reset should be 'earliest'"
        )

    def test_isolation_level_read_committed(self):
        props = read_properties("/app/configs/transactional-consumer.properties")
        assert props.get("isolation.level") == "read_committed", (
            "isolation.level should be 'read_committed'"
        )


# ============================================================
# Partition Reassignment Plan (CREATE)
# ============================================================


class TestReassignmentPlan:
    """Verify the partition reassignment plan satisfies all constraints."""

    ORIGINAL_ASSIGNMENTS = {
        0: [0, 1, 2],
        1: [1, 2, 0],
        2: [2, 0, 1],
        3: [0, 1, 2],
        4: [1, 2, 0],
        5: [2, 0, 1],
        6: [0, 1, 2],
        7: [1, 2, 0],
        8: [2, 0, 1],
        9: [0, 1, 2],
    }
    RACK_A = {0, 1, 2}
    RACK_B = {3, 4}

    def _load_plan(self):
        with open("/app/evaluation/reassignment.json") as f:
            return json.load(f)

    def test_file_exists(self):
        assert os.path.exists("/app/evaluation/reassignment.json"), (
            "reassignment.json not found"
        )

    def test_valid_json_structure(self):
        plan = self._load_plan()
        assert plan.get("version") == 1, "Plan must have version=1"
        assert "partitions" in plan, "Plan must have 'partitions' field"
        assert len(plan["partitions"]) == 10, (
            f"Expected 10 partitions, got {len(plan['partitions'])}"
        )

    def test_all_partitions_present_with_correct_rf(self):
        plan = self._load_plan()
        partition_ids = set()
        for entry in plan["partitions"]:
            assert entry["topic"] == "migration-test", (
                f"Expected topic 'migration-test', got '{entry['topic']}'"
            )
            pid = entry["partition"]
            partition_ids.add(pid)
            assert len(entry["replicas"]) == 3, (
                f"Partition {pid}: expected RF=3, got {len(entry['replicas'])} replicas"
            )
            assert len(set(entry["replicas"])) == 3, (
                f"Partition {pid}: duplicate brokers in replica list"
            )
            for broker in entry["replicas"]:
                assert 0 <= broker <= 4, (
                    f"Partition {pid}: invalid broker ID {broker}"
                )
        assert partition_ids == set(range(10)), (
            f"Missing partitions: {set(range(10)) - partition_ids}"
        )

    def test_broker_balance_six_each(self):
        plan = self._load_plan()
        broker_counts = {i: 0 for i in range(5)}
        for entry in plan["partitions"]:
            for broker in entry["replicas"]:
                broker_counts[broker] += 1
        for broker_id, count in broker_counts.items():
            assert count == 6, (
                f"Broker {broker_id} has {count} replicas, expected exactly 6. "
                f"Distribution: {broker_counts}"
            )

    def test_rack_awareness_both_racks(self):
        plan = self._load_plan()
        for entry in plan["partitions"]:
            replicas = set(entry["replicas"])
            pid = entry["partition"]
            has_rack_a = bool(replicas & self.RACK_A)
            has_rack_b = bool(replicas & self.RACK_B)
            assert has_rack_a, (
                f"Partition {pid} replicas {entry['replicas']} have no rack-A broker "
                f"(rack-A = {self.RACK_A})"
            )
            assert has_rack_b, (
                f"Partition {pid} replicas {entry['replicas']} have no rack-B broker "
                f"(rack-B = {self.RACK_B})"
            )

    def test_leader_distribution_two_each(self):
        plan = self._load_plan()
        leader_counts = {i: 0 for i in range(5)}
        for entry in plan["partitions"]:
            leader = entry["replicas"][0]
            leader_counts[leader] += 1
        for broker_id, count in leader_counts.items():
            assert count == 2, (
                f"Broker {broker_id} is preferred leader for {count} partitions, "
                f"expected exactly 2. Distribution: {leader_counts}"
            )

    def test_minimum_movements_within_budget(self):
        plan = self._load_plan()
        partition_map = {
            entry["partition"]: entry["replicas"]
            for entry in plan["partitions"]
        }
        movements = 0
        for pid, original in self.ORIGINAL_ASSIGNMENTS.items():
            new = partition_map[pid]
            original_set = set(original)
            for broker in new:
                if broker not in original_set:
                    movements += 1
        assert movements <= 12, (
            f"Total movements: {movements}, maximum allowed: 12. "
            f"Each replica on a different broker than the original counts as 1 movement."
        )


# ============================================================
# Configuration Governance Audit (EVALUATE)
# ============================================================


class TestConfigAudit:
    """Verify configuration governance audit verdicts."""

    EXPECTED_VERDICTS = {
        "A": "REJECT",
        "B": "ACCEPT",
        "C": "REJECT",
        "D": "REJECT",
        "E": "ACCEPT",
    }

    def _load_audit(self):
        with open("/app/evaluation/config_audit.json") as f:
            return json.load(f)

    def _get_verdicts(self):
        audit = self._load_audit()
        return {p["id"]: p["verdict"] for p in audit["proposals"]}

    def test_file_exists(self):
        assert os.path.exists("/app/evaluation/config_audit.json"), (
            "config_audit.json not found"
        )

    def test_valid_structure(self):
        audit = self._load_audit()
        assert "proposals" in audit, "Audit must have 'proposals' field"
        assert len(audit["proposals"]) == 5, (
            f"Expected 5 proposals, got {len(audit['proposals'])}"
        )

    def test_all_proposals_have_required_fields(self):
        audit = self._load_audit()
        for proposal in audit["proposals"]:
            assert "id" in proposal, "Each proposal must have 'id'"
            assert "verdict" in proposal, "Each proposal must have 'verdict'"
            assert "reason" in proposal, "Each proposal must have 'reason'"
            assert proposal["verdict"] in ("ACCEPT", "REJECT"), (
                f"Verdict must be ACCEPT or REJECT, got '{proposal['verdict']}'"
            )
            assert len(proposal["reason"]) > 0, "Reason must not be empty"

    def test_proposal_a_unclean_election_rejected(self):
        """Unclean leader election on compliance-audit must be rejected (data loss risk)."""
        verdicts = self._get_verdicts()
        assert verdicts.get("A") == "REJECT", (
            "Proposal A: unclean.leader.election.enable=true on compliance-audit "
            "should be REJECTED — risks data loss on compliance-critical topic"
        )

    def test_proposal_b_min_isr_accepted(self):
        """min.insync.replicas=2 with acks=all on payment-ledger should be accepted."""
        verdicts = self._get_verdicts()
        assert verdicts.get("B") == "ACCEPT", (
            "Proposal B: min.insync.replicas=2 with acks=all and RF=3 "
            "should be ACCEPTED — standard high-durability configuration"
        )

    def test_proposal_c_idempotence_acks_rejected(self):
        """enable.idempotence=true with acks=1 is invalid and must be rejected."""
        verdicts = self._get_verdicts()
        assert verdicts.get("C") == "REJECT", (
            "Proposal C: enable.idempotence=true with acks=1 "
            "should be REJECTED — idempotence requires acks=all in Kafka"
        )

    def test_proposal_d_infinite_retention_rejected(self):
        """Infinite retention on high-throughput telemetry topic must be rejected."""
        verdicts = self._get_verdicts()
        assert verdicts.get("D") == "REJECT", (
            "Proposal D: retention.ms=-1 on sensor-telemetry (400 MB/s) "
            "should be REJECTED — infinite retention will exhaust storage"
        )

    def test_proposal_e_throughput_optimization_accepted(self):
        """lz4 compression and larger batch size are valid throughput optimizations."""
        verdicts = self._get_verdicts()
        assert verdicts.get("E") == "ACCEPT", (
            "Proposal E: compression.type=lz4 and batch.size=262144 for throughput-producer "
            "should be ACCEPTED — valid throughput optimization"
        )


# ============================================================
# Verification Tests
# ============================================================


class TestVerification:
    def test_produced_file_exists(self):
        assert os.path.exists("/app/verification/produced.txt"), (
            "produced.txt not found"
        )

    def test_produced_has_messages(self):
        with open("/app/verification/produced.txt") as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) >= 10, (
            f"Expected at least 10 produced messages, got {len(lines)}"
        )

    def test_consumed_file_exists(self):
        assert os.path.exists("/app/verification/consumed.txt"), (
            "consumed.txt not found"
        )

    def test_consumed_has_messages(self):
        with open("/app/verification/consumed.txt") as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) >= 10, (
            f"Expected at least 10 consumed messages, got {len(lines)}"
        )
