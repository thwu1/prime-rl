
import json
import hashlib
import base64
import subprocess
import os
import pytest


def derive_peer_key_hex(seed_name):
    """Derive the hex Curve25519 public key using the same seed as the generator."""
    priv_bytes = hashlib.sha256(
        f"wg-private-{seed_name}-seed-v1".encode()
    ).digest()
    priv_b64 = base64.b64encode(priv_bytes).decode()
    result = subprocess.run(
        ["wg", "pubkey"],
        input=priv_b64,
        capture_output=True,
        text=True,
        check=True,
    )
    pub_b64 = result.stdout.strip()
    pub_bytes = base64.b64decode(pub_b64)
    return pub_bytes.hex()


@pytest.fixture(scope="module")
def keys():
    names = [
        "alpha", "bravo", "gamma", "delta", "echo",
        "rogue", "server1", "server2",
    ]
    return {name: derive_peer_key_hex(name) for name in names}


@pytest.fixture(scope="module")
def report():
    path = "/app/audit_report.json"
    assert os.path.exists(path), "audit_report.json not found at /app/audit_report.json"
    with open(path) as f:
        return json.load(f)


# ─── Node 1 frame counts ────────────────────────────────────────────


class TestNode1Totals:
    def test_total_frames(self, report):
        assert report["node1"]["total_frames"] == 37

    def test_session_count(self, report):
        assert report["node1"]["session_count"] == 4


class TestNode1FrameCounts:
    def test_server_key(self, report):
        assert report["node1"]["frame_type_counts"]["ServerKey"] == 4

    def test_client_info(self, report):
        assert report["node1"]["frame_type_counts"]["ClientInfo"] == 4

    def test_server_info(self, report):
        assert report["node1"]["frame_type_counts"]["ServerInfo"] == 4

    def test_send_packet(self, report):
        assert report["node1"]["frame_type_counts"]["SendPacket"] == 4

    def test_recv_packet(self, report):
        assert report["node1"]["frame_type_counts"]["RecvPacket"] == 2

    def test_keep_alive(self, report):
        assert report["node1"]["frame_type_counts"]["KeepAlive"] == 2

    def test_note_preferred(self, report):
        assert report["node1"]["frame_type_counts"]["NotePreferred"] == 2

    def test_ping(self, report):
        assert report["node1"]["frame_type_counts"]["Ping"] == 3

    def test_pong(self, report):
        assert report["node1"]["frame_type_counts"]["Pong"] == 3

    def test_watch_conns(self, report):
        assert report["node1"]["frame_type_counts"]["WatchConns"] == 2

    def test_forward_packet(self, report):
        assert report["node1"]["frame_type_counts"]["ForwardPacket"] == 3

    def test_peer_present(self, report):
        assert report["node1"]["frame_type_counts"]["PeerPresent"] == 2

    def test_peer_gone(self, report):
        assert report["node1"]["frame_type_counts"]["PeerGone"] == 2


class TestNode1DataBytes:
    def test_send_bytes(self, report):
        # 128 + 256 + 100 + 64 = 548
        assert report["node1"]["data_bytes"]["send"] == 548

    def test_recv_bytes(self, report):
        # 200 + 300 = 500
        assert report["node1"]["data_bytes"]["recv"] == 500

    def test_forward_bytes(self, report):
        # 150 + 300 + 200 = 650
        assert report["node1"]["data_bytes"]["forward"] == 650


# ─── Node 2 frame counts ────────────────────────────────────────────


class TestNode2Totals:
    def test_total_frames(self, report):
        assert report["node2"]["total_frames"] == 31

    def test_session_count(self, report):
        assert report["node2"]["session_count"] == 4


class TestNode2FrameCounts:
    def test_server_key(self, report):
        assert report["node2"]["frame_type_counts"]["ServerKey"] == 4

    def test_client_info(self, report):
        assert report["node2"]["frame_type_counts"]["ClientInfo"] == 4

    def test_server_info(self, report):
        assert report["node2"]["frame_type_counts"]["ServerInfo"] == 4

    def test_send_packet(self, report):
        assert report["node2"]["frame_type_counts"]["SendPacket"] == 2

    def test_recv_packet(self, report):
        assert report["node2"]["frame_type_counts"]["RecvPacket"] == 3

    def test_keep_alive(self, report):
        assert report["node2"]["frame_type_counts"]["KeepAlive"] == 1

    def test_note_preferred(self, report):
        assert report["node2"]["frame_type_counts"]["NotePreferred"] == 2

    def test_ping(self, report):
        assert report["node2"]["frame_type_counts"]["Ping"] == 1

    def test_pong(self, report):
        assert report["node2"]["frame_type_counts"]["Pong"] == 1

    def test_watch_conns(self, report):
        assert report["node2"]["frame_type_counts"]["WatchConns"] == 2

    def test_forward_packet(self, report):
        assert report["node2"]["frame_type_counts"]["ForwardPacket"] == 1

    def test_peer_present(self, report):
        assert report["node2"]["frame_type_counts"]["PeerPresent"] == 2

    def test_peer_gone(self, report):
        assert report["node2"]["frame_type_counts"]["PeerGone"] == 1

    def test_health(self, report):
        assert report["node2"]["frame_type_counts"]["Health"] == 1

    def test_restarting(self, report):
        assert report["node2"]["frame_type_counts"]["Restarting"] == 1

    def test_close_peer(self, report):
        assert report["node2"]["frame_type_counts"]["ClosePeer"] == 1


