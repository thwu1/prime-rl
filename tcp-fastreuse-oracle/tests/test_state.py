"""
Tests for TCP bind bucket fastreuse state machine oracle.

Verifies the oracle correctly models Linux kernel TCP port allocation behavior
across 12 scenarios covering bind/connect path interactions, SO_REUSEADDR,
IP_BIND_ADDRESS_NO_PORT, ordering sensitivity, and multi-port ranges.

"""

import json
import os
import subprocess
import pytest

ORACLE = "/app/oracle.py"
SCENARIO_PATH = "/app/scenario.json"
RESULTS_PATH = "/app/results.json"


def run_oracle(scenario):
    """Write scenario to disk, run oracle, return parsed results."""
    with open(SCENARIO_PATH, "w") as f:
        json.dump(scenario, f)
    if os.path.exists(RESULTS_PATH):
        os.remove(RESULTS_PATH)
    result = subprocess.run(
        ["python3", ORACLE],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Oracle exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(RESULTS_PATH), "Oracle did not write /app/results.json"
    with open(RESULTS_PATH) as f:
        return json.load(f)


def assert_step(results, step_num, expected):
    """Assert a single step's outcome matches expected."""
    actual = None
    for s in results["steps"]:
        if s["step"] == step_num:
            actual = s
            break
    assert actual is not None, f"Step {step_num} not found in results"
    assert actual["outcome"] == expected["outcome"], (
        f"Step {step_num}: expected outcome '{expected['outcome']}', "
        f"got '{actual['outcome']}'"
    )
    if "errno" in expected:
        assert actual.get("errno") == expected["errno"], (
            f"Step {step_num}: expected errno '{expected['errno']}', "
            f"got '{actual.get('errno')}'"
        )
    if "port" in expected:
        assert actual.get("port") == expected["port"], (
            f"Step {step_num}: expected port {expected['port']}, "
            f"got {actual.get('port')}"
        )


def assert_buckets(results, expected_buckets):
    """Assert final bind bucket states match expected."""
    actual = results.get("final_buckets", {})
    for port_str, exp in expected_buckets.items():
        assert port_str in actual, (
            f"Expected bucket for port {port_str} not found. "
            f"Actual buckets: {list(actual.keys())}"
        )
        act = actual[port_str]
        assert act["fastreuse"] == exp["fastreuse"], (
            f"Port {port_str}: expected fastreuse {exp['fastreuse']}, "
            f"got {act['fastreuse']}"
        )
        assert act["num_owners"] == exp["num_owners"], (
            f"Port {port_str}: expected {exp['num_owners']} owners, "
            f"got {act['num_owners']}"
        )
    # No extra buckets with owners
    for port_str, act in actual.items():
        if port_str not in expected_buckets:
            assert act["num_owners"] == 0, (
                f"Unexpected bucket for port {port_str} with "
                f"{act['num_owners']} owners"
            )


# ---------------------------------------------------------------------------
# Scenario 1: Two sockets bind to distinct local IPs, same remote.
# ---------------------------------------------------------------------------
class TestBindUniqueIPs:
    def test_both_succeed_sharing_port(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "bind", "id": "s1", "ip": "127.1.1.1", "port": 0},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "bind", "id": "s2", "ip": "127.2.2.2", "port": 0},
                {"step": 6, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 3, {"outcome": "success"})
        assert_step(r, 5, {"outcome": "success", "port": 60000})
        assert_step(r, 6, {"outcome": "success"})
        assert_buckets(r, {"60000": {"fastreuse": 0, "num_owners": 2}})


# ---------------------------------------------------------------------------
# Scenario 2: s1 connect-only, then s2 bind+connect.
# ---------------------------------------------------------------------------
class TestConnectThenBind:
    def test_connect_first_then_bind_succeeds(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "connect", "id": "s1",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
                {"step": 3, "action": "socket", "id": "s2"},
                {"step": 4, "action": "bind", "id": "s2", "ip": "127.2.2.2", "port": 0},
                {"step": 5, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 4, {"outcome": "success", "port": 60000})
        assert_step(r, 5, {"outcome": "success"})
        assert_buckets(r, {"60000": {"fastreuse": 0, "num_owners": 2}})


# ---------------------------------------------------------------------------
# Scenario 3: s1 bind+connect, then s2 connect-only.
# Ordering reversal of Scenario 2 produces a different outcome.
# ---------------------------------------------------------------------------
class TestBindThenConnect:
    def test_bind_first_blocks_later_connect(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "bind", "id": "s1", "ip": "127.1.1.1", "port": 0},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 3, {"outcome": "success"})
        assert_step(r, 5, {"outcome": "error", "errno": "EADDRNOTAVAIL"})
        assert_buckets(r, {"60000": {"fastreuse": 0, "num_owners": 1}})


