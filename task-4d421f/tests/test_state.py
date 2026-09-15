
import pytest
import sys
import json
import os

sys.path.insert(0, '/app')
import ospf_analyzer


def _make_analyzer():
    return ospf_analyzer.OSPFAnalyzer("/data/topology.json")


# ================================================================
# Section 1 — tshark pcap extraction
# ================================================================

class TestTsharkExtraction:
    """Verify that extract_packets correctly invokes tshark and parses output."""

    def test_extract_p2p_packet_count(self):
        a = _make_analyzer()
        pkts = a.extract_packets("/data/captures/p2p_adjacency.pcap")
        assert len(pkts) == 5

    def test_extract_p2p_fields(self):
        a = _make_analyzer()
        pkts = a.extract_packets("/data/captures/p2p_adjacency.pcap")
        # First packet: R3 Hello, no neighbors
        assert pkts[0]["src_router"] == "3.3.3.3"
        assert pkts[0]["type"] == "Hello"
        assert pkts[0]["hello_interval"] == 10
        assert pkts[0]["dead_interval"] == 40
        assert pkts[0]["neighbors"] == []
        # Second packet: R4 Hello, no neighbors
        assert pkts[1]["src_router"] == "4.4.4.4"
        assert pkts[1]["neighbors"] == []
        # Fourth packet: R4 Hello, lists R3
        assert pkts[3]["src_router"] == "4.4.4.4"
        assert "3.3.3.3" in pkts[3]["neighbors"]

    def test_extract_broadcast_dr_fields(self):
        a = _make_analyzer()
        pkts = a.extract_packets("/data/captures/broadcast_network.pcap")
        assert len(pkts) == 8
        # Second-round R1 Hello should show DR=1.1.1.1 BDR=2.2.2.2
        r1_round2 = pkts[4]
        assert r1_round2["src_router"] == "1.1.1.1"
        assert r1_round2["dr"] == "1.1.1.1"
        assert r1_round2["bdr"] == "2.2.2.2"
        assert set(r1_round2["neighbors"]) == {"2.2.2.2", "3.3.3.3", "5.5.5.5"}


# ================================================================
# Section 2 — pcap-based FSM analysis
# ================================================================

class TestPcapAnalysis:
    """Verify analyze_capture infers correct FSM events from pcaps."""

    def test_p2p_analysis(self):
        a = _make_analyzer()
        report = a.analyze_capture("/data/captures/p2p_adjacency.pcap", "3.3.3.3")
        # R3 perspective: receives R4 Hellos at T+1 (no list) and T+11 (lists R3)
        assert report["final_states"]["4.4.4.4"] == "ExStart"
        transitions = report["transitions"]
        # Must see HelloReceived Down->Init and 2-WayReceived Init->ExStart
        hello_t = [t for t in transitions if t["event"] == "HelloReceived"
                   and t["from_state"] == "Down"]
        assert len(hello_t) >= 1
        assert hello_t[0]["to_state"] == "Init"
        two_way = [t for t in transitions if t["event"] == "2-WayReceived"]
        assert len(two_way) >= 1
        assert two_way[0]["from_state"] == "Init"
        assert two_way[0]["to_state"] == "ExStart"

    def test_broadcast_adjacency_decisions(self):
        a = _make_analyzer()
        report = a.analyze_capture("/data/captures/broadcast_network.pcap", "3.3.3.3")
        fs = report["final_states"]
        # R3 (DROther) should form adjacency with DR (R1) and BDR (R2) -> ExStart
        assert fs["1.1.1.1"] == "ExStart"
        assert fs["2.2.2.2"] == "ExStart"
        # R3 (DROther) should NOT form adjacency with R5 (DROther) -> 2-Way
        assert fs["5.5.5.5"] == "2-Way"

    def test_timing_violation_detection(self):
        a = _make_analyzer()
        report = a.analyze_capture("/data/captures/timing_violation.pcap", "3.3.3.3")
        # Must detect dead_interval_exceeded
        viols = [v for v in report["violations"]
                 if v["type"] == "dead_interval_exceeded"]
        assert len(viols) == 1
        # Must have InactivityTimer transition
        inact = [t for t in report["transitions"]
                 if t["event"] == "InactivityTimer"]
        assert len(inact) == 1
        assert inact[0]["from_state"] == "ExStart"
        assert inact[0]["to_state"] == "Down"

    def test_param_mismatch_detection(self):
        a = _make_analyzer()
        report = a.analyze_capture("/data/captures/param_mismatch.pcap", "3.3.3.3")
        viols = [v for v in report["violations"]
                 if v["type"] == "hello_interval_mismatch"]
        assert len(viols) >= 1


