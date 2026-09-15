"""

Tests for Redis cluster recovery task.
Verifies cluster health, slot balance, data integrity, and report correctness.
"""

import csv
import json
import os

import pytest
import redis

HASH_SLOT_COUNT = 16384
DATASET_PATH = "/app/dataset.csv"
REPORT_PATH = "/app/cluster_report.json"
PORTS = [7000, 7001, 7002]

MIN_SLOTS_PER_NODE = 4500
MAX_SLOTS_PER_NODE = 6000


def crc16(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def key_slot(key: str) -> int:
    k = key
    s = k.find("{")
    if s != -1:
        e = k.find("}", s + 1)
        if e != -1 and e != s + 1:
            k = k[s + 1:e]
    return crc16(k.encode()) % HASH_SLOT_COUNT


def _get_conn(port: int) -> redis.Redis:
    return redis.Redis(host="127.0.0.1", port=port, decode_responses=True,
                       socket_timeout=5)


def _parse_node_slots(nodes_output: str) -> dict:
    """Parse CLUSTER NODES output -> {port: set_of_owned_slots}."""
    result = {}
    for line in nodes_output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        addr = parts[1].split("@")[0].split(",")[0]
        port = int(addr.split(":")[1])
        owned = set()
        for token in parts[8:]:
            if token.startswith("["):
                continue
            if "-" in token:
                lo, hi = token.split("-")
                try:
                    owned.update(range(int(lo), int(hi) + 1))
                except ValueError:
                    pass
            else:
                try:
                    owned.add(int(token))
                except ValueError:
                    pass
        result[port] = owned
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestClusterRunning:
    """Redis instances must be alive and reachable."""

    @pytest.mark.parametrize("port", PORTS)
    def test_node_ping(self, port):
        r = _get_conn(port)
        assert r.ping(), f"Node {port} did not respond to PING"
        r.close()


class TestClusterHealth:
    """All nodes should report a healthy cluster."""

    @pytest.mark.parametrize("port", PORTS)
    def test_cluster_state_ok(self, port):
        r = _get_conn(port)
        info = r.execute_command("CLUSTER", "INFO")
        r.close()
        assert "cluster_state:ok" in info, f"Port {port}: {info[:200]}"


class TestSlotBalance:
    """Slot distribution must be approximately uniform."""

    @pytest.fixture(autouse=True)
    def _slot_map(self):
        r = _get_conn(7000)
        raw = r.execute_command("CLUSTER", "NODES")
        r.close()
        self.slot_map = _parse_node_slots(raw)

    def test_all_slots_assigned(self):
        all_slots = set()
        for slots in self.slot_map.values():
            all_slots.update(slots)
        missing = set(range(HASH_SLOT_COUNT)) - all_slots
        assert not missing, f"{len(missing)} slots unassigned"

    @pytest.mark.parametrize("port", PORTS)
    def test_node_slot_count_balanced(self, port):
        count = len(self.slot_map.get(port, set()))
        assert MIN_SLOTS_PER_NODE <= count <= MAX_SLOTS_PER_NODE, (
            f"Node {port} has {count} slots, expected {MIN_SLOTS_PER_NODE}-{MAX_SLOTS_PER_NODE}"
        )


class TestDataIntegrity:
    """Every key from dataset.csv must be accessible on its correct owner."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        r = _get_conn(7000)
        raw = r.execute_command("CLUSTER", "NODES")
        r.close()
        slot_map = _parse_node_slots(raw)
        self.slot_to_port = {}
        for port, slots in slot_map.items():
            for slot in slots:
                self.slot_to_port[slot] = port

        self.keys = []
        with open(DATASET_PATH) as f:
            for row in csv.DictReader(f):
                slot = key_slot(row["key"])
                owner = self.slot_to_port.get(slot)
                self.keys.append((row["key"], row["value"], slot, owner))

    def test_all_keys_present(self):
        conns = {p: _get_conn(p) for p in PORTS}
        missing = []
        for key, expected_val, slot, owner in self.keys:
            if owner is None:
                missing.append(f"key={key} slot={slot} no_owner")
                continue
            val = conns[owner].get(key)
            if val != expected_val:
                missing.append(
                    f"key={key} slot={slot} port={owner} "
                    f"expected={expected_val!r} got={val!r}"
                )
        for c in conns.values():
            c.close()
        assert not missing, f"{len(missing)} key(s) wrong:\n" + "\n".join(missing[:10])

    def test_key_count_matches_dataset(self):
        conns = {p: _get_conn(p) for p in PORTS}
        total = sum(int(conns[p].dbsize()) for p in PORTS)
        for c in conns.values():
            c.close()
        expected = len(self.keys)
        assert total >= expected, (
            f"Found {total} keys in cluster, expected at least {expected}"
        )


class TestReport:
    """cluster_report.json must exist and contain correct information."""

    def test_report_exists(self):
        assert os.path.isfile(REPORT_PATH), f"{REPORT_PATH} not found"

    def test_report_valid_json(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_report_has_required_fields(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        for field in ["nodes", "migrated_key_count", "all_keys_verified"]:
            assert field in data, f"Missing field: {field}"

    def test_report_nodes_structure(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        nodes = data["nodes"]
        assert isinstance(nodes, list)
        assert len(nodes) >= 3
        ports_seen = set()
        for node in nodes:
            for required in ("port", "node_id", "role", "slots"):
                assert required in node, f"Node missing field: {required}"
            ports_seen.add(node["port"])
        assert set(PORTS) <= ports_seen

    def test_report_verified_flag(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert data["all_keys_verified"] is True

    def test_report_migrated_key_count_positive(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data["migrated_key_count"], int)
        assert data["migrated_key_count"] > 0, (
            "migrated_key_count must be positive — rebalancing should have relocated keys"
        )

    def test_report_migrated_key_count_reasonable(self):
        with open(REPORT_PATH) as f:
            data = json.load(f)
        total_keys = sum(1 for _ in csv.DictReader(open(DATASET_PATH)))
        assert data["migrated_key_count"] <= total_keys, (
            f"migrated_key_count={data['migrated_key_count']} exceeds total keys={total_keys}"
        )
