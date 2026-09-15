#!/usr/bin/env python3
"""
Tests for the network control plane forensic recovery task.

Verifies that:
1. The SQLite database has a correctly restored routes table with all 30 routes
2. The manual operator override is preserved
3. The network topology has been corrected (link cost reverted)
4. The control plane server is running on the correct port
5. The API serves correct route data
6. Configuration has been properly restored
"""

import sqlite3
import json
import os
import pytest

try:
    import requests
except ImportError:
    pytest.skip("requests not installed", allow_module_level=True)

DB_PATH = '/app/db/network.db'
API_BASE = 'http://localhost:5000'
TOPOLOGY_PATH = '/app/config/topology.json'

# The complete set of correct routes
# (source_node, destination_network) -> (next_hop_node, metric)
EXPECTED_ROUTES = {
    ('gateway', '10.0.2.0/24'): ('auth', 10),
    ('gateway', '10.0.3.0/24'): ('api', 10),
    ('gateway', '10.0.4.0/24'): ('api', 20),
    ('gateway', '10.0.5.0/24'): ('api', 20),
    ('gateway', '10.0.6.0/24'): ('api', 30),
    ('auth', '10.0.1.0/24'): ('gateway', 10),
    ('auth', '10.0.3.0/24'): ('api', 10),
    ('auth', '10.0.4.0/24'): ('api', 20),
    ('auth', '10.0.5.0/24'): ('api', 20),
    ('auth', '10.0.6.0/24'): ('api', 30),
    ('api', '10.0.1.0/24'): ('gateway', 10),
    ('api', '10.0.2.0/24'): ('auth', 10),
    ('api', '10.0.4.0/24'): ('compute-east', 10),
    ('api', '10.0.5.0/24'): ('compute-west', 10),
    ('api', '10.0.6.0/24'): ('compute-east', 20),
    ('compute-east', '10.0.1.0/24'): ('api', 20),
    ('compute-east', '10.0.2.0/24'): ('api', 20),
    ('compute-east', '10.0.3.0/24'): ('api', 10),
    ('compute-east', '10.0.5.0/24'): ('api', 20),
    ('compute-east', '10.0.6.0/24'): ('storage', 10),
    ('compute-west', '10.0.1.0/24'): ('api', 20),
    ('compute-west', '10.0.2.0/24'): ('api', 20),
    ('compute-west', '10.0.3.0/24'): ('api', 10),
    ('compute-west', '10.0.4.0/24'): ('storage', 15),
    ('compute-west', '10.0.6.0/24'): ('storage', 10),
    ('storage', '10.0.1.0/24'): ('compute-east', 30),
    ('storage', '10.0.2.0/24'): ('compute-east', 30),
    ('storage', '10.0.3.0/24'): ('compute-east', 20),
    ('storage', '10.0.4.0/24'): ('compute-east', 10),
    ('storage', '10.0.5.0/24'): ('compute-west', 10),
}


class TestDatabaseRecovery:
    """Test that the routing database has been correctly restored."""

    def test_routes_table_exists(self):
        """Routes table must exist in the database."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='routes'"
        )
        result = cursor.fetchone()
        conn.close()
        assert result is not None, "routes table does not exist in the database"

    def test_correct_number_of_routes(self):
        """Database must contain exactly 30 routes."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("SELECT COUNT(*) FROM routes")
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 30, f"Expected 30 routes, got {count}"

    def test_all_routes_present_and_correct(self):
        """Every expected route must be present with correct next_hop and metric."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT source_node, destination_network, next_hop_node, metric "
            "FROM routes"
        ).fetchall()
        conn.close()

        actual_routes = {}
        for row in rows:
            key = (row['source_node'], row['destination_network'])
            actual_routes[key] = (row['next_hop_node'], row['metric'])

        errors = []
        for key, expected in EXPECTED_ROUTES.items():
            if key not in actual_routes:
                errors.append(f"MISSING: {key[0]} -> {key[1]}")
            elif actual_routes[key] != expected:
                actual = actual_routes[key]
                errors.append(
                    f"WRONG: {key[0]} -> {key[1]}: "
                    f"expected via={expected[0]} metric={expected[1]}, "
                    f"got via={actual[0]} metric={actual[1]}"
                )

        assert not errors, "Route errors:\n" + "\n".join(errors)

    def test_all_routes_active(self):
        """All routes must have status 'active'."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM routes WHERE status != 'active'"
        )
        count = cursor.fetchone()[0]
        conn.close()
        assert count == 0, f"{count} routes have non-active status"

    def test_no_duplicate_routes(self):
        """No duplicate (source_node, destination_network) pairs."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT source_node, destination_network, COUNT(*) as cnt "
            "FROM routes GROUP BY source_node, destination_network HAVING cnt > 1"
        )
        dupes = cursor.fetchall()
        conn.close()
        assert len(dupes) == 0, f"Found duplicate routes: {dupes}"

    def test_manual_override_preserved(self):
        """The manual override for compute-west -> 10.0.4.0/24 must use storage with metric 15."""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT next_hop_node, metric FROM routes "
            "WHERE source_node = 'compute-west' AND destination_network = '10.0.4.0/24'"
        ).fetchone()
        conn.close()
        assert row is not None, "Override route compute-west -> 10.0.4.0/24 not found"
        assert row['next_hop_node'] == 'storage', \
            f"Override next_hop should be 'storage', got '{row['next_hop_node']}'"
        assert row['metric'] == 15, \
            f"Override metric should be 15, got {row['metric']}"

    def test_each_node_has_five_routes(self):
        """Each of the 6 nodes must have exactly 5 routes."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT source_node, COUNT(*) as cnt FROM routes "
            "GROUP BY source_node ORDER BY source_node"
        )
        node_counts = {row[0]: row[1] for row in cursor.fetchall()}
        conn.close()

        expected_nodes = ['api', 'auth', 'compute-east', 'compute-west', 'gateway', 'storage']
        for node in expected_nodes:
            assert node in node_counts, f"No routes found for node '{node}'"
            assert node_counts[node] == 5, \
                f"Node '{node}' has {node_counts[node]} routes, expected 5"