# ================================================================
# Section 3 — JSON trace FSM engine (kept from prior task)
# ================================================================

class TestTraceFSM:
    """Verify process_trace handles JSON event traces correctly."""

    def test_trace_p2p_full(self):
        a = _make_analyzer()
        result = a.process_trace("/data/traces/trace_01_p2p_full.json")
        assert result["trace_id"] == "trace_01_p2p_full"
        assert result["final_states"]["R3->R4"] == "Full"
        assert result["final_states"]["R4->R3"] == "Full"
        t = result["transitions"]
        assert len(t) == 8
        assert t[0]["from_state"] == "Down"
        assert t[0]["to_state"] == "Init"
        assert t[6]["from_state"] == "Exchange"
        assert t[6]["to_state"] == "Full"

    def test_trace_adjok_promotion(self):
        a = _make_analyzer()
        result = a.process_trace("/data/traces/trace_05_adjok_promotion.json")
        assert result["final_states"]["R3->R5"] == "Full"
        t = result["transitions"]
        assert len(t) == 5
        assert t[1]["from_state"] == "Init"
        assert t[1]["to_state"] == "2-Way"
        assert t[2]["from_state"] == "2-Way"
        assert t[2]["to_state"] == "ExStart"
        assert t[2]["event"] == "AdjOK?"

    def test_trace_violations(self):
        a = _make_analyzer()
        violations = a.validate_transitions(
            "/data/traces/trace_08_violations.json")
        assert len(violations) == 3
        indices = {v["index"] for v in violations}
        assert indices == {1, 2, 3}
        for v in violations:
            assert v["type"] == "invalid_transition"


# ================================================================
# Section 4 — scapy pcap generation
# ================================================================

class TestScapyGeneration:
    """Verify generate_test_pcap creates valid OSPF pcaps using scapy."""

    def test_roundtrip(self):
        a = _make_analyzer()
        out = "/tmp/test_roundtrip.pcap"
        a.generate_test_pcap(
            packets_spec=[
                {"router_id": "3.3.3.3", "src_ip": "10.0.2.1",
                 "neighbors": [], "timestamp": 0},
                {"router_id": "4.4.4.4", "src_ip": "10.0.2.2",
                 "neighbors": ["3.3.3.3"], "timestamp": 1},
            ],
            output_file=out
        )
        assert os.path.exists(out)
        pkts = a.extract_packets(out)
        assert len(pkts) == 2
        assert pkts[0]["src_router"] == "3.3.3.3"
        assert pkts[0]["type"] == "Hello"
        assert pkts[1]["src_router"] == "4.4.4.4"
        assert "3.3.3.3" in pkts[1]["neighbors"]

    def test_generated_broadcast(self):
        a = _make_analyzer()
        out = "/tmp/test_broadcast_gen.pcap"
        a.generate_test_pcap(
            packets_spec=[
                {"router_id": "1.1.1.1", "src_ip": "10.0.1.1",
                 "priority": 100, "dr": "1.1.1.1", "bdr": "2.2.2.2",
                 "neighbors": ["2.2.2.2", "3.3.3.3"], "timestamp": 0},
                {"router_id": "3.3.3.3", "src_ip": "10.0.1.3",
                 "priority": 10, "dr": "1.1.1.1", "bdr": "2.2.2.2",
                 "neighbors": ["1.1.1.1", "2.2.2.2"], "timestamp": 1},
            ],
            output_file=out
        )
        pkts = a.extract_packets(out)
        assert len(pkts) == 2
        assert pkts[0]["dr"] == "1.1.1.1"
        assert pkts[0]["priority"] == 100
        assert set(pkts[0]["neighbors"]) == {"2.2.2.2", "3.3.3.3"}
