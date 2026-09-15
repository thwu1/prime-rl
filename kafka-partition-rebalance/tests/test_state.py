
import csv
import json
import os
import re

import pytest
import yaml
from collections import defaultdict


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
    """Parse disk_quotas.csv for broker capacities."""
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
    """Parse kafka-topics --describe output."""
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
    """Parse kafka-log-dirs JSON for partition sizes."""
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
    }


def build_cluster_state():
    """Build the complete cluster state from metadata files."""
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


@pytest.fixture
def cluster_state():
    return build_cluster_state()


@pytest.fixture
def reassignment_plan():
    with open("/app/reassignment_plan.json") as f:
        return json.load(f)


@pytest.fixture
def audit_report():
    with open("/app/audit_report.json") as f:
        return json.load(f)


@pytest.fixture
def validation_report():
    with open("/app/validation_report.json") as f:
        return json.load(f)


@pytest.fixture
def broker_rack(cluster_state):
    return {b["id"]: b["rack"] for b in cluster_state["brokers"]}


@pytest.fixture
def broker_capacity(cluster_state):
    return {b["id"]: b["disk_capacity_gb"] for b in cluster_state["brokers"]}


@pytest.fixture
def original_assignments(cluster_state):
    """Build a dict of (topic, partition) -> {replicas, leader, size_gb, rf}"""
    assignments = {}
    for topic in cluster_state["topics"]:
        rf = topic["replication_factor"]
        for part in topic["partitions"]:
            key = (topic["name"], part["partition"])
            assignments[key] = {
                "replicas": list(part["replicas"]),
                "leader": part["leader"],
                "size_gb": part["size_gb"],
                "rf": rf,
            }
    return assignments


@pytest.fixture
def final_assignments(original_assignments, reassignment_plan):
    """Compute the final state after applying the reassignment plan."""
    final = {}
    for key, val in original_assignments.items():
        final[key] = dict(val)

    for batch in reassignment_plan["batches"]:
        for entry in batch["partitions"]:
            key = (entry["topic"], entry["partition"])
            assert key in final, f"Reassignment references unknown partition: {key}"
            final[key]["replicas"] = list(entry["replicas"])
            final[key]["leader"] = entry["replicas"][0]

    return final


class TestOutputFilesExist:
    def test_reassignment_plan_exists(self):
        assert os.path.exists("/app/reassignment_plan.json"), \
            "reassignment_plan.json not found"

    def test_audit_report_exists(self):
        assert os.path.exists("/app/audit_report.json"), \
            "audit_report.json not found"

    def test_validation_report_exists(self):
        assert os.path.exists("/app/validation_report.json"), \
            "validation_report.json not found"


class TestValidationReport:
    def test_validation_passed(self, validation_report):
        assert validation_report.get("valid") is True, \
            f"Validation report shows invalid plan. Errors: {validation_report.get('errors', [])}"

    def test_has_summary(self, validation_report):
        assert "summary" in validation_report
        assert "checks_passed" in validation_report
        assert "checks_total" in validation_report

    def test_all_checks_passed(self, validation_report):
        assert validation_report["checks_passed"] == validation_report["checks_total"], \
            f"Only {validation_report['checks_passed']}/{validation_report['checks_total']} checks passed"


class TestReassignmentPlanFormat:
    def test_version(self, reassignment_plan):
        assert reassignment_plan.get("version") == 1

    def test_has_batches(self, reassignment_plan):
        assert "batches" in reassignment_plan
        assert isinstance(reassignment_plan["batches"], list)
        assert len(reassignment_plan["batches"]) > 0

    def test_batch_ids_sequential(self, reassignment_plan):
        batch_ids = [b["batch_id"] for b in reassignment_plan["batches"]]
        assert batch_ids == list(range(1, len(batch_ids) + 1))

    def test_partition_entries_format(self, reassignment_plan):
        for batch in reassignment_plan["batches"]:
            for entry in batch["partitions"]:
                assert "topic" in entry
                assert "partition" in entry
                assert "replicas" in entry
                assert "log_dirs" in entry
                assert isinstance(entry["replicas"], list)
                assert isinstance(entry["log_dirs"], list)
                assert len(entry["log_dirs"]) == len(entry["replicas"])
                assert all(d == "any" for d in entry["log_dirs"])

    def test_batch_size_limit(self, reassignment_plan, cluster_state):
        max_moves = cluster_state["constraints"]["max_concurrent_moves"]
        for batch in reassignment_plan["batches"]:
            assert len(batch["partitions"]) <= max_moves, \
                f"Batch {batch['batch_id']} has {len(batch['partitions'])} moves, max is {max_moves}"


