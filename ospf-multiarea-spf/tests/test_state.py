
import json
import os
import pytest

RESULTS_DIR = "/app/results"


def load_json(filename):
    with open(os.path.join(RESULTS_DIR, filename)) as f:
        return json.load(f)


def find_route(table, destination):
    for entry in table:
        if entry["destination"] == destination:
            return entry
    return None


# ===========================================================================
# R7 Routing Table Tests
# ===========================================================================

class TestR7IntraArea:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.table = load_json("routing_table_R7.json")

    def test_own_loopback(self):
        route = find_route(self.table, "10.7.7.7/32")
        assert route is not None, "R7 own loopback missing"
        assert route["route_type"] == "intra-area"
        assert route["cost"] == 0

    def test_r8_loopback(self):
        route = find_route(self.table, "10.8.8.8/32")
        assert route is not None, "R8 loopback missing from R7 table"
        assert route["route_type"] == "intra-area"
        assert route["cost"] == 4
        assert route["next_hop_router"] == "R8"


class TestR7InterArea:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.table = load_json("routing_table_R7.json")

    def test_r1_loopback(self):
        route = find_route(self.table, "10.1.1.1/32")
        assert route is not None, "R1 loopback missing from R7 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 16
        assert route["next_hop_router"] == "R2"

    def test_r2_loopback(self):
        route = find_route(self.table, "10.2.2.2/32")
        assert route is not None, "R2 loopback missing from R7 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 6
        assert route["next_hop_router"] == "R2"

    def test_r3_loopback(self):
        route = find_route(self.table, "10.3.3.3/32")
        assert route is not None, "R3 loopback missing from R7 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 7
        assert route["next_hop_router"] == "R8"

    def test_r4_loopback(self):
        route = find_route(self.table, "10.4.4.4/32")
        assert route is not None, "R4 loopback missing from R7 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 15
        assert route["next_hop_router"] == "R8"

    def test_r5_loopback(self):
        """R7 to R5 requires cross-area routing: Area 2 -> ABR -> Area 0 -> ABR -> Area 1"""
        route = find_route(self.table, "10.5.5.5/32")
        assert route is not None, "R5 loopback missing from R7 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 19
        assert route["next_hop_router"] == "R8"

    def test_r6_loopback(self):
        route = find_route(self.table, "10.6.6.6/32")
        assert route is not None, "R6 loopback missing from R7 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 14
        assert route["next_hop_router"] == "R8"


class TestR7External:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.table = load_json("routing_table_R7.json")

    def test_e2_172_16(self):
        route = find_route(self.table, "172.16.0.0/16")
        assert route is not None, "172.16.0.0/16 missing from R7 table"
        assert route["route_type"] == "external-type2"
        assert route["cost"] == 20
        assert route["forwarding_cost"] == 15
        assert route["next_hop_router"] == "R8"

    def test_e1_192_168_1(self):
        route = find_route(self.table, "192.168.1.0/24")
        assert route is not None, "192.168.1.0/24 missing from R7 table"
        assert route["route_type"] == "external-type1"
        assert route["cost"] == 25
        assert route["next_hop_router"] == "R8"

    def test_e2_with_forwarding_address(self):
        """192.168.2.0/24 has forwarding address 10.6.6.6 - must resolve via FA not ASBR"""
        route = find_route(self.table, "192.168.2.0/24")
        assert route is not None, "192.168.2.0/24 missing from R7 table"
        assert route["route_type"] == "external-type2"
        assert route["cost"] == 20
        assert route["forwarding_cost"] == 14
        assert route["next_hop_router"] == "R8"


# ===========================================================================
# R5 Routing Table Tests
# ===========================================================================

class TestR5IntraArea:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.table = load_json("routing_table_R5.json")

    def test_own_loopback(self):
        route = find_route(self.table, "10.5.5.5/32")
        assert route is not None, "R5 own loopback missing"
        assert route["route_type"] == "intra-area"
        assert route["cost"] == 0

    def test_r6_loopback(self):
        route = find_route(self.table, "10.6.6.6/32")
        assert route is not None, "R6 loopback missing from R5 table"
        assert route["route_type"] == "intra-area"
        assert route["cost"] == 5
        assert route["next_hop_router"] == "R6"


