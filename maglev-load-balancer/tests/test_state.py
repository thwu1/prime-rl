"""
Tests for the L4 Load Balancer Forensics and Reconstruction task.

"""

import json
import os
import subprocess
import sys
from collections import Counter

for p in ("/app",):
    if p not in sys.path:
        sys.path.insert(0, p)

import pytest

# --- Conditional import for the balancer module ---
try:
    from balancer import LoadBalancer
    from framework import TABLE_SIZE

    HAS_BALANCER = True
except Exception:
    HAS_BALANCER = False
    TABLE_SIZE = 65537


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pkt(src_port=1234, fin=False):
    return {
        "src_ip": "192.168.1.10",
        "dst_ip": "10.0.0.100",
        "src_port": src_port,
        "dst_port": 80,
        "protocol": 6,
        "fin": fin,
    }


def _lb(backend_specs):
    """Create a LoadBalancer with service 'svc1' and given backends."""
    lb = LoadBalancer()
    lb.add_service("svc1")
    for bid, w in backend_specs:
        lb.add_backend("svc1", bid, weight=w)
    return lb


def _tshark_field(pcap, display_filter, field):
    """Run tshark to extract a single field from matching packets."""
    result = subprocess.run(
        ["tshark", "-r", pcap, "-Y", display_filter,
         "-T", "fields", "-e", field],
        capture_output=True, text=True,
    )
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    return lines


# ---------------------------------------------------------------------------
# Lookup table tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_BALANCER, reason="balancer.py not implemented")
class TestLookupTable:

    def test_table_size(self):
        lb = _lb([("10.0.0.1:80", 1), ("10.0.0.2:80", 1)])
        table = lb.get_lookup_table("svc1")
        assert len(table) == TABLE_SIZE

    def test_table_entries_are_valid(self):
        backends = [("10.0.0.1:80", 1), ("10.0.0.2:80", 1), ("10.0.0.3:80", 1)]
        lb = _lb(backends)
        table = lb.get_lookup_table("svc1")
        valid = {b for b, _ in backends}
        for i, entry in enumerate(table):
            assert entry in valid, f"table[{i}] = {entry!r} not in {valid}"

    def test_even_distribution(self):
        n = 5
        specs = [(f"10.0.0.{i}:80", 1) for i in range(1, n + 1)]
        lb = _lb(specs)
        table = lb.get_lookup_table("svc1")
        expected = TABLE_SIZE / n
        for bid, _ in specs:
            count = table.count(bid)
            assert abs(count - expected) / expected < 0.02, (
                f"{bid}: {count} entries, expected ~{expected:.0f}"
            )

    def test_weighted_distribution(self):
        lb = _lb([("10.0.0.1:80", 1), ("10.0.0.2:80", 3)])
        table = lb.get_lookup_table("svc1")
        c1 = table.count("10.0.0.1:80")
        c2 = table.count("10.0.0.2:80")
        ratio = c2 / c1
        assert abs(ratio - 3.0) < 0.2, f"Expected ~3:1 ratio, got {ratio:.2f}"

    def test_minimal_disruption(self):
        n = 5
        specs = [(f"10.0.0.{i}:80", 1) for i in range(1, n + 1)]
        lb = _lb(specs)
        before = lb.get_lookup_table("svc1")

        lb.remove_backend("svc1", "10.0.0.5:80")
        after = lb.get_lookup_table("svc1")

        changes = sum(1 for a, b in zip(before, after) if a != b)
        limit = TABLE_SIZE / n * 1.5
        assert changes <= limit, f"Disruption {changes} exceeds limit {limit:.0f}"

    def test_deterministic_order_independence(self):
        lb1 = LoadBalancer()
        lb1.add_service("s")
        lb1.add_backend("s", "10.0.0.1:80")
        lb1.add_backend("s", "10.0.0.2:80")
        lb1.add_backend("s", "10.0.0.3:80")

        lb2 = LoadBalancer()
        lb2.add_service("s")
        lb2.add_backend("s", "10.0.0.3:80")
        lb2.add_backend("s", "10.0.0.1:80")
        lb2.add_backend("s", "10.0.0.2:80")

        assert lb1.get_lookup_table("s") == lb2.get_lookup_table("s")

    def test_empty_pool_gives_empty_table(self):
        lb = LoadBalancer()
        lb.add_service("svc1")
        assert lb.get_lookup_table("svc1") == []

    def test_single_backend_fills_table(self):
        lb = _lb([("10.0.0.1:80", 1)])
        table = lb.get_lookup_table("svc1")
        assert len(table) == TABLE_SIZE
        assert all(e == "10.0.0.1:80" for e in table)