class TestOnlyChangedPartitions:
    def test_no_unchanged_partitions(self, reassignment_plan, original_assignments):
        """Only partitions whose replicas actually changed should appear."""
        for batch in reassignment_plan["batches"]:
            for entry in batch["partitions"]:
                key = (entry["topic"], entry["partition"])
                orig = original_assignments[key]
                assert entry["replicas"] != orig["replicas"], \
                    f"Partition {key} appears in plan but replicas didn't change"


class TestAllPartitionsPreserved:
    def test_partition_count(self, final_assignments, original_assignments):
        assert set(final_assignments.keys()) == set(original_assignments.keys()), \
            "Some partitions are missing or extra partitions appeared"

    def test_replication_factor_preserved(self, final_assignments, original_assignments):
        for key in original_assignments:
            orig_rf = original_assignments[key]["rf"]
            new_rf = len(final_assignments[key]["replicas"])
            assert new_rf == orig_rf, \
                f"Partition {key}: RF changed from {orig_rf} to {new_rf}"


class TestNoDuplicateBrokers:
    def test_no_colocation(self, final_assignments, cluster_state):
        broker_ids = {b["id"] for b in cluster_state["brokers"]}
        for key, val in final_assignments.items():
            replicas = val["replicas"]
            assert len(replicas) == len(set(replicas)), \
                f"Partition {key}: duplicate broker in replicas {replicas}"
            for bid in replicas:
                assert bid in broker_ids, \
                    f"Partition {key}: invalid broker ID {bid}"


class TestRackAwareness:
    def test_full_rack_diversity(self, final_assignments, broker_rack):
        all_racks = set(broker_rack.values())
        num_racks = len(all_racks)

        for key, val in final_assignments.items():
            rf = val["rf"]
            replicas = val["replicas"]
            racks_used = {broker_rack[bid] for bid in replicas}
            ideal_racks = min(rf, num_racks)
            assert len(racks_used) >= ideal_racks, \
                f"Partition {key}: uses {len(racks_used)} racks but should use {ideal_racks}. " \
                f"Replicas: {replicas}, Racks: {racks_used}"


class TestReplicaBalance:
    def test_replica_count_balance(self, final_assignments, cluster_state):
        max_imbalance = cluster_state["constraints"]["max_replica_imbalance"]
        broker_ids = [b["id"] for b in cluster_state["brokers"]]
        counts = {bid: 0 for bid in broker_ids}

        for val in final_assignments.values():
            for bid in val["replicas"]:
                counts[bid] += 1

        max_count = max(counts.values())
        min_count = min(counts.values())
        imbalance = max_count - min_count
        assert imbalance <= max_imbalance, \
            f"Replica imbalance {imbalance} exceeds max {max_imbalance}. Counts: {counts}"


class TestLeaderBalance:
    def test_leader_count_balance(self, final_assignments, cluster_state):
        max_imbalance = cluster_state["constraints"]["max_leader_imbalance"]
        broker_ids = [b["id"] for b in cluster_state["brokers"]]
        counts = {bid: 0 for bid in broker_ids}

        for val in final_assignments.values():
            leader = val["leader"]
            counts[leader] += 1

        max_count = max(counts.values())
        min_count = min(counts.values())
        imbalance = max_count - min_count
        assert imbalance <= max_imbalance, \
            f"Leader imbalance {imbalance} exceeds max {max_imbalance}. Counts: {counts}"


class TestDiskCapacity:
    def test_no_broker_exceeds_capacity(self, final_assignments, broker_capacity):
        disk_usage = defaultdict(float)

        for val in final_assignments.values():
            for bid in val["replicas"]:
                disk_usage[bid] += val["size_gb"]

        for bid, cap in broker_capacity.items():
            usage = disk_usage[bid]
            assert usage <= cap, \
                f"Broker {bid}: disk usage {usage}GB exceeds capacity {cap}GB"


