"""
Tests for strace parser, ss parser, and end-to-end forensic pipeline.

Verifies the parsers correctly handle strace and ss output formats,
and that the full pipeline (strace -> oracle -> ss comparison) works.

"""

import json
import os
import subprocess
import tempfile
import pytest


STRACE_PARSER = "/app/strace_parser.py"
SS_PARSER = "/app/ss_parser.py"
ORACLE = "/app/oracle.py"


def run_cmd(args, timeout=15):
    """Run a command and return the result."""
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Strace Parser Tests
# ---------------------------------------------------------------------------
class TestStraceParserCapture01:
    """Parse capture_01: two sockets bind to distinct IPs, both connect."""

    def test_correct_operation_count(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_01.strace",
                      "/app/parsed_01.json", "--ephemeral-lo", "60000",
                      "--ephemeral-hi", "60000"])
        assert r.returncode == 0, f"Parser failed: {r.stderr}"
        with open("/app/parsed_01.json") as f:
            scenario = json.load(f)
        ops = scenario["operations"]
        # socket, bind, connect, socket, bind, connect (getsockname skipped)
        assert len(ops) == 6

    def test_operation_types_and_ips(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_01.strace",
                      "/app/parsed_01.json", "--ephemeral-lo", "60000",
                      "--ephemeral-hi", "60000"])
        assert r.returncode == 0
        with open("/app/parsed_01.json") as f:
            ops = json.load(f)["operations"]

        assert ops[0]["action"] == "socket"
        assert ops[1]["action"] == "bind"
        assert ops[1]["ip"] == "127.1.1.1"
        assert ops[1]["port"] == 0
        assert ops[2]["action"] == "connect"
        assert ops[2]["dst_ip"] == "127.9.9.9"
        assert ops[2]["dst_port"] == 1234
        assert ops[3]["action"] == "socket"
        assert ops[4]["action"] == "bind"
        assert ops[4]["ip"] == "127.2.2.2"
        assert ops[5]["action"] == "connect"

    def test_socket_id_consistency(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_01.strace",
                      "/app/parsed_01.json"])
        assert r.returncode == 0
        with open("/app/parsed_01.json") as f:
            ops = json.load(f)["operations"]

        # First socket's ID should be consistent across its operations
        s1_id = ops[0]["id"]
        assert ops[1]["id"] == s1_id
        assert ops[2]["id"] == s1_id
        # Second socket should have different ID
        s2_id = ops[3]["id"]
        assert s2_id != s1_id
        assert ops[4]["id"] == s2_id
        assert ops[5]["id"] == s2_id


class TestStraceParserCapture02:
    """Parse capture_02: SO_REUSEADDR, failed connect, close."""

    def test_operation_count_with_setsockopt_and_close(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_02.strace",
                      "/app/parsed_02.json", "--ephemeral-lo", "60000",
                      "--ephemeral-hi", "60000"])
        assert r.returncode == 0, f"Parser failed: {r.stderr}"
        with open("/app/parsed_02.json") as f:
            ops = json.load(f)["operations"]
        # socket, setsockopt, bind, connect, socket, setsockopt, connect, close, close
        assert len(ops) == 9

    def test_setsockopt_extraction(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_02.strace",
                      "/app/parsed_02.json"])
        assert r.returncode == 0
        with open("/app/parsed_02.json") as f:
            ops = json.load(f)["operations"]

        assert ops[1]["action"] == "setsockopt"
        assert ops[1]["option"] == "SO_REUSEADDR"
        assert ops[1]["value"] == 1

        assert ops[5]["action"] == "setsockopt"
        assert ops[5]["option"] == "SO_REUSEADDR"
        assert ops[5]["value"] == 1

    def test_explicit_port_bind(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_02.strace",
                      "/app/parsed_02.json"])
        assert r.returncode == 0
        with open("/app/parsed_02.json") as f:
            ops = json.load(f)["operations"]

        assert ops[2]["action"] == "bind"
        assert ops[2]["port"] == 60000
        assert ops[2]["ip"] == "127.0.0.1"

    def test_close_operations(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_02.strace",
                      "/app/parsed_02.json"])
        assert r.returncode == 0
        with open("/app/parsed_02.json") as f:
            ops = json.load(f)["operations"]

        assert ops[7]["action"] == "close"
        assert ops[8]["action"] == "close"
        # Close IDs should match the sockets they belong to
        s2_id = ops[4]["id"]
        s1_id = ops[0]["id"]
        assert ops[7]["id"] == s2_id
        assert ops[8]["id"] == s1_id


