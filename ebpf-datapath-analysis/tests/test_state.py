
import json
import os
import pytest


ANALYSIS_FILE = "/app/analysis.json"


@pytest.fixture
def analysis():
    assert os.path.exists(ANALYSIS_FILE), f"{ANALYSIS_FILE} does not exist"
    with open(ANALYSIS_FILE) as f:
        data = json.load(f)
    return data


def get_graph_targets(graph, *possible_keys):
    """Get all targets for a node, trying multiple possible key names."""
    all_targets = set()
    for key in possible_keys:
        if key in graph:
            val = graph[key]
            if isinstance(val, list):
                all_targets.update(val)
    return all_targets


# ---- BPF Maps ----

class TestBPFMaps:
    def test_map_count(self, analysis):
        """bpf_lxc.c defines exactly 3 BPF maps with __section_maps_btf"""
        maps = analysis["bpf_maps"]
        assert len(maps) == 3, f"Expected 3 maps, got {len(maps)}: {[m['name'] for m in maps]}"

    def test_map_names(self, analysis):
        """All three expected map names must be present"""
        names = {m["name"] for m in analysis["bpf_maps"]}
        expected = {
            "cilium_nodeport_nat_buffer",
            "cilium_tail_call_buffer6",
            "cilium_tail_call_buffer4",
        }
        assert names == expected, f"Expected {expected}, got {names}"

    def test_all_maps_percpu_array(self, analysis):
        """All maps in bpf_lxc.c are BPF_MAP_TYPE_PERCPU_ARRAY"""
        for m in analysis["bpf_maps"]:
            assert m["type"] == "BPF_MAP_TYPE_PERCPU_ARRAY", (
                f"Map {m['name']} has type {m['type']}, expected BPF_MAP_TYPE_PERCPU_ARRAY"
            )

    def test_all_maps_single_entry(self, analysis):
        """All maps have max_entries == 1"""
        for m in analysis["bpf_maps"]:
            assert m["max_entries"] == 1, (
                f"Map {m['name']} has max_entries={m['max_entries']}, expected 1"
            )


# ---- Entry Points ----

class TestEntryPoints:
    def test_entry_point_count(self, analysis):
        """bpf_lxc.c has exactly 4 __section_entry functions"""
        assert len(analysis["entry_points"]) == 4, (
            f"Expected 4 entry points, got {len(analysis['entry_points'])}"
        )

    def test_entry_point_names(self, analysis):
        """All four expected entry point names must be present"""
        names = {ep["function_name"] for ep in analysis["entry_points"]}
        expected = {
            "cil_from_container",
            "cil_lxc_policy",
            "cil_lxc_policy_egress",
            "cil_to_container",
        }
        assert names == expected, f"Expected {expected}, got {names}"


# ---- Tail Call Programs ----

class TestTailCallPrograms:
    def test_total_count(self, analysis):
        """bpf_lxc.c has exactly 17 tail call programs (11 direct + 6 macro)"""
        assert len(analysis["tail_call_programs"]) == 17, (
            f"Expected 17 tail call programs, got {len(analysis['tail_call_programs'])}"
        )

    def test_declare_tail_programs(self, analysis):
        """All 11 __declare_tail program IDs must be present"""
        ids = {p["id"] for p in analysis["tail_call_programs"] if p["source"] == "declare_tail"}
        expected = {
            "CILIUM_CALL_IPV6_FROM_LXC_CONT",
            "CILIUM_CALL_IPV6_FROM_LXC",
            "CILIUM_CALL_IPV4_FROM_LXC_CONT",
            "CILIUM_CALL_IPV4_FROM_LXC",
            "CILIUM_CALL_ARP",
            "CILIUM_CALL_IPV6_TO_LXC_POLICY_ONLY",
            "CILIUM_CALL_IPV6_TO_ENDPOINT",
            "CILIUM_CALL_IPV4_TO_LXC_POLICY_ONLY",
            "CILIUM_CALL_IPV4_TO_ENDPOINT",
            "CILIUM_CALL_IPV4_POLICY_DENIED",
            "CILIUM_CALL_IPV6_POLICY_DENIED",
        }
        assert ids == expected, f"Missing: {expected - ids}, Extra: {ids - expected}"

    def test_macro_programs(self, analysis):
        """All 6 TAIL_CT_LOOKUP macro-generated program IDs must be present"""
        ids = {p["id"] for p in analysis["tail_call_programs"] if p["source"] == "macro"}
        expected = {
            "CILIUM_CALL_IPV6_CT_EGRESS",
            "CILIUM_CALL_IPV6_CT_INGRESS_POLICY_ONLY",
            "CILIUM_CALL_IPV6_CT_INGRESS",
            "CILIUM_CALL_IPV4_CT_EGRESS",
            "CILIUM_CALL_IPV4_CT_INGRESS_POLICY_ONLY",
            "CILIUM_CALL_IPV4_CT_INGRESS",
        }
        assert ids == expected, f"Missing: {expected - ids}, Extra: {ids - expected}"

    def test_function_name_mapping(self, analysis):
        """Specific CILIUM_CALL IDs must map to the correct function names"""
        id_to_func = {p["id"]: p["function_name"] for p in analysis["tail_call_programs"]}
        assert id_to_func["CILIUM_CALL_ARP"] == "tail_handle_arp"
        assert id_to_func["CILIUM_CALL_IPV4_FROM_LXC"] == "tail_handle_ipv4"
        assert id_to_func["CILIUM_CALL_IPV6_FROM_LXC"] == "tail_handle_ipv6"
        assert id_to_func["CILIUM_CALL_IPV6_CT_EGRESS"] == "tail_ipv6_ct_egress"
        assert id_to_func["CILIUM_CALL_IPV4_CT_INGRESS"] == "tail_ipv4_ct_ingress"
        assert id_to_func["CILIUM_CALL_IPV4_TO_ENDPOINT"] == "tail_ipv4_to_endpoint"