# ---------------------------------------------------------------------------
# Scenario 4: Both sockets connect-only to different remotes.
# ---------------------------------------------------------------------------
class TestDualConnect:
    def test_two_connects_different_remotes(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 3, "action": "socket", "id": "s2"},
                {"step": 4, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 4, {"outcome": "success", "port": 60000})
        assert_buckets(r, {"60000": {"fastreuse": -1, "num_owners": 2}})


# ---------------------------------------------------------------------------
# Scenario 5: Both bind to same IP, connect to different remotes.
# ---------------------------------------------------------------------------
class TestSameIPBind:
    def test_same_ip_bind_conflict(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "bind", "id": "s1", "ip": "127.0.0.1", "port": 0},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "bind", "id": "s2", "ip": "127.0.0.1", "port": 0},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 3, {"outcome": "success"})
        assert_step(r, 5, {"outcome": "error", "errno": "EADDRINUSE"})
        assert_buckets(r, {"60000": {"fastreuse": 0, "num_owners": 1}})


# ---------------------------------------------------------------------------
# Scenario 6: Both bind to same IP AND explicit same port.
# ---------------------------------------------------------------------------
class TestSameIPPortBind:
    def test_explicit_port_same_ip_conflict(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "bind", "id": "s1",
                 "ip": "127.0.0.1", "port": 60000},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "bind", "id": "s2",
                 "ip": "127.0.0.1", "port": 60000},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 3, {"outcome": "success"})
        assert_step(r, 5, {"outcome": "error", "errno": "EADDRINUSE"})
        assert_buckets(r, {"60000": {"fastreuse": 0, "num_owners": 1}})


# ---------------------------------------------------------------------------
# Scenario 7: SO_REUSEADDR. s1 connect-only, s2 bind+connect.
# ---------------------------------------------------------------------------
class TestReuseaddrConnectThenBind:
    def test_reuseaddr_connect_then_bind(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "setsockopt", "id": "s1",
                 "option": "SO_REUSEADDR", "value": 1},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "setsockopt", "id": "s2",
                 "option": "SO_REUSEADDR", "value": 1},
                {"step": 6, "action": "bind", "id": "s2",
                 "ip": "127.0.0.1", "port": 60000},
                {"step": 7, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 3, {"outcome": "success", "port": 60000})
        assert_step(r, 6, {"outcome": "success", "port": 60000})
        assert_step(r, 7, {"outcome": "success"})
        assert_buckets(r, {"60000": {"fastreuse": 1, "num_owners": 2}})