class TestStraceParserCapture03:
    """Parse capture_03: multi-PID, unfinished/resumed, IP_BIND_ADDRESS_NO_PORT."""

    def test_multipid_fd_namespace_isolation(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_03.strace",
                      "/app/parsed_03.json", "--ephemeral-lo", "60000",
                      "--ephemeral-hi", "60000"])
        assert r.returncode == 0, f"Parser failed: {r.stderr}"
        with open("/app/parsed_03.json") as f:
            ops = json.load(f)["operations"]

        # 8 ops: socket, setsockopt, bind, socket, setsockopt, bind, connect(resumed), connect
        assert len(ops) == 8

        s1_id = ops[0]["id"]
        s2_id = ops[3]["id"]
        # Both PIDs use fd=3, but should get different socket IDs
        assert s1_id != s2_id

    def test_unfinished_resumed_ordering(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_03.strace",
                      "/app/parsed_03.json"])
        assert r.returncode == 0
        with open("/app/parsed_03.json") as f:
            ops = json.load(f)["operations"]

        s1_id = ops[0]["id"]
        s2_id = ops[3]["id"]

        # s2's socket/setsockopt/bind come BEFORE s1's resumed connect
        assert ops[3]["action"] == "socket"
        assert ops[4]["action"] == "setsockopt"
        assert ops[5]["action"] == "bind"

        # Resumed connect for s1 comes after s2's bind
        assert ops[6]["action"] == "connect"
        assert ops[6]["id"] == s1_id
        assert ops[6]["dst_ip"] == "127.8.8.8"

        # s2's connect comes last
        assert ops[7]["action"] == "connect"
        assert ops[7]["id"] == s2_id
        assert ops[7]["dst_ip"] == "127.9.9.9"

    def test_banp_setsockopt(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_03.strace",
                      "/app/parsed_03.json"])
        assert r.returncode == 0
        with open("/app/parsed_03.json") as f:
            ops = json.load(f)["operations"]

        assert ops[1]["option"] == "IP_BIND_ADDRESS_NO_PORT"
        assert ops[1]["value"] == 1
        assert ops[4]["option"] == "IP_BIND_ADDRESS_NO_PORT"
        assert ops[4]["value"] == 1


class TestStraceParserEdgeCases:
    """Edge cases: noise lines, config passthrough."""

    def test_ignore_signal_and_exit_lines(self):
        strace_text = (
            'socket(AF_INET, SOCK_STREAM|SOCK_CLOEXEC, IPPROTO_TCP) = 3\n'
            '--- SIGCHLD {si_signo=SIGCHLD, si_code=CLD_EXITED, si_pid=5678, '
            'si_uid=0, si_status=0, si_utime=0, si_stime=0} ---\n'
            'bind(3, {sa_family=AF_INET, sin_port=htons(0), '
            'sin_addr=inet_addr("127.1.1.1")}, 16) = 0\n'
            'getsockname(3, {sa_family=AF_INET, sin_port=htons(60000), '
            'sin_addr=inet_addr("127.1.1.1")}, [16]) = 0\n'
            '+++ exited with 0 +++\n'
        )
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.strace', delete=False
        ) as f:
            f.write(strace_text)
            tmp = f.name
        try:
            r = run_cmd(["python3", STRACE_PARSER, tmp, "/app/parsed_noise.json"])
            assert r.returncode == 0, f"Parser failed: {r.stderr}"
            with open("/app/parsed_noise.json") as f:
                ops = json.load(f)["operations"]
            assert len(ops) == 2
            assert ops[0]["action"] == "socket"
            assert ops[1]["action"] == "bind"
        finally:
            os.unlink(tmp)

    def test_config_passthrough(self):
        r = run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_01.strace",
                      "/app/parsed_config.json",
                      "--ephemeral-lo", "32768", "--ephemeral-hi", "60999",
                      "--auto-src-ip", "10.0.0.1"])
        assert r.returncode == 0
        with open("/app/parsed_config.json") as f:
            scenario = json.load(f)
        assert scenario["config"]["ephemeral_range"] == [32768, 60999]
        assert scenario["config"]["auto_src_ip"] == "10.0.0.1"