# ---- Tail Call Graph ----

class TestTailCallGraph:
    def test_cil_from_container_targets(self, analysis):
        """cil_from_container must tail-call to IPv6, IPv4, and ARP handlers"""
        graph = analysis["tail_call_graph"]
        targets = get_graph_targets(graph, "cil_from_container")
        assert "CILIUM_CALL_IPV6_FROM_LXC" in targets, f"Missing IPV6_FROM_LXC in {targets}"
        assert "CILIUM_CALL_IPV4_FROM_LXC" in targets, f"Missing IPV4_FROM_LXC in {targets}"
        assert "CILIUM_CALL_ARP" in targets, f"Missing ARP in {targets}"

    def test_cil_to_container_targets(self, analysis):
        """cil_to_container must tail-call to CT ingress handlers"""
        graph = analysis["tail_call_graph"]
        targets = get_graph_targets(graph, "cil_to_container")
        assert "CILIUM_CALL_IPV6_CT_INGRESS" in targets, f"Missing in {targets}"
        assert "CILIUM_CALL_IPV4_CT_INGRESS" in targets, f"Missing in {targets}"

    def test_cil_lxc_policy_targets(self, analysis):
        """cil_lxc_policy must tail-call to CT ingress policy-only handlers"""
        graph = analysis["tail_call_graph"]
        targets = get_graph_targets(graph, "cil_lxc_policy")
        assert "CILIUM_CALL_IPV6_CT_INGRESS_POLICY_ONLY" in targets, f"Missing in {targets}"
        assert "CILIUM_CALL_IPV4_CT_INGRESS_POLICY_ONLY" in targets, f"Missing in {targets}"

    def test_ct_egress_macro_edges(self, analysis):
        """TAIL_CT_LOOKUP egress macros must chain to FROM_LXC_CONT programs"""
        graph = analysis["tail_call_graph"]
        v4_targets = get_graph_targets(
            graph, "CILIUM_CALL_IPV4_CT_EGRESS", "tail_ipv4_ct_egress"
        )
        v6_targets = get_graph_targets(
            graph, "CILIUM_CALL_IPV6_CT_EGRESS", "tail_ipv6_ct_egress"
        )
        assert "CILIUM_CALL_IPV4_FROM_LXC_CONT" in v4_targets, f"Missing in {v4_targets}"
        assert "CILIUM_CALL_IPV6_FROM_LXC_CONT" in v6_targets, f"Missing in {v6_targets}"

    def test_ct_ingress_macro_edges(self, analysis):
        """TAIL_CT_LOOKUP ingress macros must chain to TO_ENDPOINT programs"""
        graph = analysis["tail_call_graph"]
        v4_targets = get_graph_targets(
            graph, "CILIUM_CALL_IPV4_CT_INGRESS", "tail_ipv4_ct_ingress"
        )
        v6_targets = get_graph_targets(
            graph, "CILIUM_CALL_IPV6_CT_INGRESS", "tail_ipv6_ct_ingress"
        )
        assert "CILIUM_CALL_IPV4_TO_ENDPOINT" in v4_targets, f"Missing in {v4_targets}"
        assert "CILIUM_CALL_IPV6_TO_ENDPOINT" in v6_targets, f"Missing in {v6_targets}"

    def test_inline_function_resolution(self, analysis):
        """Tail calls through inline helpers must be resolved transitively.

        CILIUM_CALL_IPV4_FROM_LXC -> tail_handle_ipv4 -> __tail_handle_ipv4
        -> __per_packet_lb_svc_xlate_4 -> tail_call_internal(CILIUM_CALL_IPV4_CT_EGRESS)

        This edge can ONLY be found by following the inline function call chain.
        """
        graph = analysis["tail_call_graph"]
        targets = get_graph_targets(
            graph, "CILIUM_CALL_IPV4_FROM_LXC", "tail_handle_ipv4"
        )
        assert "CILIUM_CALL_IPV4_CT_EGRESS" in targets, (
            f"CILIUM_CALL_IPV4_CT_EGRESS not found in targets of CILIUM_CALL_IPV4_FROM_LXC. "
            f"This requires resolving tail calls through __tail_handle_ipv4 -> "
            f"__per_packet_lb_svc_xlate_4. Got: {targets}"
        )
