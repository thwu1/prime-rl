"""Forensic audit verification tests for DERP relay capture analysis.

Validates /app/audit.db (SQLite) and /app/audit.json against deterministic
expected values derived from the known capture generator seeds.
"""

import json
import hashlib
import os
import sqlite3
import subprocess

import pytest

# Deterministic client keys (same seeds as generator)
KEY_ALPHA     = hashlib.sha256(b"audit_client_alpha").digest().hex()
KEY_BRAVO     = hashlib.sha256(b"audit_client_bravo").digest().hex()
KEY_CHARLIE   = hashlib.sha256(b"audit_client_charlie").digest().hex()
KEY_MESH_WEST = hashlib.sha256(b"audit_mesh_west_peer").digest().hex()
KEY_PHANTOM   = hashlib.sha256(b"audit_phantom_node").digest().hex()

TOTAL_FRAMES = 51


def _extract_server_key_hex():
    """Extract raw Ed25519 public key hex from PEM via openssl."""
    result = subprocess.run(
        ['openssl', 'pkey', '-pubin',
         '-in', '/app/certs/server_identity.pem', '-outform', 'DER'],
        capture_output=True, check=True
    )
    return result.stdout[12:].hex()


def _server_key_fingerprint():
    key_hex = _extract_server_key_hex()
    return hashlib.sha256(bytes.fromhex(key_hex)).hexdigest()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def audit_json():
    path = "/app/audit.json"
    assert os.path.exists(path), "audit.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def audit_db():
    path = "/app/audit.db"
    assert os.path.exists(path), "audit.db not found"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ── Database schema tests ────────────────────────────────────────────────

class TestDatabaseSchema:
    def test_frames_table_exists(self, audit_db):
        cur = audit_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='frames'")
        assert cur.fetchone() is not None

    def test_connections_table_exists(self, audit_db):
        cur = audit_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='connections'")
        assert cur.fetchone() is not None

    def test_routing_events_table_exists(self, audit_db):
        cur = audit_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routing_events'")
        assert cur.fetchone() is not None

    def test_anomalies_table_exists(self, audit_db):
        cur = audit_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='anomalies'")
        assert cur.fetchone() is not None


# ── Frames table tests ───────────────────────────────────────────────────

class TestFramesTable:
    def test_total_frame_count(self, audit_db):
        cur = audit_db.execute("SELECT COUNT(*) FROM frames")
        assert cur.fetchone()[0] == TOTAL_FRAMES

    def test_frame_type_distribution(self, audit_db):
        expected = {
            'FrameServerKey': 6, 'FrameClientInfo': 5, 'FrameServerInfo': 5,
            'FrameSendPacket': 8, 'FrameRecvPacket': 8, 'FrameKeepAlive': 4,
            'FrameNotePreferred': 2, 'FramePeerGone': 3, 'FramePeerPresent': 2,
            'FrameForwardPacket': 1, 'FrameWatchConns': 2, 'FrameClosePeer': 1,
            'FramePing': 1, 'FramePong': 1, 'FrameHealth': 1,
            'FrameRestarting': 1,
        }
        cur = audit_db.execute(
            "SELECT frame_type_name, COUNT(*) FROM frames GROUP BY frame_type_name")
        actual = {row[0]: row[1] for row in cur}
        for name, count in expected.items():
            assert actual.get(name) == count, \
                f"{name}: expected {count}, got {actual.get(name)}"


# ── Connections table tests ──────────────────────────────────────────────