class TestR5InterArea:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.table = load_json("routing_table_R5.json")

    def test_r1_loopback(self):
        route = find_route(self.table, "10.1.1.1/32")
        assert route is not None, "R1 loopback missing from R5 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 10
        assert route["next_hop_router"] == "R1"

    def test_r2_loopback(self):
        """R5 to R2: via ABR R3 (cost 12+5=17) beats via ABR R1 (cost 10+10=20)"""
        route = find_route(self.table, "10.2.2.2/32")
        assert route is not None, "R2 loopback missing from R5 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 17
        assert route["next_hop_router"] == "R6"

    def test_r3_loopback(self):
        route = find_route(self.table, "10.3.3.3/32")
        assert route is not None, "R3 loopback missing from R5 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 12
        assert route["next_hop_router"] == "R6"

    def test_r4_loopback(self):
        route = find_route(self.table, "10.4.4.4/32")
        assert route is not None, "R4 loopback missing from R5 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 20
        assert route["next_hop_router"] == "R6"

    def test_r7_loopback(self):
        """R5 to R7 requires cross-area: Area 1 -> ABR R3 -> Area 2"""
        route = find_route(self.table, "10.7.7.7/32")
        assert route is not None, "R7 loopback missing from R5 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 19
        assert route["next_hop_router"] == "R6"

    def test_r8_loopback(self):
        route = find_route(self.table, "10.8.8.8/32")
        assert route is not None, "R8 loopback missing from R5 table"
        assert route["route_type"] == "inter-area"
        assert route["cost"] == 15
        assert route["next_hop_router"] == "R6"


class TestR5External:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.table = load_json("routing_table_R5.json")

    def test_e2_172_16(self):
        route = find_route(self.table, "172.16.0.0/16")
        assert route is not None, "172.16.0.0/16 missing from R5 table"
        assert route["route_type"] == "external-type2"
        assert route["cost"] == 20
        assert route["forwarding_cost"] == 20
        assert route["next_hop_router"] == "R6"

    def test_e1_192_168_1(self):
        route = find_route(self.table, "192.168.1.0/24")
        assert route is not None, "192.168.1.0/24 missing from R5 table"
        assert route["route_type"] == "external-type1"
        assert route["cost"] == 30
        assert route["next_hop_router"] == "R6"

    def test_e2_with_forwarding_address(self):
        """FA 10.6.6.6 is R6, direct neighbor of R5 at cost 5"""
        route = find_route(self.table, "192.168.2.0/24")
        assert route is not None, "192.168.2.0/24 missing from R5 table"
        assert route["route_type"] == "external-type2"
        assert route["cost"] == 20
        assert route["forwarding_cost"] == 5
        assert route["next_hop_router"] == "R6"


# ===========================================================================
# Analysis Tests (Routing)
# ===========================================================================

class TestRoutingAnalysis:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.analysis = load_json("analysis.json")

    def test_r7_cost_to_r5(self):
        assert self.analysis["r7_cost_to_10_5_5_5"] == 19

    def test_r7_next_hop_to_r5(self):
        assert self.analysis["r7_next_hop_to_10_5_5_5"] == "R8"

    def test_r7_forwarding_cost_172_16(self):
        assert self.analysis["r7_forwarding_cost_172_16"] == 15

    def test_r7_failover_cost(self):
        """When R8-R3 fails, R3 leaves Area 2, R7 uses only ABR R2: 6+17=23"""
        assert self.analysis["r7_failover_cost_to_10_5_5_5"] == 23

    def test_r7_failover_next_hop(self):
        """After R8-R3 failure, R7 reaches R4 only via R2"""
        assert self.analysis["r7_failover_next_hop_to_10_4_4_4"] == "R2"

    def test_forwarding_address_routing(self):
        assert self.analysis["r7_192_168_2_route_via"] == "forwarding_address"

    def test_e2_tiebreaker(self):
        """E2 tiebreak: 192.168.2.0/24 fwd_cost=14 < 172.16.0.0/16 fwd_cost=15"""
        assert self.analysis["e2_tiebreaker_preferred"] == "192.168.2.0/24"


# ===========================================================================
# Analysis Tests (Packet Capture)
# ===========================================================================

class TestPcapAnalysis:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.analysis = load_json("analysis.json")

    def test_hello_count(self):
        """Total OSPF Hello packets in the capture"""
        assert self.analysis["pcap_hello_count"] == 6

    def test_area0_dr(self):
        """DR router-id from Area 0 Hello packets"""
        assert self.analysis["pcap_area0_dr"] == "2.2.2.2"

    def test_r8_dead_interval(self):
        """R8 uses non-standard dead interval of 120 seconds"""
        assert self.analysis["pcap_r8_dead_interval"] == 120

    def test_r3_area0_lsa_link_count(self):
        """R3's Area 0 Router LSA has 4 links: 3 P2P + 1 stub loopback"""
        assert self.analysis["pcap_r3_area0_lsa_link_count"] == 4