class TestAuditReport:
    def test_has_before_and_after(self, audit_report):
        assert "before" in audit_report
        assert "after" in audit_report
        for section in ["before", "after"]:
            data = audit_report[section]
            assert "replica_count_per_broker" in data
            assert "leader_count_per_broker" in data
            assert "disk_usage_gb_per_broker" in data
            assert "rack_awareness_violations" in data

    def test_has_movement_stats(self, audit_report):
        assert "total_replica_moves" in audit_report
        assert "total_data_moved_gb" in audit_report
        assert "num_batches" in audit_report
        assert "partitions_reassigned" in audit_report

    def test_before_metrics_accurate(self, audit_report, original_assignments, broker_rack):
        """Verify the 'before' section matches the actual original state."""
        before = audit_report["before"]

        expected_replica = defaultdict(int)
        expected_leader = defaultdict(int)
        expected_disk = defaultdict(float)
        all_racks = set(broker_rack.values())
        num_racks = len(all_racks)
        rack_violations = 0

        for val in original_assignments.values():
            for bid in val["replicas"]:
                expected_replica[bid] += 1
                expected_disk[bid] += val["size_gb"]
            expected_leader[val["leader"]] += 1

            racks_used = {broker_rack[bid] for bid in val["replicas"]}
            ideal = min(val["rf"], num_racks)
            if len(racks_used) < ideal:
                rack_violations += 1

        for bid_str, count in before["replica_count_per_broker"].items():
            bid = int(bid_str)
            assert count == expected_replica[bid], \
                f"Before: broker {bid} replica count {count} != expected {expected_replica[bid]}"

        for bid_str, count in before["leader_count_per_broker"].items():
            bid = int(bid_str)
            assert count == expected_leader[bid], \
                f"Before: broker {bid} leader count {count} != expected {expected_leader[bid]}"

        for bid_str, usage in before["disk_usage_gb_per_broker"].items():
            bid = int(bid_str)
            assert abs(usage - expected_disk[bid]) < 0.01, \
                f"Before: broker {bid} disk usage {usage} != expected {expected_disk[bid]}"

        assert before["rack_awareness_violations"] == rack_violations, \
            f"Before: rack violations {before['rack_awareness_violations']} != expected {rack_violations}"

    def test_after_metrics_match_plan(self, audit_report, final_assignments, broker_rack, cluster_state):
        """Verify the 'after' section matches the state after applying the plan."""
        after = audit_report["after"]
        all_racks = set(broker_rack.values())
        num_racks = len(all_racks)

        expected_replica = defaultdict(int)
        expected_leader = defaultdict(int)
        expected_disk = defaultdict(float)
        rack_violations = 0

        for val in final_assignments.values():
            for bid in val["replicas"]:
                expected_replica[bid] += 1
                expected_disk[bid] += val["size_gb"]
            expected_leader[val["leader"]] += 1

            racks_used = {broker_rack[bid] for bid in val["replicas"]}
            ideal = min(val["rf"], num_racks)
            if len(racks_used) < ideal:
                rack_violations += 1

        for bid_str, count in after["replica_count_per_broker"].items():
            bid = int(bid_str)
            assert count == expected_replica[bid], \
                f"After: broker {bid} replica count {count} != expected {expected_replica[bid]}"

        for bid_str, count in after["leader_count_per_broker"].items():
            bid = int(bid_str)
            assert count == expected_leader[bid], \
                f"After: broker {bid} leader count {count} != expected {expected_leader[bid]}"

        for bid_str, usage in after["disk_usage_gb_per_broker"].items():
            bid = int(bid_str)
            assert abs(usage - expected_disk[bid]) < 0.01, \
                f"After: broker {bid} disk usage {usage} != expected {expected_disk[bid]}"

        assert after["rack_awareness_violations"] == rack_violations

    def test_after_has_zero_rack_violations(self, audit_report):
        assert audit_report["after"]["rack_awareness_violations"] == 0, \
            "After reassignment there should be zero rack awareness violations"

    def test_movement_stats_consistent(self, audit_report, reassignment_plan):
        assert audit_report["num_batches"] == len(reassignment_plan["batches"]), \
            "num_batches doesn't match actual batch count"

        total_partitions_in_plan = sum(
            len(b["partitions"]) for b in reassignment_plan["batches"]
        )
        assert audit_report["partitions_reassigned"] == total_partitions_in_plan, \
            "partitions_reassigned doesn't match plan count"

    def test_movement_positive(self, audit_report):
        assert audit_report["total_replica_moves"] > 0
        assert audit_report["total_data_moved_gb"] > 0

    def test_all_brokers_in_report(self, audit_report, cluster_state):
        broker_ids = {str(b["id"]) for b in cluster_state["brokers"]}
        for section in ["before", "after"]:
            data = audit_report[section]
            assert set(data["replica_count_per_broker"].keys()) == broker_ids
            assert set(data["leader_count_per_broker"].keys()) == broker_ids
            assert set(data["disk_usage_gb_per_broker"].keys()) == broker_ids


class TestNoDuplicatePartitionsInPlan:
    def test_each_partition_appears_once(self, reassignment_plan):
        """Each (topic, partition) should appear at most once across all batches."""
        seen = set()
        for batch in reassignment_plan["batches"]:
            for entry in batch["partitions"]:
                key = (entry["topic"], entry["partition"])
                assert key not in seen, \
                    f"Partition {key} appears multiple times in the plan"
                seen.add(key)