class TestConnectionsTable:
    def test_connection_count(self, audit_db):
        cur = audit_db.execute("SELECT COUNT(*) FROM connections")
        assert cur.fetchone()[0] == 6

    def test_alpha_connection(self, audit_db):
        cur = audit_db.execute(
            "SELECT * FROM connections WHERE conn_id=0")
        row = cur.fetchone()
        assert row['client_key_hex'] == KEY_ALPHA
        assert row['is_mesh_peer'] == 0
        assert row['handshake_complete'] == 1
        assert row['frame_count'] == 16

    def test_bravo_connection(self, audit_db):
        cur = audit_db.execute("SELECT * FROM connections WHERE conn_id=1")
        row = cur.fetchone()
        assert row['client_key_hex'] == KEY_BRAVO
        assert row['is_mesh_peer'] == 0
        assert row['handshake_complete'] == 1
        assert row['frame_count'] == 12

    def test_charlie_connection(self, audit_db):
        cur = audit_db.execute("SELECT * FROM connections WHERE conn_id=2")
        row = cur.fetchone()
        assert row['client_key_hex'] == KEY_CHARLIE
        assert row['is_mesh_peer'] == 0
        assert row['handshake_complete'] == 1
        assert row['frame_count'] == 8

    def test_mesh_west_connection(self, audit_db):
        cur = audit_db.execute("SELECT * FROM connections WHERE conn_id=3")
        row = cur.fetchone()
        assert row['client_key_hex'] == KEY_MESH_WEST
        assert row['is_mesh_peer'] == 1
        assert row['handshake_complete'] == 1
        assert row['frame_count'] == 10

    def test_rogue_connection(self, audit_db):
        cur = audit_db.execute("SELECT * FROM connections WHERE conn_id=4")
        row = cur.fetchone()
        assert row['client_key_hex'] is None
        assert row['is_mesh_peer'] == 0
        assert row['handshake_complete'] == 0
        assert row['frame_count'] == 2

    def test_alpha_dup_connection(self, audit_db):
        cur = audit_db.execute("SELECT * FROM connections WHERE conn_id=5")
        row = cur.fetchone()
        assert row['client_key_hex'] == KEY_ALPHA
        assert row['is_mesh_peer'] == 0
        assert row['handshake_complete'] == 1
        assert row['frame_count'] == 3


# ── Routing events table tests ───────────────────────────────────────────

class TestRoutingEvents:
    def test_total_routing_events(self, audit_db):
        cur = audit_db.execute("SELECT COUNT(*) FROM routing_events")
        assert cur.fetchone()[0] == 17

    def test_send_event_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM routing_events WHERE event_type='send'")
        assert cur.fetchone()[0] == 8

    def test_recv_event_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM routing_events WHERE event_type='recv'")
        assert cur.fetchone()[0] == 8

    def test_forward_event_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM routing_events WHERE event_type='forward'")
        assert cur.fetchone()[0] == 1

    def test_total_send_data_bytes(self, audit_db):
        cur = audit_db.execute(
            "SELECT SUM(data_bytes) FROM routing_events WHERE event_type='send'")
        assert cur.fetchone()[0] == 1010

    def test_total_recv_data_bytes(self, audit_db):
        cur = audit_db.execute(
            "SELECT SUM(data_bytes) FROM routing_events WHERE event_type='recv'")
        assert cur.fetchone()[0] == 1050

    def test_total_forward_data_bytes(self, audit_db):
        cur = audit_db.execute(
            "SELECT SUM(data_bytes) FROM routing_events WHERE event_type='forward'")
        assert cur.fetchone()[0] == 90

    def test_null_src_for_rogue_send(self, audit_db):
        """The rogue connection (no ClientInfo) should have NULL src_key."""
        cur = audit_db.execute(
            "SELECT src_key_hex FROM routing_events "
            "WHERE event_type='send' AND src_key_hex IS NULL")
        rows = cur.fetchall()
        assert len(rows) == 1


# ── Anomalies table tests ───────────────────────────────────────────────

class TestAnomalies:
    def test_total_anomaly_count(self, audit_db):
        cur = audit_db.execute("SELECT COUNT(*) FROM anomalies")
        assert cur.fetchone()[0] == 6

    def test_split_brain_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM anomalies WHERE anomaly_type='split_brain'")
        assert cur.fetchone()[0] == 1

    def test_split_brain_conn_id(self, audit_db):
        cur = audit_db.execute(
            "SELECT conn_id FROM anomalies WHERE anomaly_type='split_brain'")
        assert cur.fetchone()[0] == 5

    def test_handshake_violation_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM anomalies WHERE anomaly_type='handshake_violation'")
        assert cur.fetchone()[0] == 1

    def test_handshake_violation_conn_id(self, audit_db):
        cur = audit_db.execute(
            "SELECT conn_id FROM anomalies WHERE anomaly_type='handshake_violation'")
        assert cur.fetchone()[0] == 4

    def test_unauthorized_mesh_op_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM anomalies WHERE anomaly_type='unauthorized_mesh_op'")
        assert cur.fetchone()[0] == 1

    def test_unauthorized_mesh_op_conn_id(self, audit_db):
        cur = audit_db.execute(
            "SELECT conn_id FROM anomalies WHERE anomaly_type='unauthorized_mesh_op'")
        assert cur.fetchone()[0] == 2

    def test_acl_violation_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM anomalies WHERE anomaly_type='acl_violation'")
        assert cur.fetchone()[0] == 2

    def test_acl_violation_conn_ids(self, audit_db):
        cur = audit_db.execute(
            "SELECT DISTINCT conn_id FROM anomalies WHERE anomaly_type='acl_violation'")
        conn_ids = [row[0] for row in cur]
        assert conn_ids == [2], "Both ACL violations should be from charlie (conn 2)"

    def test_phantom_peer_count(self, audit_db):
        cur = audit_db.execute(
            "SELECT COUNT(*) FROM anomalies WHERE anomaly_type='phantom_peer'")
        assert cur.fetchone()[0] == 1

    def test_phantom_peer_conn_id(self, audit_db):
        cur = audit_db.execute(
            "SELECT conn_id FROM anomalies WHERE anomaly_type='phantom_peer'")
        assert cur.fetchone()[0] == 3


