
"""
Verification tests for Garnet cluster resharding task.
Checks cluster topology, slot distribution, replication, key integrity, and report.
"""

import json
import subprocess
import time

import redis


def redis_conn(port):
    """Create a redis connection to a specific Garnet port."""
    return redis.Redis(host="127.0.0.1", port=port, decode_responses=True, socket_timeout=10)


def parse_cluster_nodes(port=7000):
    """Parse CLUSTER NODES output from a given port into structured data."""
    r = redis_conn(port)
    raw = r.execute_command("CLUSTER", "NODES")
    r.close()
    nodes = []
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        node_id = parts[0]
        addr = parts[1]
        flags = parts[2]
        master_id = parts[3]
        link_state = parts[7]

        # Extract port from address (format: ip:port@cport,hostname)
        port_str = addr.split(":")[1].split("@")[0]

        # Count slots owned by this node
        slot_parts = parts[8:] if len(parts) > 8 else []
        total_slots = 0
        for s in slot_parts:
            if "-" in s:
                try:
                    start, end = s.split("-")
                    total_slots += int(end) - int(start) + 1
                except ValueError:
                    pass
            else:
                try:
                    int(s)
                    total_slots += 1
                except ValueError:
                    pass

        nodes.append(
            {
                "id": node_id,
                "port": int(port_str),
                "flags": flags,
                "is_master": "master" in flags,
                "is_replica": "slave" in flags,
                "master_id": master_id if "slave" in flags else None,
                "link_state": link_state,
                "slot_count": total_slots,
            }
        )
    return nodes


class TestClusterTopology:
    """Tests for cluster topology after resharding."""

    def test_four_master_nodes(self):
        """Cluster must have exactly 4 master nodes."""
        nodes = parse_cluster_nodes(7000)
        masters = [n for n in nodes if n["is_master"]]
        assert len(masters) == 4, (
            f"Expected 4 masters, found {len(masters)}: "
            f"{[n['port'] for n in masters]}"
        )

    def test_one_replica_node(self):
        """Cluster must have exactly 1 replica node."""
        nodes = parse_cluster_nodes(7000)
        replicas = [n for n in nodes if n["is_replica"]]
        assert len(replicas) == 1, (
            f"Expected 1 replica, found {len(replicas)}: "
            f"{[n['port'] for n in replicas]}"
        )

    def test_node_7003_is_master(self):
        """Port 7003 must be a master node with slots assigned."""
        nodes = parse_cluster_nodes(7000)
        node_7003 = [n for n in nodes if n["port"] == 7003]
        assert len(node_7003) == 1, "Port 7003 not found in cluster"
        assert node_7003[0]["is_master"], "Port 7003 should be a master"
        assert node_7003[0]["slot_count"] > 0, "Port 7003 should own slots"

    def test_node_7004_is_replica_of_7003(self):
        """Port 7004 must be a replica of port 7003."""
        nodes = parse_cluster_nodes(7000)
        node_7004 = [n for n in nodes if n["port"] == 7004]
        assert len(node_7004) == 1, "Port 7004 not found in cluster"
        assert node_7004[0]["is_replica"], "Port 7004 should be a replica"

        node_7003 = [n for n in nodes if n["port"] == 7003]
        assert len(node_7003) == 1, "Port 7003 not found in cluster"
        assert node_7004[0]["master_id"] == node_7003[0]["id"], (
            f"Port 7004 should replicate from 7003 "
            f"(expected master_id={node_7003[0]['id']}, "
            f"got {node_7004[0]['master_id']})"
        )


class TestSlotDistribution:
    """Tests for balanced slot distribution across masters."""

    def test_total_slots_16384(self):
        """All 16384 slots must be assigned across the cluster."""
        nodes = parse_cluster_nodes(7000)
        masters = [n for n in nodes if n["is_master"]]
        total = sum(n["slot_count"] for n in masters)
        assert total == 16384, (
            f"Total slots should be 16384, got {total}. "
            f"Per-node: {[(n['port'], n['slot_count']) for n in masters]}"
        )

    def test_balanced_slot_distribution(self):
        """Each master should own approximately 4096 slots (within ±10)."""
        nodes = parse_cluster_nodes(7000)
        masters = [n for n in nodes if n["is_master"]]
        for m in masters:
            assert 4086 <= m["slot_count"] <= 4106, (
                f"Port {m['port']} has {m['slot_count']} slots, "
                f"expected ~4096 (range 4086-4106)"
            )