# ---------------------------------------------------------------------------
# SS Parser Tests
# ---------------------------------------------------------------------------
class TestSSParserCapture01:
    """Parse capture_01.ss: two ESTAB connections sharing a port."""

    def test_connection_count(self):
        r = run_cmd(["python3", SS_PARSER, "/app/captures/capture_01.ss",
                      "/app/conns_01.json"])
        assert r.returncode == 0, f"Parser failed: {r.stderr}"
        with open("/app/conns_01.json") as f:
            conns = json.load(f)
        assert len(conns) == 2

    def test_connection_details(self):
        r = run_cmd(["python3", SS_PARSER, "/app/captures/capture_01.ss",
                      "/app/conns_01.json"])
        assert r.returncode == 0
        with open("/app/conns_01.json") as f:
            conns = json.load(f)
        for conn in conns:
            assert conn["state"] == "ESTAB"
            assert conn["peer_ip"] == "127.9.9.9"
            assert conn["peer_port"] == 1234
            assert conn["local_port"] == 60000
        local_ips = {c["local_ip"] for c in conns}
        assert local_ips == {"127.1.1.1", "127.2.2.2"}

    def test_process_info(self):
        r = run_cmd(["python3", SS_PARSER, "/app/captures/capture_01.ss",
                      "/app/conns_01.json"])
        assert r.returncode == 0
        with open("/app/conns_01.json") as f:
            conns = json.load(f)
        for conn in conns:
            assert conn["pid"] == 5001
        fds = {c["fd"] for c in conns}
        assert fds == {3, 4}


class TestSSParserCapture02:
    """Parse capture_02.ss: single ESTAB connection."""

    def test_single_connection(self):
        r = run_cmd(["python3", SS_PARSER, "/app/captures/capture_02.ss",
                      "/app/conns_02.json"])
        assert r.returncode == 0, f"Parser failed: {r.stderr}"
        with open("/app/conns_02.json") as f:
            conns = json.load(f)
        assert len(conns) == 1
        assert conns[0]["state"] == "ESTAB"
        assert conns[0]["local_ip"] == "127.0.0.1"
        assert conns[0]["local_port"] == 60000
        assert conns[0]["peer_ip"] == "127.9.9.9"
        assert conns[0]["peer_port"] == 1234


class TestSSParserCapture03:
    """Parse capture_03.ss: two connections from different PIDs sharing port."""

    def test_multipid_same_port(self):
        r = run_cmd(["python3", SS_PARSER, "/app/captures/capture_03.ss",
                      "/app/conns_03.json"])
        assert r.returncode == 0, f"Parser failed: {r.stderr}"
        with open("/app/conns_03.json") as f:
            conns = json.load(f)
        assert len(conns) == 2
        for conn in conns:
            assert conn["local_ip"] == "127.0.0.1"
            assert conn["local_port"] == 60000
        pids = {c["pid"] for c in conns}
        assert pids == {2001, 2002}
        peer_ips = {c["peer_ip"] for c in conns}
        assert peer_ips == {"127.8.8.8", "127.9.9.9"}


class TestSSParserMixedStates:
    """Parse ss output with multiple TCP states and missing process info."""

    def test_mixed_states_and_wildcards(self):
        ss_text = (
            "State    Recv-Q  Send-Q    Local Address:Port     "
            "Peer Address:Port  Process\n"
            "LISTEN   0       128       0.0.0.0:8080           "
            "0.0.0.0:*\n"
            "ESTAB    0       0         10.0.0.1:8080          "
            "10.0.0.2:45678     users:((\"httpd\",pid=1000,fd=7))\n"
            "TIME-WAIT 0      0         10.0.0.1:8080          "
            "10.0.0.3:34567\n"
            "CLOSE-WAIT 0     0         10.0.0.1:8080          "
            "10.0.0.5:23456     users:((\"httpd\",pid=1000,fd=11))\n"
        )
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.ss', delete=False
        ) as f:
            f.write(ss_text)
            tmp = f.name
        try:
            r = run_cmd(["python3", SS_PARSER, tmp, "/app/conns_mixed.json"])
            assert r.returncode == 0, f"Parser failed: {r.stderr}"
            with open("/app/conns_mixed.json") as f:
                conns = json.load(f)

            assert len(conns) == 4
            states = [c["state"] for c in conns]
            assert "LISTEN" in states
            assert "ESTAB" in states
            assert "TIME-WAIT" in states
            assert "CLOSE-WAIT" in states

            # LISTEN socket has wildcard peer port
            listen = next(c for c in conns if c["state"] == "LISTEN")
            assert listen["peer_port"] == 0

            # TIME-WAIT has no process info
            tw = next(c for c in conns if c["state"] == "TIME-WAIT")
            assert "pid" not in tw

            # ESTAB has process info
            estab = next(c for c in conns if c["state"] == "ESTAB")
            assert estab["pid"] == 1000
            assert estab["fd"] == 7
        finally:
            os.unlink(tmp)