# ── JSON report tests ───────────────────────────────────────────────────

class TestAuditJsonBasics:
    def test_total_frames(self, audit_json):
        assert audit_json['total_frames'] == TOTAL_FRAMES

    def test_frame_type_distribution_keys(self, audit_json):
        dist = audit_json['frame_type_distribution']
        assert dist['FrameServerKey'] == 6
        assert dist['FrameClientInfo'] == 5
        assert dist['FrameSendPacket'] == 8
        assert dist['FrameRecvPacket'] == 8
        assert dist['FrameForwardPacket'] == 1
        assert dist['FrameWatchConns'] == 2

    def test_frame_type_sum(self, audit_json):
        assert sum(audit_json['frame_type_distribution'].values()) == TOTAL_FRAMES


class TestAuditJsonConnections:
    def test_connections_count(self, audit_json):
        assert len(audit_json['connections_summary']) == 6

    def test_mesh_peer_identification(self, audit_json):
        mesh_conns = [c for c in audit_json['connections_summary']
                      if c['is_mesh_peer']]
        assert len(mesh_conns) == 1
        assert mesh_conns[0]['conn_id'] == 3
        assert mesh_conns[0]['client_key_hex'] == KEY_MESH_WEST

    def test_incomplete_handshake(self, audit_json):
        rogue = [c for c in audit_json['connections_summary']
                 if c['conn_id'] == 4][0]
        assert rogue['handshake_complete'] is False
        assert rogue['client_key_hex'] is None


class TestAuditJsonServerKey:
    def test_server_key_verified(self, audit_json):
        assert audit_json['server_key_verified'] is True

    def test_server_key_fingerprint(self, audit_json):
        expected_fp = _server_key_fingerprint()
        assert audit_json['server_key_fingerprint'] == expected_fp


class TestAuditJsonRouting:
    def test_total_send(self, audit_json):
        assert audit_json['routing_summary']['total_send'] == 8

    def test_total_recv(self, audit_json):
        assert audit_json['routing_summary']['total_recv'] == 8

    def test_total_forward(self, audit_json):
        assert audit_json['routing_summary']['total_forward'] == 1

    def test_total_data_bytes(self, audit_json):
        assert audit_json['routing_summary']['total_data_bytes'] == 2150


class TestAuditJsonAnomalies:
    def test_total_anomalies(self, audit_json):
        assert audit_json['total_anomalies'] == 6

    def test_anomaly_counts(self, audit_json):
        ac = audit_json['anomaly_counts']
        assert ac.get('split_brain') == 1
        assert ac.get('handshake_violation') == 1
        assert ac.get('unauthorized_mesh_op') == 1
        assert ac.get('acl_violation') == 2
        assert ac.get('phantom_peer') == 1


class TestAuditJsonACLCompliance:
    def test_evaluated_sends(self, audit_json):
        assert audit_json['acl_compliance']['evaluated_sends'] == 7

    def test_permitted_sends(self, audit_json):
        assert audit_json['acl_compliance']['permitted_sends'] == 5

    def test_denied_sends(self, audit_json):
        assert audit_json['acl_compliance']['denied_sends'] == 2

    def test_compliance_ratio(self, audit_json):
        ratio = audit_json['acl_compliance']['compliance_ratio']
        assert abs(ratio - 5 / 7) < 0.001