class TestNode2DataBytes:
    def test_send_bytes(self, report):
        # 180 + 90 = 270
        assert report["node2"]["data_bytes"]["send"] == 270

    def test_recv_bytes(self, report):
        # 256 + 150 + 120 = 526
        assert report["node2"]["data_bytes"]["recv"] == 526

    def test_forward_bytes(self, report):
        assert report["node2"]["data_bytes"]["forward"] == 250


# ─── Peer key mapping ───────────────────────────────────────────────


class TestPeerKeyMapping:
    def test_mapping_count(self, report):
        assert len(report["peer_key_mapping"]) == 5

    def test_alpha(self, report, keys):
        assert report["peer_key_mapping"][keys["alpha"]] == "alpha"

    def test_bravo(self, report, keys):
        assert report["peer_key_mapping"][keys["bravo"]] == "bravo"

    def test_gamma(self, report, keys):
        assert report["peer_key_mapping"][keys["gamma"]] == "gamma"

    def test_delta(self, report, keys):
        assert report["peer_key_mapping"][keys["delta"]] == "delta"

    def test_echo(self, report, keys):
        assert report["peer_key_mapping"][keys["echo"]] == "echo"

    def test_rogue_not_mapped(self, report, keys):
        assert keys["rogue"] not in report["peer_key_mapping"]


# ─── Unauthorized peers ─────────────────────────────────────────────


class TestUnauthorizedPeers:
    def test_count(self, report):
        assert len(report["unauthorized_peers"]) == 1

    def test_rogue_key(self, report, keys):
        entry = report["unauthorized_peers"][0]
        assert entry["key"] == keys["rogue"]

    def test_rogue_node(self, report):
        entry = report["unauthorized_peers"][0]
        assert entry["node"] == "node1"

    def test_rogue_session_index(self, report):
        entry = report["unauthorized_peers"][0]
        assert entry["session_index"] == 3


# ─── Privilege violations ───────────────────────────────────────────


class TestPrivilegeViolations:
    def test_count(self, report):
        assert len(report["privilege_violations"]) == 2

    def test_watch_conns_violation(self, report, keys):
        wc = [v for v in report["privilege_violations"]
              if v["frame_type"] == "WatchConns"]
        assert len(wc) == 1
        assert wc[0]["peer_name"] == "bravo"
        assert wc[0]["peer_key"] == keys["bravo"]
        assert wc[0]["node"] == "node1"
        assert wc[0]["peer_role"] == "client"
        assert wc[0]["required_role"] == "mesh"

    def test_forward_packet_violation(self, report, keys):
        fp = [v for v in report["privilege_violations"]
              if v["frame_type"] == "ForwardPacket"]
        assert len(fp) == 1
        assert fp[0]["peer_name"] == "bravo"
        assert fp[0]["peer_key"] == keys["bravo"]
        assert fp[0]["node"] == "node1"
        assert fp[0]["peer_role"] == "client"
        assert fp[0]["required_role"] == "mesh"


# ─── Node policy violations ─────────────────────────────────────────


class TestNodePolicyViolations:
    def test_count(self, report):
        assert len(report["node_policy_violations"]) == 1

    def test_alpha_on_node2(self, report, keys):
        v = report["node_policy_violations"][0]
        assert v["peer_name"] == "alpha"
        assert v["peer_key"] == keys["alpha"]
        assert v["node"] == "node2"
        assert v["allowed_nodes"] == ["node1"]


# ─── Protocol violations ────────────────────────────────────────────


class TestProtocolViolations:
    def test_count(self, report):
        assert len(report["protocol_violations"]) == 1

    def test_send_before_clientinfo(self, report):
        v = report["protocol_violations"][0]
        assert v["node"] == "node1"
        assert v["session_index"] == 3
        assert v["frame_index_in_session"] == 1
        assert "SendPacket" in v["violation"] or "before" in v["violation"].lower()


# ─── Cross-node metrics ─────────────────────────────────────────────


class TestCrossNodeMetrics:
    def test_forward_packet_count(self, report):
        assert report["cross_node_forward_packets"] == 4

    def test_forward_bytes(self, report):
        assert report["cross_node_forward_bytes"] == 900

    def test_total_data_bytes(self, report):
        assert report["total_data_bytes"] == 2744


# ─── Mesh topology ──────────────────────────────────────────────────


class TestMeshTopology:
    def test_node1_peer_count(self, report):
        assert report["mesh_topology"]["node1_peer_count"] == 4

    def test_node2_peer_count(self, report):
        assert report["mesh_topology"]["node2_peer_count"] == 4

    def test_shared_peers(self, report):
        shared = sorted(report["mesh_topology"]["shared_peers"])
        assert shared == ["alpha", "gamma"]