# ---------------------------------------------------------------------------
# Connection tracking tests
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not HAS_BALANCER, reason="balancer.py not implemented")
class TestConnectionTracking:

    def test_consistent_selection(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        pkt = _pkt(src_port=5000)
        r1 = lb.select_backend("svc1", pkt)
        r2 = lb.select_backend("svc1", pkt)
        assert r1 is not None
        assert r1 == r2

    def test_different_flows_distributed(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        results = set()
        for port in range(10000, 10200):
            results.add(lb.select_backend("svc1", _pkt(src_port=port)))
        assert len(results) > 1, "All 200 flows went to the same backend"

    def test_connection_preservation_on_unhealthy(self):
        backends = ["10.0.0.1:80", "10.0.0.2:80", "10.0.0.3:80"]
        lb = _lb([(b, 1) for b in backends])

        mapping = {}
        for port in range(2000, 2200):
            mapping[port] = lb.select_backend("svc1", _pkt(src_port=port))

        lb.set_backend_health("svc1", "10.0.0.2:80", False)

        for port, expected in mapping.items():
            got = lb.select_backend("svc1", _pkt(src_port=port))
            assert got == expected, f"port {port}: expected {expected}, got {got}"

    def test_new_connections_skip_unhealthy(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        lb.set_backend_health("svc1", "10.0.0.2:80", False)
        for port in range(3000, 3200):
            r = lb.select_backend("svc1", _pkt(src_port=port))
            assert r != "10.0.0.2:80", (
                f"New connection on port {port} went to unhealthy backend"
            )

    def test_fin_clears_connection(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        lb.select_backend("svc1", _pkt(src_port=4000))
        assert lb.get_connection_count("svc1") == 1

        lb.select_backend("svc1", _pkt(src_port=4000, fin=True))
        assert lb.get_connection_count("svc1") == 0

    def test_fin_still_returns_backend(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        r1 = lb.select_backend("svc1", _pkt(src_port=4100))
        r2 = lb.select_backend("svc1", _pkt(src_port=4100, fin=True))
        assert r2 is not None
        assert r2 == r1, "FIN should forward to the same backend"

    def test_connection_count(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        for port in range(5000, 5010):
            lb.select_backend("svc1", _pkt(src_port=port))
        assert lb.get_connection_count("svc1") == 10

        lb.select_backend("svc1", _pkt(src_port=5000, fin=True))
        assert lb.get_connection_count("svc1") == 9

    def test_removed_backend_remaps_connection(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])

        target_port = None
        for port in range(6000, 7000):
            if lb.select_backend("svc1", _pkt(src_port=port)) == "10.0.0.2:80":
                target_port = port
                break
        assert target_port is not None, "Could not find a flow to 10.0.0.2:80"

        lb.remove_backend("svc1", "10.0.0.2:80")
        got = lb.select_backend("svc1", _pkt(src_port=target_port))
        assert got in ("10.0.0.1:80", "10.0.0.3:80"), (
            f"Expected remap to surviving backend, got {got}"
        )

    def test_no_backends_returns_none(self):
        lb = LoadBalancer()
        lb.add_service("svc1")
        assert lb.select_backend("svc1", _pkt()) is None

    def test_all_unhealthy_returns_none(self):
        lb = _lb([("10.0.0.1:80", 1)])
        lb.set_backend_health("svc1", "10.0.0.1:80", False)
        assert lb.select_backend("svc1", _pkt(src_port=7000)) is None

    def test_fin_for_unknown_flow_no_tracking(self):
        lb = _lb([(f"10.0.0.{i}:80", 1) for i in range(1, 4)])
        r = lb.select_backend("svc1", _pkt(src_port=8000, fin=True))
        assert r is not None, "FIN should still select a backend"
        assert lb.get_connection_count("svc1") == 0

    def test_health_recovery_allows_new_connections(self):
        lb = _lb([("10.0.0.1:80", 1), ("10.0.0.2:80", 1)])
        lb.set_backend_health("svc1", "10.0.0.2:80", False)

        for port in range(9000, 9050):
            assert lb.select_backend("svc1", _pkt(src_port=port)) == "10.0.0.1:80"

        lb.set_backend_health("svc1", "10.0.0.2:80", True)

        results = set()
        for port in range(9100, 9300):
            results.add(lb.select_backend("svc1", _pkt(src_port=port)))
        assert len(results) == 2, "Recovered backend should receive new connections"


# ---------------------------------------------------------------------------
# PCAP analysis tests -- expected values computed at test time via tshark
# ---------------------------------------------------------------------------

class TestPcapAnalysis:

    STATS_PATH = "/app/analysis/traffic_stats.json"
    PCAP_PATH = "/app/captures/incident.pcap"

    @pytest.fixture(autouse=True)
    def _load(self):
        self.stats = None
        self.expected = None
        if os.path.exists(self.STATS_PATH):
            with open(self.STATS_PATH) as f:
                self.stats = json.load(f)
        if os.path.exists(self.PCAP_PATH):
            self.expected = self._compute_expected()

    def _compute_expected(self):
        """Independently compute expected values from the PCAP using tshark."""
        # Extract request source IPs (UDP packets with dst port 80)
        req_lines = _tshark_field(
            self.PCAP_PATH, "udp.dstport==80", "ip.src"
        )
        total_requests = len(req_lines)
        unique_clients = len(set(req_lines))

        # Extract response source IPs (UDP packets with src port 80)
        resp_lines = _tshark_field(
            self.PCAP_PATH, "udp.srcport==80", "ip.src"
        )
        total_responses = len(resp_lines)

        dist = dict(Counter(resp_lines))
        most_loaded = max(dist, key=dist.get) if dist else ""

        return {
            "total_requests": total_requests,
            "total_responses": total_responses,
            "backend_distribution": dist,
            "most_loaded_backend": most_loaded,
            "unique_client_ips": unique_clients,
        }

    def test_pcap_exists(self):
        assert os.path.exists(self.PCAP_PATH), (
            f"{self.PCAP_PATH} not found -- PCAP file is missing"
        )

    def test_analysis_file_exists(self):
        assert os.path.exists(self.STATS_PATH), (
            f"{self.STATS_PATH} not found -- run PCAP analysis"
        )

    def test_json_has_required_fields(self):
        assert self.stats is not None, "traffic_stats.json missing"
        for key in ("total_requests", "total_responses",
                    "backend_distribution", "most_loaded_backend",
                    "unique_client_ips"):
            assert key in self.stats, f"Missing key: {key}"

    def test_total_requests_accurate(self):
        assert self.stats is not None and self.expected is not None
        expected = self.expected["total_requests"]
        actual = self.stats["total_requests"]
        assert abs(actual - expected) <= max(expected * 0.05, 5), (
            f"total_requests: got {actual}, expected ~{expected}"
        )

    def test_total_responses_accurate(self):
        assert self.stats is not None and self.expected is not None
        expected = self.expected["total_responses"]
        actual = self.stats["total_responses"]
        assert abs(actual - expected) <= max(expected * 0.05, 5), (
            f"total_responses: got {actual}, expected ~{expected}"
        )

    def test_most_loaded_backend_correct(self):
        assert self.stats is not None and self.expected is not None
        assert self.stats["most_loaded_backend"] == self.expected["most_loaded_backend"]

    def test_unique_client_ips_accurate(self):
        assert self.stats is not None and self.expected is not None
        expected = self.expected["unique_client_ips"]
        actual = self.stats["unique_client_ips"]
        assert abs(actual - expected) <= max(expected * 0.05, 5), (
            f"unique_client_ips: got {actual}, expected ~{expected}"
        )

    def test_backend_distribution_complete(self):
        assert self.stats is not None and self.expected is not None
        expected_keys = set(self.expected["backend_distribution"].keys())
        actual_keys = set(self.stats["backend_distribution"].keys())
        assert actual_keys == expected_keys, (
            f"Expected backends {expected_keys}, got {actual_keys}"
        )


# ---------------------------------------------------------------------------
# Nginx configuration tests
# ---------------------------------------------------------------------------

class TestNginxConfig:

    CONFIG_PATH = "/app/nginx/nginx.conf"

    def test_config_file_exists(self):
        assert os.path.exists(self.CONFIG_PATH)

    def test_config_syntax_valid(self):
        result = subprocess.run(
            ["nginx", "-t", "-c", self.CONFIG_PATH],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, (
            f"nginx -t failed:\n{result.stderr}"
        )

    def test_uses_consistent_hashing(self):
        with open(self.CONFIG_PATH) as f:
            cfg = f.read()
        assert "hash" in cfg.lower(), (
            "Config must use a hash directive for consistent hashing"
        )
        assert "consistent" in cfg.lower(), (
            "Config must enable consistent hashing mode"
        )

    def test_has_all_backend_servers(self):
        with open(self.CONFIG_PATH) as f:
            cfg = f.read()
        for port in (8001, 8002, 8003, 8004):
            assert f"127.0.0.1:{port}" in cfg, (
                f"Missing backend server 127.0.0.1:{port}"
            )