# ---------------------------------------------------------------------------
# Scenario 8: SO_REUSEADDR reversed order. s1 bind+connect, s2 connect-only.
# Ordering reversal of Scenario 7 produces a different outcome.
# ---------------------------------------------------------------------------
class TestReuseaddrBindThenConnect:
    def test_reuseaddr_bind_first_blocks_connect(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "setsockopt", "id": "s1",
                 "option": "SO_REUSEADDR", "value": 1},
                {"step": 3, "action": "bind", "id": "s1",
                 "ip": "127.0.0.1", "port": 60000},
                {"step": 4, "action": "connect", "id": "s1",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
                {"step": 5, "action": "socket", "id": "s2"},
                {"step": 6, "action": "setsockopt", "id": "s2",
                 "option": "SO_REUSEADDR", "value": 1},
                {"step": 7, "action": "connect", "id": "s2",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 3, {"outcome": "success", "port": 60000})
        assert_step(r, 4, {"outcome": "success"})
        assert_step(r, 7, {"outcome": "error", "errno": "EADDRNOTAVAIL"})
        assert_buckets(r, {"60000": {"fastreuse": 1, "num_owners": 1}})


# ---------------------------------------------------------------------------
# Scenario 9: IP_BIND_ADDRESS_NO_PORT. Both sockets bind to same IP but
# defer port allocation.
# ---------------------------------------------------------------------------
class TestBindAddressNoPort:
    def test_deferred_port_allows_sharing(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "setsockopt", "id": "s1",
                 "option": "IP_BIND_ADDRESS_NO_PORT", "value": 1},
                {"step": 3, "action": "bind", "id": "s1", "ip": "127.0.0.1", "port": 0},
                {"step": 4, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 5, "action": "socket", "id": "s2"},
                {"step": 6, "action": "setsockopt", "id": "s2",
                 "option": "IP_BIND_ADDRESS_NO_PORT", "value": 1},
                {"step": 7, "action": "bind", "id": "s2", "ip": "127.0.0.1", "port": 0},
                {"step": 8, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        # bind steps with BANP should not allocate a port
        assert_step(r, 3, {"outcome": "success"})
        assert_step(r, 4, {"outcome": "success", "port": 60000})
        assert_step(r, 7, {"outcome": "success"})
        assert_step(r, 8, {"outcome": "success", "port": 60000})
        assert_buckets(r, {"60000": {"fastreuse": -1, "num_owners": 2}})


# ---------------------------------------------------------------------------
# Scenario 10: Wider port range with interleaved strategies.
# ephemeral_range = [60000, 60002] (3 ports).
# ---------------------------------------------------------------------------
class TestWiderRangeInterleaved:
    def test_mixed_strategies_across_ports(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60002], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "bind", "id": "s1", "ip": "127.0.0.1", "port": 0},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "connect", "id": "s2",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
                {"step": 6, "action": "socket", "id": "s3"},
                {"step": 7, "action": "connect", "id": "s3",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 8, "action": "socket", "id": "s4"},
                {"step": 9, "action": "connect", "id": "s4",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 5, {"outcome": "success", "port": 60001})
        assert_step(r, 7, {"outcome": "success", "port": 60001})
        assert_step(r, 9, {"outcome": "success", "port": 60002})
        assert_buckets(r, {
            "60000": {"fastreuse": 0, "num_owners": 1},
            "60001": {"fastreuse": -1, "num_owners": 2},
            "60002": {"fastreuse": -1, "num_owners": 1},
        })


# ---------------------------------------------------------------------------
# Scenario 11: A REUSEADDR bind on a bucket previously allocated via
# connect changes its state, affecting subsequent connect attempts.
# ---------------------------------------------------------------------------
class TestFastreusePoisoning:
    def test_reuseaddr_bind_poisons_bucket_for_connect(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "connect", "id": "s1",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 3, "action": "socket", "id": "s2"},
                {"step": 4, "action": "setsockopt", "id": "s2",
                 "option": "SO_REUSEADDR", "value": 1},
                {"step": 5, "action": "bind", "id": "s2", "ip": "127.2.2.2", "port": 0},
                {"step": 6, "action": "connect", "id": "s2",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 7, "action": "socket", "id": "s3"},
                {"step": 8, "action": "connect", "id": "s3",
                 "dst_ip": "127.7.7.7", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 5, {"outcome": "success", "port": 60000})
        assert_step(r, 6, {"outcome": "success"})
        assert_step(r, 8, {"outcome": "error", "errno": "EADDRNOTAVAIL"})
        assert_buckets(r, {"60000": {"fastreuse": 1, "num_owners": 2}})


# ---------------------------------------------------------------------------
# Scenario 12: Socket closure frees bucket slot, allowing new allocations.
# ---------------------------------------------------------------------------
class TestCloseAndReuse:
    def test_close_frees_bucket(self):
        scenario = {
            "config": {"ephemeral_range": [60000, 60000], "auto_src_ip": "127.0.0.1"},
            "operations": [
                {"step": 1, "action": "socket", "id": "s1"},
                {"step": 2, "action": "bind", "id": "s1", "ip": "127.1.1.1", "port": 0},
                {"step": 3, "action": "connect", "id": "s1",
                 "dst_ip": "127.9.9.9", "dst_port": 1234},
                {"step": 4, "action": "socket", "id": "s2"},
                {"step": 5, "action": "connect", "id": "s2",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
                {"step": 6, "action": "close", "id": "s1"},
                {"step": 7, "action": "socket", "id": "s3"},
                {"step": 8, "action": "connect", "id": "s3",
                 "dst_ip": "127.8.8.8", "dst_port": 1234},
            ],
        }
        r = run_oracle(scenario)
        assert_step(r, 2, {"outcome": "success", "port": 60000})
        assert_step(r, 3, {"outcome": "success"})
        assert_step(r, 5, {"outcome": "error", "errno": "EADDRNOTAVAIL"})
        assert_step(r, 6, {"outcome": "success"})
        assert_step(r, 8, {"outcome": "success", "port": 60000})
        assert_buckets(r, {"60000": {"fastreuse": -1, "num_owners": 1}})