class TestTopologyRestored:
    """Test that the network topology has been corrected."""

    def test_topology_file_exists(self):
        """topology.json must exist."""
        assert os.path.exists(TOPOLOGY_PATH), "topology.json not found"

    def test_compute_east_storage_link_cost(self):
        """The compute-east <-> storage link cost must be 10 (not the corrupted value of 15)."""
        with open(TOPOLOGY_PATH) as f:
            topo = json.load(f)
        for link in topo['links']:
            if set([link['node_a'], link['node_b']]) == set(['compute-east', 'storage']):
                assert link['cost'] == 10, \
                    f"compute-east <-> storage link cost should be 10, got {link['cost']}"
                return
        pytest.fail("compute-east <-> storage link not found in topology")

    def test_all_link_costs_are_ten(self):
        """All link costs in the topology must be 10 (original values)."""
        with open(TOPOLOGY_PATH) as f:
            topo = json.load(f)
        for link in topo['links']:
            assert link['cost'] == 10, \
                f"Link {link['node_a']}<->{link['node_b']} cost should be 10, got {link['cost']}"


class TestControlPlaneServer:
    """Test that the control plane server is running and serving correct data."""

    def test_server_running_on_port_5000(self):
        """Control plane server must be accessible on port 5000."""
        try:
            resp = requests.get(f'{API_BASE}/health', timeout=10)
            assert resp.status_code == 200, f"Health endpoint returned {resp.status_code}"
            data = resp.json()
            assert data.get('status') == 'healthy', f"Server reports unhealthy: {data}"
        except requests.exceptions.ConnectionError:
            pytest.fail("Control plane server is not running on port 5000")

    def test_api_returns_all_routes(self):
        """GET /routes must return all 30 routes."""
        try:
            resp = requests.get(f'{API_BASE}/routes', timeout=10)
            assert resp.status_code == 200, f"API returned {resp.status_code}"
            routes = resp.json()
            assert len(routes) == 30, f"API returned {len(routes)} routes, expected 30"
        except requests.exceptions.ConnectionError:
            pytest.fail("Control plane server not accessible on port 5000")

    def test_api_routes_match_expected(self):
        """Routes returned by the API must match all expected values."""
        try:
            resp = requests.get(f'{API_BASE}/routes', timeout=10)
            assert resp.status_code == 200
            api_routes = {}
            for r in resp.json():
                key = (r['source_node'], r['destination_network'])
                api_routes[key] = (r['next_hop_node'], r['metric'])

            errors = []
            for key, expected in EXPECTED_ROUTES.items():
                if key not in api_routes:
                    errors.append(f"API MISSING: {key[0]} -> {key[1]}")
                elif api_routes[key] != expected:
                    actual = api_routes[key]
                    errors.append(
                        f"API WRONG: {key[0]} -> {key[1]}: "
                        f"expected via={expected[0]} metric={expected[1]}, "
                        f"got via={actual[0]} metric={actual[1]}"
                    )
            assert not errors, "API route errors:\n" + "\n".join(errors)
        except requests.exceptions.ConnectionError:
            pytest.fail("Control plane server not accessible on port 5000")

    def test_per_node_routes(self):
        """GET /routes/<node> must return 5 routes for each node."""
        nodes = ['gateway', 'auth', 'api', 'compute-east', 'compute-west', 'storage']
        for node in nodes:
            try:
                resp = requests.get(f'{API_BASE}/routes/{node}', timeout=10)
                assert resp.status_code == 200, \
                    f"API returned {resp.status_code} for node '{node}'"
                routes = resp.json()
                assert len(routes) == 5, \
                    f"Node '{node}' should have 5 routes via API, got {len(routes)}"
            except requests.exceptions.ConnectionError:
                pytest.fail(f"Control plane server not accessible for node '{node}'")


class TestServerConfiguration:
    """Test that server configuration has been properly restored."""

    def test_server_ini_correct_port(self):
        """server.ini must specify port 5000."""
        import configparser
        config = configparser.ConfigParser()
        config.read('/app/config/server.ini')
        port = config.getint('server', 'port')
        assert port == 5000, \
            f"server.ini port should be 5000, got {port}"

    def test_control_plane_pid_valid(self):
        """If a control plane PID file exists, it must point to a running process."""
        pid_file = '/var/run/control_plane.pid'
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                try:
                    pid = int(f.read().strip())
                except ValueError:
                    pytest.fail(f"PID file {pid_file} contains invalid content")
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                pytest.fail(
                    f"Stale PID file {pid_file} points to non-existent process {pid}"
                )