# ---------------------------------------------------------------------------
# End-to-End Pipeline Tests
# ---------------------------------------------------------------------------
class TestPipelineCapture01:
    """End-to-end: strace -> oracle produces correct predictions."""

    def test_oracle_all_success(self):
        run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_01.strace",
                 "/app/scenario.json", "--ephemeral-lo", "60000",
                 "--ephemeral-hi", "60000"])
        r = run_cmd(["python3", ORACLE])
        assert r.returncode == 0, f"Oracle failed: {r.stderr}"
        with open("/app/results.json") as f:
            results = json.load(f)

        for step in results["steps"]:
            assert step["outcome"] == "success", (
                f"Step {step['step']} failed unexpectedly"
            )

    def test_bucket_state(self):
        run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_01.strace",
                 "/app/scenario.json", "--ephemeral-lo", "60000",
                 "--ephemeral-hi", "60000"])
        run_cmd(["python3", ORACLE])
        with open("/app/results.json") as f:
            results = json.load(f)

        assert "60000" in results["final_buckets"]
        assert results["final_buckets"]["60000"]["num_owners"] == 2
        assert results["final_buckets"]["60000"]["fastreuse"] == 0

    def test_ss_agreement(self):
        """SS connections match oracle's predicted established connections."""
        run_cmd(["python3", SS_PARSER, "/app/captures/capture_01.ss",
                 "/app/connections.json"])
        with open("/app/connections.json") as f:
            conns = json.load(f)

        estab = [c for c in conns if c["state"] == "ESTAB"]
        assert len(estab) == 2
        assert all(c["local_port"] == 60000 for c in estab)
        assert {c["local_ip"] for c in estab} == {"127.1.1.1", "127.2.2.2"}


class TestPipelineCapture02:
    """End-to-end: strace with errors -> oracle detects failure."""

    def test_connect_error_detected(self):
        run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_02.strace",
                 "/app/scenario.json", "--ephemeral-lo", "60000",
                 "--ephemeral-hi", "60000"])
        r = run_cmd(["python3", ORACLE])
        assert r.returncode == 0, f"Oracle failed: {r.stderr}"
        with open("/app/results.json") as f:
            results = json.load(f)

        errors = [s for s in results["steps"] if s["outcome"] == "error"]
        assert len(errors) == 1
        assert errors[0]["errno"] == "EADDRNOTAVAIL"

    def test_empty_buckets_after_close(self):
        run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_02.strace",
                 "/app/scenario.json", "--ephemeral-lo", "60000",
                 "--ephemeral-hi", "60000"])
        run_cmd(["python3", ORACLE])
        with open("/app/results.json") as f:
            results = json.load(f)

        assert len(results["final_buckets"]) == 0


class TestPipelineCapture03:
    """End-to-end: multi-PID BANP strace -> oracle -> ss consistency."""

    def test_banp_sharing(self):
        run_cmd(["python3", STRACE_PARSER, "/app/captures/capture_03.strace",
                 "/app/scenario.json", "--ephemeral-lo", "60000",
                 "--ephemeral-hi", "60000"])
        r = run_cmd(["python3", ORACLE])
        assert r.returncode == 0, f"Oracle failed: {r.stderr}"
        with open("/app/results.json") as f:
            results = json.load(f)

        # All operations succeed
        for step in results["steps"]:
            assert step["outcome"] == "success", (
                f"Step {step['step']} failed: {step}"
            )

        # BANP deferred allocation
        assert results["final_buckets"]["60000"]["fastreuse"] == -1
        assert results["final_buckets"]["60000"]["num_owners"] == 2

    def test_ss_matches_oracle_port(self):
        run_cmd(["python3", SS_PARSER, "/app/captures/capture_03.ss",
                 "/app/connections.json"])
        with open("/app/connections.json") as f:
            conns = json.load(f)

        assert len(conns) == 2
        for c in conns:
            assert c["local_port"] == 60000
            assert c["state"] == "ESTAB"