class TestKeyIntegrity:
    """Tests for data integrity after resharding."""

    def test_all_500_keys_accessible(self):
        """All 500 keys must return correct values after resharding."""
        # Use redis-cli -c to follow MOVED redirections
        missing = []
        wrong = []
        for i in range(500):
            key = f"key:{i:04d}"
            expected = f"val:{i:04d}"
            result = subprocess.run(
                ["redis-cli", "-c", "-h", "127.0.0.1", "-p", "7000", "GET", key],
                capture_output=True,
                text=True,
                timeout=10,
            )
            actual = result.stdout.strip()
            if actual == "":
                missing.append(key)
            elif actual != expected:
                wrong.append((key, expected, actual))

        assert len(missing) == 0, f"Missing keys ({len(missing)}): {missing[:10]}..."
        assert len(wrong) == 0, f"Wrong values ({len(wrong)}): {wrong[:10]}..."

    def test_keys_distributed_across_new_node(self):
        """Some keys should now be served by the new node 7003."""
        # Query node 7003 for keys it owns (no -c flag, so it returns the key
        # if it owns it, or MOVED if not)
        owned_count = 0
        for i in range(500):
            key = f"key:{i:04d}"
            result = subprocess.run(
                ["redis-cli", "-h", "127.0.0.1", "-p", "7003", "GET", key],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.strip()
            # If we get a value (not MOVED), the key is on this node
            if not output.startswith("MOVED") and output != "":
                owned_count += 1

        # Node 7003 should own roughly 1/4 of the keys
        assert owned_count > 50, (
            f"Port 7003 only owns {owned_count} keys directly, "
            f"expected at least 50 after rebalancing"
        )


class TestClusterReport:
    """Tests for the cluster_report.json output."""

    def test_report_file_exists(self):
        """The cluster report JSON file must exist."""
        import os

        assert os.path.exists("/app/cluster_report.json"), (
            "/app/cluster_report.json does not exist"
        )

    def test_report_valid_json(self):
        """The report must be valid JSON with required fields."""
        with open("/app/cluster_report.json") as f:
            report = json.load(f)

        assert "nodes" in report, "Report missing 'nodes' field"
        assert "total_keys_verified" in report, "Report missing 'total_keys_verified'"
        assert "replica_replicating" in report, "Report missing 'replica_replicating'"

    def test_report_nodes_structure(self):
        """Each node in the report must have id, port, role, slot_count."""
        with open("/app/cluster_report.json") as f:
            report = json.load(f)

        for node in report["nodes"]:
            assert "id" in node, f"Node missing 'id': {node}"
            assert "port" in node, f"Node missing 'port': {node}"
            assert "role" in node, f"Node missing 'role': {node}"
            assert "slot_count" in node, f"Node missing 'slot_count': {node}"
            assert node["role"] in ("master", "replica"), (
                f"Invalid role '{node['role']}' for port {node.get('port')}"
            )

    def test_report_shows_500_keys(self):
        """Report must indicate all 500 keys were verified."""
        with open("/app/cluster_report.json") as f:
            report = json.load(f)

        assert report["total_keys_verified"] == 500, (
            f"Expected 500 verified keys, got {report['total_keys_verified']}"
        )

    def test_report_replica_active(self):
        """Report must indicate replica is actively replicating."""
        with open("/app/cluster_report.json") as f:
            report = json.load(f)

        assert report["replica_replicating"] is True, (
            "Report shows replica is not replicating"
        )

    def test_report_four_masters(self):
        """Report must show exactly 4 master nodes."""
        with open("/app/cluster_report.json") as f:
            report = json.load(f)

        masters = [n for n in report["nodes"] if n["role"] == "master"]
        assert len(masters) == 4, (
            f"Report shows {len(masters)} masters, expected 4"
        )
