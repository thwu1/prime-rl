
import json
import subprocess
import pytest


def run_nftrace(config_dir, output_file):
    """Run the nftrace tool and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/nftrace.py", config_dir, output_file],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"nftrace exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    with open(output_file) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def scenario1():
    return run_nftrace("/app/config", "/app/output/trace1.json")


@pytest.fixture(scope="module")
def scenario2():
    return run_nftrace("/tests/scenario2/config", "/app/output/trace2.json")


# ─── Scenario 1: conntrack max=8, tcp_loose=true, 20 packets ───


class TestScenario1Verdicts:
    """Verify per-packet verdicts in the main scenario."""

    def test_accepted_packets(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        accepted = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 13, 15, 17, 20]
        for pid in accepted:
            assert results[pid]["verdict"] == "ACCEPT", f"Packet {pid} should be ACCEPT"

    def test_conntrack_overflow_drops(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        overflow = [12, 14, 16, 18, 19]
        for pid in overflow:
            assert results[pid]["verdict"] == "DROP", f"Packet {pid} should be DROP"
            assert results[pid]["drop_layer"] == "conntrack_overflow", (
                f"Packet {pid} should be dropped by conntrack overflow"
            )

    def test_firewall_drop(self, scenario1):
        """Packet 7: SSH SYN from untrusted IP → DROPped in filter INPUT."""
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[7]["verdict"] == "DROP"
        assert results[7]["drop_layer"] == "filter_INPUT"

    def test_stray_ack_overflow_with_loose(self, scenario1):
        """Packet 19: stray ACK with tcp_loose=true → creates NEW → overflow."""
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[19]["verdict"] == "DROP"
        assert results[19]["drop_layer"] == "conntrack_overflow"


class TestScenario1ConntrackStates:
    """Verify conntrack state assignments."""

    def test_new_connections(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        new_pkts = [1, 2, 4, 6, 7, 8, 9, 10, 11]
        for pid in new_pkts:
            assert results[pid]["conntrack_state"] == "NEW", (
                f"Packet {pid} should have ctstate NEW"
            )

    def test_established_connections(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        for pid in [5, 13, 17]:
            assert results[pid]["conntrack_state"] == "ESTABLISHED", (
                f"Packet {pid} should have ctstate ESTABLISHED"
            )

    def test_untracked_packets(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        for pid in [3, 15, 20]:
            assert results[pid]["conntrack_state"] == "UNTRACKED", (
                f"Packet {pid} should have ctstate UNTRACKED"
            )

    def test_overflow_packets_null_state(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        for pid in [12, 14, 16, 18, 19]:
            assert results[pid]["conntrack_state"] is None, (
                f"Packet {pid} (overflow) should have null ctstate"
            )


class TestScenario1Counters:
    """Verify rule counters match expected iptables -nvx output."""

    def test_raw_prerouting_counter_discrepancy(self, scenario1):
        """The key diagnostic: raw sees more packets than mangle.
        Difference equals conntrack overflow drops."""
        c = scenario1["rule_counters"]
        raw_ct = c["2"]["packets"]      # CT rule in raw
        notrack = c["1"]["packets"]     # NOTRACK rule
        mangle = c["3"]["packets"]      # counter in mangle
        total_raw = raw_ct + notrack
        assert total_raw - mangle == 5, "Counter discrepancy should equal overflow drops"

    def test_notrack_counter(self, scenario1):
        assert scenario1["rule_counters"]["1"] == {"packets": 3, "bytes": 240}

    def test_ct_counter(self, scenario1):
        assert scenario1["rule_counters"]["2"] == {"packets": 17, "bytes": 988}

    def test_mangle_counter(self, scenario1):
        assert scenario1["rule_counters"]["3"] == {"packets": 15, "bytes": 936}

    def test_ssh_trusted_counter(self, scenario1):
        assert scenario1["rule_counters"]["4"] == {"packets": 1, "bytes": 60}

    def test_ssh_drop_counter(self, scenario1):
        assert scenario1["rule_counters"]["5"] == {"packets": 1, "bytes": 60}

    def test_established_counter(self, scenario1):
        assert scenario1["rule_counters"]["6"] == {"packets": 3, "bytes": 156}

    def test_new_http_counter(self, scenario1):
        assert scenario1["rule_counters"]["7"] == {"packets": 6, "bytes": 360}

    def test_dns_counter(self, scenario1):
        assert scenario1["rule_counters"]["8"] == {"packets": 3, "bytes": 240}

    def test_new_https_counter(self, scenario1):
        assert scenario1["rule_counters"]["9"] == {"packets": 1, "bytes": 60}

    def test_default_drop_counter(self, scenario1):
        assert scenario1["rule_counters"]["10"] == {"packets": 0, "bytes": 0}


class TestScenario1ConntrackStats:
    def test_confirmed_entries(self, scenario1):
        assert scenario1["conntrack_stats"]["confirmed_entries"] == 8

    def test_overflow_drops(self, scenario1):
        assert scenario1["conntrack_stats"]["overflow_drops"] == 5

    def test_unconfirmed_drops(self, scenario1):
        """Packet 7 creates unconfirmed entry then DROPped → 1 unconfirmed drop."""
        assert scenario1["conntrack_stats"]["unconfirmed_drops"] == 1


class TestScenario1MatchedRules:
    """Verify rule matching path for key packets."""

    def test_normal_syn_path(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[1]["matched_rules"] == [2, 3, 7]

    def test_notrack_path(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[3]["matched_rules"] == [1, 3, 8]

    def test_established_path(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[5]["matched_rules"] == [2, 3, 6]

    def test_firewall_drop_path(self, scenario1):
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[7]["matched_rules"] == [2, 3, 5]

    def test_overflow_path(self, scenario1):
        """Overflow packets only match the raw PREROUTING rule."""
        results = {r["packet_id"]: r for r in scenario1["packet_results"]}
        assert results[12]["matched_rules"] == [2]


# ─── Scenario 2: conntrack max=3, tcp_loose=false, 10 packets ───


class TestScenario2Verdicts:
    def test_accepted_packets(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        for pid in [1, 2, 3, 4, 6, 8, 10]:
            assert results[pid]["verdict"] == "ACCEPT", f"Packet {pid} should be ACCEPT"

    def test_overflow_drops(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        for pid in [5, 9]:
            assert results[pid]["verdict"] == "DROP"
            assert results[pid]["drop_layer"] == "conntrack_overflow"

    def test_stray_ack_with_loose_false(self, scenario2):
        """Packet 7: stray ACK with tcp_loose=false → INVALID → filter DROP.
        This is the critical test: with tcp_loose=false, the stray ACK does NOT
        create a new flow, so it passes conntrack even though the table is full.
        It then gets INVALID ctstate and is dropped by filter rules."""
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[7]["verdict"] == "DROP"
        assert results[7]["drop_layer"] == "filter_INPUT"
        assert results[7]["conntrack_state"] == "INVALID"


class TestScenario2ConntrackStates:
    def test_new_flows(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        for pid in [1, 2, 4]:
            assert results[pid]["conntrack_state"] == "NEW"

    def test_established_flow(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[6]["conntrack_state"] == "ESTABLISHED"

    def test_untracked_notrack(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        for pid in [3, 8, 10]:
            assert results[pid]["conntrack_state"] == "UNTRACKED"

    def test_invalid_stray_ack(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[7]["conntrack_state"] == "INVALID"


class TestScenario2Counters:
    def test_notrack_counter(self, scenario2):
        assert scenario2["rule_counters"]["1"] == {"packets": 3, "bytes": 172}

    def test_ct_counter(self, scenario2):
        assert scenario2["rule_counters"]["2"] == {"packets": 7, "bytes": 404}

    def test_mangle_counter(self, scenario2):
        assert scenario2["rule_counters"]["3"] == {"packets": 8, "bytes": 456}

    def test_established_counter(self, scenario2):
        assert scenario2["rule_counters"]["4"] == {"packets": 1, "bytes": 52}

    def test_new_http_counter(self, scenario2):
        assert scenario2["rule_counters"]["5"] == {"packets": 3, "bytes": 180}

    def test_https_counter(self, scenario2):
        assert scenario2["rule_counters"]["6"] == {"packets": 3, "bytes": 172}

    def test_default_drop_counter(self, scenario2):
        assert scenario2["rule_counters"]["7"] == {"packets": 1, "bytes": 52}


class TestScenario2ConntrackStats:
    def test_confirmed_entries(self, scenario2):
        assert scenario2["conntrack_stats"]["confirmed_entries"] == 3

    def test_overflow_drops(self, scenario2):
        assert scenario2["conntrack_stats"]["overflow_drops"] == 2

    def test_unconfirmed_drops(self, scenario2):
        assert scenario2["conntrack_stats"]["unconfirmed_drops"] == 0


class TestScenario2MatchedRules:
    def test_notrack_path(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[3]["matched_rules"] == [1, 3, 6]

    def test_invalid_ack_path(self, scenario2):
        """Stray ACK with loose=false hits default DROP in filter."""
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[7]["matched_rules"] == [2, 3, 7]

    def test_established_path(self, scenario2):
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[6]["matched_rules"] == [2, 3, 4]

    def test_notrack_ack_path(self, scenario2):
        """Packet 10: ACK to port 443 → NOTRACK → UNTRACKED → rule 6."""
        results = {r["packet_id"]: r for r in scenario2["packet_results"]}
        assert results[10]["matched_rules"] == [1, 3, 6]
