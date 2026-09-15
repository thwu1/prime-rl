
import json
import pytest
from collections import defaultdict


@pytest.fixture(scope="module")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def spec():
    with open("/app/system_spec.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def flow_edge_set(results):
    return {tuple(e) for e in results["flow_edges"]}


@pytest.fixture(scope="module")
def violation_set(results):
    return {tuple(v) for v in results["violations"]}


@pytest.fixture(scope="module")
def pd_labels(spec):
    return {
        pd["name"]: (pd["security_level"], set(pd["compartments"]))
        for pd in spec["protection_domains"]
    }


def dominates(dst_label, src_label):
    """dst dominates src iff dst.level >= src.level AND dst.compartments >= src.compartments"""
    return dst_label[0] >= src_label[0] and dst_label[1] >= src_label[1]


# --- Inert Capability Tests ---

class TestInertCapabilities:
    def test_inert_count(self, results):
        assert len(results["inert_capability_ids"]) == 2

    def test_inert_ids(self, results):
        assert results["inert_capability_ids"] == ["cap_083", "cap_084"]


# --- Flow Edge Tests ---

class TestFlowEdges:
    def test_flow_edge_count(self, results):
        assert len(results["flow_edges"]) == 66

    def test_no_self_loops(self, results):
        for e in results["flow_edges"]:
            assert e[0] != e[1], f"Self-loop: {e}"

    def test_shm_nav_data_flow(self, flow_edge_set):
        assert ("nav_svc", "att_ctrl", "shm_nav_data") in flow_edge_set

    def test_ep_cmd_channel_flow(self, flow_edge_set):
        assert ("cmd_handler", "exec_svc", "ep_cmd_channel") in flow_edge_set

    def test_ntf_heartbeat_flow(self, flow_edge_set):
        assert ("time_svc", "exec_svc", "ntf_heartbeat") in flow_edge_set
        assert ("time_svc", "sw_bus", "ntf_heartbeat") in flow_edge_set

    def test_bidirectional_net_buf(self, flow_edge_set):
        assert ("net_stack", "eth_drv", "shm_net_buf") in flow_edge_set
        assert ("eth_drv", "net_stack", "shm_net_buf") in flow_edge_set

    def test_bidirectional_uart_buf(self, flow_edge_set):
        assert ("uart_drv", "downlink", "shm_uart_buf") in flow_edge_set
        assert ("downlink", "uart_drv", "shm_uart_buf") in flow_edge_set

    def test_crypto_out_flow(self, flow_edge_set):
        assert ("crypto_svc", "cmd_handler", "shm_crypto_out") in flow_edge_set
        assert ("crypto_svc", "key_mgmt", "shm_crypto_out") in flow_edge_set

    def test_absent_inert_ep_flow(self, flow_edge_set):
        """cap_084 (sw_bus Recv on ep_cmd_channel) is inert; no flow should exist."""
        assert ("cmd_handler", "sw_bus", "ep_cmd_channel") not in flow_edge_set

    def test_absent_inert_shm_flow(self, flow_edge_set):
        """cap_083 (downlink R on shm_health_buf) is inert; no read flow to downlink."""
        for e in flow_edge_set:
            if e[2] == "shm_health_buf":
                assert e[1] != "downlink", f"Inert cap should not create flow: {e}"

    def test_payload_io_flow(self, flow_edge_set):
        assert ("payload_ctrl", "legacy_vm", "shm_payload_io") in flow_edge_set
        assert ("payload_ctrl", "health_mon", "shm_payload_io") in flow_edge_set


# --- Violation Tests ---

class TestViolations:
    def test_violation_count(self, results):
        assert len(results["violations"]) == 43

    def test_level_and_compartment_violation(self, violation_set):
        """cmd_handler(L3,{COMMS,CRYPTO}) -> exec_svc(L2,{FLIGHT,PAYLOAD}): both level and compartment fail."""
        assert ("cmd_handler", "exec_svc", "ep_cmd_channel") in violation_set
        assert ("cmd_handler", "exec_svc", "shm_cmd_bus") in violation_set

    def test_compartment_breach_violation(self, violation_set):
        """exec_svc(L2,{FLIGHT,PAYLOAD}) -> crypto_svc(L3,{CRYPTO}): level OK but compartments fail."""
        assert ("exec_svc", "crypto_svc", "ep_crypto_req") in violation_set

    def test_compartment_breach_same_level(self, violation_set):
        """exec_svc(L2,{FLIGHT,PAYLOAD}) -> att_ctrl(L2,{FLIGHT}): same level, compartment mismatch."""
        assert ("exec_svc", "att_ctrl", "ep_exec_ctrl") in violation_set
        assert ("exec_svc", "att_ctrl", "shm_att_cmd") in violation_set

    def test_compartment_breach_level_zero(self, violation_set):
        """downlink(L0,{COMMS}) -> uart_drv(L0,{}): same level, compartment breach."""
        assert ("downlink", "uart_drv", "shm_uart_buf") in violation_set

    def test_write_down_violation(self, violation_set):
        """file_sys(L1,{}) -> legacy_vm(L0,{}): level drops, compartments OK (both empty)."""
        assert ("file_sys", "legacy_vm", "shm_file_cache") in violation_set

    def test_legal_flow_not_in_violations(self, violation_set):
        """nav_svc(L2,{FLIGHT}) -> att_ctrl(L2,{FLIGHT}): att_ctrl dominates, not a violation."""
        assert ("nav_svc", "att_ctrl", "ep_nav_update") not in violation_set
        assert ("nav_svc", "att_ctrl", "shm_nav_data") not in violation_set

    def test_upward_flow_not_violation(self, violation_set):
        """legacy_vm(L0,{}) -> health_mon(L1,{FLIGHT,PAYLOAD}): health_mon dominates."""
        assert ("legacy_vm", "health_mon", "shm_payload_io") not in violation_set

    def test_all_violations_are_non_dominated(self, results, pd_labels):
        """Every reported violation must have dst NOT dominating src."""
        for v in results["violations"]:
            src, dst = v[0], v[1]
            assert not dominates(pd_labels[dst], pd_labels[src]), (
                f"{v}: dst {dst} dominates src {src}, should not be a violation"
            )

    def test_violation_completeness(self, results, pd_labels):
        """Every flow edge where dst doesn't dominate src must be in violations."""
        violation_set = {tuple(v) for v in results["violations"]}
        for e in results["flow_edges"]:
            src, dst = e[0], e[1]
            if not dominates(pd_labels[dst], pd_labels[src]):
                assert tuple(e) in violation_set, (
                    f"Flow {e} is non-dominated but missing from violations"
                )

    def test_sw_bus_violations(self, violation_set):
        """sw_bus(L1,{COMMS}) involved in compartment breaches."""
        assert ("sw_bus", "exec_svc", "shm_cmd_bus") in violation_set
        assert ("sw_bus", "time_svc", "ep_sw_bus_relay") in violation_set

    def test_event_svc_violations(self, violation_set):
        assert ("event_svc", "exec_svc", "ntf_alarm") in violation_set
        assert ("event_svc", "file_sys", "shm_log_buf") in violation_set

    def test_telemetry_violations(self, violation_set):
        assert ("telemetry", "downlink", "ep_tlm_channel") in violation_set
        assert ("telemetry", "downlink", "shm_tlm_buf") in violation_set
        assert ("telemetry", "net_stack", "shm_tlm_buf") in violation_set


# --- TCB Tests ---

class TestTCB:
    def test_tcb_all_pds(self, results, spec):
        pd_names = {pd["name"] for pd in spec["protection_domains"]}
        assert set(results["tcb"].keys()) == pd_names

    def test_tcb_nav_svc_empty(self, results):
        """nav_svc has no incoming flows; TCB is empty."""
        assert results["tcb"]["nav_svc"] == []

    def test_tcb_downlink_count(self, results):
        assert len(results["tcb"]["downlink"]) == 17

    def test_tcb_uart_drv_count(self, results):
        assert len(results["tcb"]["uart_drv"]) == 17

    def test_tcb_eth_drv_count(self, results):
        assert len(results["tcb"]["eth_drv"]) == 15

    def test_tcb_att_ctrl(self, results):
        expected = sorted([
            "cmd_handler", "crypto_svc", "event_svc", "exec_svc", "file_sys",
            "health_mon", "key_mgmt", "legacy_vm", "nav_svc", "payload_ctrl",
            "sw_bus", "telemetry", "time_svc"
        ])
        assert results["tcb"]["att_ctrl"] == expected

    def test_tcb_exec_svc(self, results):
        expected = sorted([
            "att_ctrl", "cmd_handler", "crypto_svc", "event_svc", "file_sys",
            "health_mon", "key_mgmt", "legacy_vm", "nav_svc", "payload_ctrl",
            "sw_bus", "telemetry", "time_svc"
        ])
        assert results["tcb"]["exec_svc"] == expected


# --- Impact Boundary Tests ---

class TestImpactBoundary:
    def test_ib_all_pds(self, results, spec):
        pd_names = {pd["name"] for pd in spec["protection_domains"]}
        assert set(results["impact_boundary"].keys()) == pd_names

    def test_ib_nav_svc_count(self, results):
        """nav_svc reaches all 17 other PDs."""
        assert len(results["impact_boundary"]["nav_svc"]) == 17

    def test_ib_downlink(self, results):
        assert results["impact_boundary"]["downlink"] == ["uart_drv"]

    def test_ib_uart_drv(self, results):
        assert results["impact_boundary"]["uart_drv"] == ["downlink"]

    def test_ib_eth_drv(self, results):
        assert results["impact_boundary"]["eth_drv"] == sorted(["downlink", "net_stack", "uart_drv"])

    def test_ib_net_stack(self, results):
        assert results["impact_boundary"]["net_stack"] == sorted(["downlink", "eth_drv", "uart_drv"])

    def test_ib_legacy_vm_reaches_all(self, results):
        """legacy_vm at level 0 can still reach 16 PDs through upward flows."""
        assert len(results["impact_boundary"]["legacy_vm"]) == 16


# --- Minimum Revocation Tests ---

class TestMinRevocations:
    def test_total_cost(self, results):
        assert results["total_revocation_cost"] == 100

    def test_cost_sum_matches(self, results):
        computed = sum(r["cost"] for r in results["min_revocations"])
        assert computed == results["total_revocation_cost"]

    def test_revocation_fields(self, results):
        """Each revocation entry must have the required fields."""
        for r in results["min_revocations"]:
            assert "id" in r
            assert "pd" in r
            assert "resource" in r
            assert "cost" in r

    def test_no_inert_in_revocations(self, results):
        """Inert capabilities create no flows; revoking them is pointless."""
        revoked_ids = {r["id"] for r in results["min_revocations"]}
        for inert_id in results["inert_capability_ids"]:
            assert inert_id not in revoked_ids

    def test_cascaded_not_in_direct(self, results):
        """Cascaded IDs must not overlap with directly-revoked IDs."""
        direct_ids = {r["id"] for r in results["min_revocations"]}
        for cid in results["cascaded_revocation_ids"]:
            assert cid not in direct_ids

    def test_cascaded_have_revoked_ancestor(self, results, spec):
        """Every cascaded capability must have an ancestor in the direct revocation set."""
        caps_by_id = {c["id"]: c for c in spec["capabilities"]}
        direct_ids = {r["id"] for r in results["min_revocations"]}

        for cid in results["cascaded_revocation_ids"]:
            # Walk up delegation chain
            found_ancestor = False
            current = cid
            while current is not None:
                parent = caps_by_id[current]["derived_from"]
                if parent in direct_ids:
                    found_ancestor = True
                    break
                current = parent
            assert found_ancestor, f"Cascaded {cid} has no revoked ancestor"

    def test_revocations_eliminate_all_violations(self, results, spec):
        """Functional test: after applying revocations + cascading, no violations remain."""
        # Collect all revoked capability IDs
        all_revoked = {r["id"] for r in results["min_revocations"]}
        all_revoked.update(results["cascaded_revocation_ids"])

        caps_by_id = {c["id"]: c for c in spec["capabilities"]}
        res_types = {r["name"]: r["type"] for r in spec["resources"]}
        labels = {
            pd["name"]: (pd["security_level"], set(pd["compartments"]))
            for pd in spec["protection_domains"]
        }

        # Resolve effective rights for remaining capabilities
        def rights_to_set(r):
            if r == "RW":
                return {"R", "W"}
            return {r}

        def resolve_effective(cap_id, memo):
            if cap_id in memo:
                return memo[cap_id]
            cap = caps_by_id[cap_id]
            declared = rights_to_set(cap["rights"])
            if cap["derived_from"] is None:
                memo[cap_id] = declared
            else:
                parent_eff = resolve_effective(cap["derived_from"], memo)
                memo[cap_id] = declared & parent_eff
            return memo[cap_id]

        memo = {}
        remaining_caps = []
        for cap in spec["capabilities"]:
            if cap["id"] not in all_revoked:
                eff = resolve_effective(cap["id"], memo)
                if len(eff) > 0:
                    remaining_caps.append((cap, eff))

        # Rebuild flow edges from remaining capabilities
        by_resource = defaultdict(list)
        for cap, eff in remaining_caps:
            by_resource[cap["resource"]].append((cap["pd"], eff))

        for res_name, entries in by_resource.items():
            rtype = res_types[res_name]
            if rtype == "shared_memory":
                writers = [pd for pd, eff in entries if "W" in eff]
                readers = [pd for pd, eff in entries if "R" in eff]
                for w in writers:
                    for r in readers:
                        if w != r:
                            assert dominates(labels[r], labels[w]), (
                                f"Remaining violation: {w} -> {r} via {res_name}"
                            )
            elif rtype == "endpoint":
                senders = [pd for pd, eff in entries if "Send" in eff]
                receivers = [pd for pd, eff in entries if "Recv" in eff]
                for s in senders:
                    for rcv in receivers:
                        if s != rcv:
                            assert dominates(labels[rcv], labels[s]), (
                                f"Remaining violation: {s} -> {rcv} via {res_name}"
                            )
            elif rtype == "notification":
                signalers = [pd for pd, eff in entries if "Signal" in eff]
                waiters = [pd for pd, eff in entries if "Wait" in eff]
                for s in signalers:
                    for w in waiters:
                        if s != w:
                            assert dominates(labels[w], labels[s]), (
                                f"Remaining violation: {s} -> {w} via {res_name}"
                            )
