
"""
Validates a redesigned F-Prime FPP topology against all six connection rules,
scheduling constraints, infrastructure wiring completeness, redundancy
requirements, and graphviz visualization output.
"""

import json
import os
import subprocess
import pytest
from collections import defaultdict


@pytest.fixture(scope="module")
def port_types():
    with open("/app/spec/port_types.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def components():
    with open("/app/spec/components.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def runtime():
    with open("/app/spec/runtime.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def baseline():
    with open("/app/spec/topology.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def topo(components):
    path = "/app/redesigned_topology.json"
    assert os.path.exists(path), "redesigned_topology.json not found at /app/"
    with open(path) as f:
        t = json.load(f)
    assert "instances" in t, "topology must have 'instances' key"
    assert "connections" in t, "topology must have 'connections' key"
    for name, inst in t["instances"].items():
        assert inst["component"] in components, (
            f"Instance '{name}' references unknown component '{inst['component']}'"
        )
    return t


def _get_port_def(components, comp_name, port_name):
    comp = components.get(comp_name)
    if comp is None:
        return None
    for p in comp["ports"]:
        if p["name"] == port_name:
            return p
    return None


def _find_conns(connections, source=None, source_port=None, source_index=None,
                target=None, target_port=None, target_index=None):
    results = []
    for c in connections:
        if source is not None and c["source"] != source:
            continue
        if source_port is not None and c["source_port"] != source_port:
            continue
        if source_index is not None and c["source_index"] != source_index:
            continue
        if target is not None and c["target"] != target:
            continue
        if target_port is not None and c["target_port"] != target_port:
            continue
        if target_index is not None and c["target_index"] != target_index:
            continue
        results.append(c)
    return results


# ── Rule 1: Port direction ──────────────────────────────────────────────


class TestDirectionRule:
    def test_source_is_output(self, topo, components):
        for i, conn in enumerate(topo["connections"]):
            inst = topo["instances"][conn["source"]]
            port = _get_port_def(components, inst["component"], conn["source_port"])
            assert port is not None, (
                f"Connection {i}: source port '{conn['source_port']}' not found"
            )
            assert port["direction"] == "output", (
                f"Connection {i}: source '{conn['source']}.{conn['source_port']}' "
                f"has direction '{port['direction']}', expected 'output'"
            )

    def test_target_is_input(self, topo, components):
        for i, conn in enumerate(topo["connections"]):
            inst = topo["instances"][conn["target"]]
            port = _get_port_def(components, inst["component"], conn["target_port"])
            assert port is not None, (
                f"Connection {i}: target port '{conn['target_port']}' not found"
            )
            assert port["direction"] == "input", (
                f"Connection {i}: target '{conn['target']}.{conn['target_port']}' "
                f"has direction '{port['direction']}', expected 'input'"
            )


# ── Rule 2: Port type compatibility ─────────────────────────────────────


class TestTypeCompatibility:
    def test_types_match(self, topo, components, port_types):
        for i, conn in enumerate(topo["connections"]):
            src_inst = topo["instances"][conn["source"]]
            tgt_inst = topo["instances"][conn["target"]]
            src_port = _get_port_def(components, src_inst["component"], conn["source_port"])
            tgt_port = _get_port_def(components, tgt_inst["component"], conn["target_port"])
            assert src_port is not None and tgt_port is not None
            src_type = src_port["type"]
            tgt_type = tgt_port["type"]
            src_serial = port_types.get(src_type, {}).get("is_serial", False)
            tgt_serial = port_types.get(tgt_type, {}).get("is_serial", False)
            if src_serial or tgt_serial:
                typed = tgt_type if src_serial else src_type
                if not port_types.get(typed, {}).get("is_serial", False):
                    assert not port_types[typed]["has_return_type"], (
                        f"Connection {i}: serial to typed with return type"
                    )
            else:
                assert src_type == tgt_type, (
                    f"Connection {i}: type mismatch {src_type} vs {tgt_type}"
                )


# ── Rule 3: Port array bounds ───────────────────────────────────────────


class TestArrayBounds:
    def test_indices_in_range(self, topo, components):
        for i, conn in enumerate(topo["connections"]):
            src_inst = topo["instances"][conn["source"]]
            tgt_inst = topo["instances"][conn["target"]]
            src_port = _get_port_def(components, src_inst["component"], conn["source_port"])
            tgt_port = _get_port_def(components, tgt_inst["component"], conn["target_port"])
            assert src_port is not None and tgt_port is not None
            assert 0 <= conn["source_index"] < src_port["size"], (
                f"Connection {i}: source index {conn['source_index']} out of bounds "
                f"(size {src_port['size']})"
            )
            assert 0 <= conn["target_index"] < tgt_port["size"], (
                f"Connection {i}: target index {conn['target_index']} out of bounds "
                f"(size {tgt_port['size']})"
            )


# ── Rule 4: Output port uniqueness ──────────────────────────────────────


class TestOutputUniqueness:
    def test_no_duplicate_outputs(self, topo):
        seen = {}
        for i, conn in enumerate(topo["connections"]):
            key = (conn["source"], conn["source_port"], conn["source_index"])
            assert key not in seen, (
                f"Connection {i}: duplicate output {key}, first at {seen[key]}"
            )
            seen[key] = i


# ── Rule 5: Port name validity ──────────────────────────────────────────


class TestPortNameValidity:
    def test_all_port_names_valid(self, topo, components):
        for i, conn in enumerate(topo["connections"]):
            src_inst = topo["instances"][conn["source"]]
            tgt_inst = topo["instances"][conn["target"]]
            assert _get_port_def(components, src_inst["component"], conn["source_port"]) is not None, (
                f"Connection {i}: source port '{conn['source_port']}' not found on "
                f"'{src_inst['component']}'"
            )
            assert _get_port_def(components, tgt_inst["component"], conn["target_port"]) is not None, (
                f"Connection {i}: target port '{conn['target_port']}' not found on "
                f"'{tgt_inst['component']}'"
            )


# ── Rule 6: Port matching ───────────────────────────────────────────────


class TestMatchSpecifiers:
    def test_match_constraints(self, topo, components):
        for inst_name, inst_def in topo["instances"].items():
            comp = components[inst_def["component"]]
            for match in comp.get("match_specifiers", []):
                p1_name = match["port1"]
                p2_name = match["port2"]
                p1_targets = {}
                p2_sources = {}
                for conn in topo["connections"]:
                    if conn["source"] == inst_name and conn["source_port"] == p1_name:
                        p1_targets[conn["source_index"]] = conn["target"]
                    if conn["target"] == inst_name and conn["target_port"] == p2_name:
                        p2_sources[conn["target_index"]] = conn["source"]
                shared = set(p1_targets.keys()) & set(p2_sources.keys())
                for idx in shared:
                    assert p1_targets[idx] == p2_sources[idx], (
                        f"Match violation on '{inst_name}': "
                        f"{p1_name}[{idx}] -> '{p1_targets[idx]}' but "
                        f"{p2_name}[{idx}] <- '{p2_sources[idx]}'"
                    )


# ── New instances ────────────────────────────────────────────────────────


class TestNewInstances:
    def test_filedownlink_exists(self, topo):
        assert "fileDownlink" in topo["instances"], "Missing fileDownlink instance"
        assert topo["instances"]["fileDownlink"]["component"] == "Svc.FileDownlink"

    def test_buffermgr_exists(self, topo):
        assert "bufferMgr" in topo["instances"], "Missing bufferMgr instance"
        assert topo["instances"]["bufferMgr"]["component"] == "Svc.BufferManager"

    def test_backup_cmddisp_exists(self, topo):
        assert "backupCmdDisp" in topo["instances"], "Missing backupCmdDisp instance"
        assert topo["instances"]["backupCmdDisp"]["component"] == "Svc.CommandDispatcher"

    def test_all_baseline_instances_preserved(self, topo):
        expected = {
            "rateDriver", "rg10Hz", "rg1Hz", "cmdDisp", "cmdSeq",
            "health", "tlmChan", "eventLog", "timeSrc", "sensorMgr",
        }
        assert expected.issubset(set(topo["instances"].keys()))


# ── Scheduling ───────────────────────────────────────────────────────────


class TestScheduling:
    def test_filedownlink_scheduled_by_rg10hz(self, topo):
        conns = _find_conns(topo["connections"],
                            source="rg10Hz", source_port="RateGroupMemberOut",
                            target="fileDownlink", target_port="Run")
        assert len(conns) == 1, (
            f"fileDownlink must be scheduled by rg10Hz, found {len(conns)} connections"
        )

    def test_sensormgr_moved_to_rg1hz(self, topo):
        """sensorMgr must no longer be in rg10Hz (budget overrun); must be in rg1Hz."""
        conns_10hz = _find_conns(topo["connections"],
                                 source="rg10Hz", source_port="RateGroupMemberOut",
                                 target="sensorMgr", target_port="schedIn")
        assert len(conns_10hz) == 0, (
            "sensorMgr should not be scheduled by rg10Hz (budget would be exceeded)"
        )
        conns_1hz = _find_conns(topo["connections"],
                                source="rg1Hz", source_port="RateGroupMemberOut",
                                target="sensorMgr", target_port="schedIn")
        assert len(conns_1hz) == 1, (
            "sensorMgr must be scheduled by rg1Hz after rebalancing"
        )

    def test_health_remains_in_rg10hz(self, topo):
        conns = _find_conns(topo["connections"],
                            source="rg10Hz", source_port="RateGroupMemberOut",
                            target="health", target_port="Run")
        assert len(conns) == 1, "health.Run must remain in rg10Hz"

    def test_tlmchan_remains_in_rg10hz(self, topo):
        conns = _find_conns(topo["connections"],
                            source="rg10Hz", source_port="RateGroupMemberOut",
                            target="tlmChan", target_port="Run")
        assert len(conns) == 1, "tlmChan.Run must remain in rg10Hz"

    def test_rg10hz_budget_not_exceeded(self, topo, runtime):
        """Sum of WCETs for rg10Hz members must not exceed budget."""
        budget = runtime["rate_groups"]["rg10Hz"]["budget_ms"]
        wcets = runtime["component_wcet_ms"]
        total = 0
        for conn in topo["connections"]:
            if conn["source"] == "rg10Hz" and conn["source_port"] == "RateGroupMemberOut":
                key = f"{conn['target']}.{conn['target_port']}"
                if key in wcets:
                    total += wcets[key]
        assert total <= budget, (
            f"rg10Hz total WCET {total}ms exceeds budget {budget}ms"
        )

    def test_rg1hz_budget_not_exceeded(self, topo, runtime):
        budget = runtime["rate_groups"]["rg1Hz"]["budget_ms"]
        wcets = runtime["component_wcet_ms"]
        total = 0
        for conn in topo["connections"]:
            if conn["source"] == "rg1Hz" and conn["source_port"] == "RateGroupMemberOut":
                key = f"{conn['target']}.{conn['target_port']}"
                if key in wcets:
                    total += wcets[key]
        assert total <= budget, (
            f"rg1Hz total WCET {total}ms exceeds budget {budget}ms"
        )


# ── Buffer management ───────────────────────────────────────────────────


class TestBufferManagement:
    def test_filedownlink_buffer_get(self, topo):
        conns = _find_conns(topo["connections"],
                            source="fileDownlink", source_port="bufferGetCaller",
                            target="bufferMgr", target_port="bufferGetCallee")
        assert len(conns) == 1, "fileDownlink.bufferGetCaller must connect to bufferMgr"

    def test_filedownlink_buffer_return(self, topo):
        conns = _find_conns(topo["connections"],
                            source="fileDownlink", source_port="bufferSendOut",
                            target="bufferMgr", target_port="bufferSendIn")
        assert len(conns) == 1, "fileDownlink.bufferSendOut must connect to bufferMgr"


# ── Backup command dispatcher ───────────────────────────────────────────


class TestBackupCmdDisp:
    def _get_cmd_bearing_instances(self, topo, components):
        """Instances that have both a command input and command reg output."""
        result = []
        for name, inst_def in topo["instances"].items():
            comp = components[inst_def["component"]]
            port_names = {p["name"] for p in comp["ports"]}
            has_cmd_in = ("cmdIn" in port_names or "CmdDisp" in port_names)
            has_cmd_reg = ("cmdRegOut" in port_names or "CmdReg" in port_names)
            if has_cmd_in and has_cmd_reg:
                result.append(name)
        return sorted(result)

    def test_backup_dispatches_to_all_cmd_components(self, topo, components):
        """backupCmdDisp.compCmdSend must have connections to all command-bearing components."""
        cmd_instances = self._get_cmd_bearing_instances(topo, components)
        # Exclude backupCmdDisp itself from the list
        cmd_instances = [n for n in cmd_instances if n != "backupCmdDisp"]
        backup_targets = set()
        for conn in topo["connections"]:
            if conn["source"] == "backupCmdDisp" and conn["source_port"] == "compCmdSend":
                backup_targets.add(conn["target"])
        for inst in cmd_instances:
            assert inst in backup_targets, (
                f"backupCmdDisp.compCmdSend must dispatch to '{inst}'"
            )

    def test_backup_match_specifier_satisfied(self, topo, components):
        """The match compCmdSend with compCmdReg must be satisfied on backupCmdDisp."""
        comp = components["Svc.CommandDispatcher"]
        for match in comp["match_specifiers"]:
            p1_name = match["port1"]
            p2_name = match["port2"]
            p1_targets = {}
            p2_sources = {}
            for conn in topo["connections"]:
                if conn["source"] == "backupCmdDisp" and conn["source_port"] == p1_name:
                    p1_targets[conn["source_index"]] = conn["target"]
                if conn["target"] == "backupCmdDisp" and conn["target_port"] == p2_name:
                    p2_sources[conn["target_index"]] = conn["source"]
            shared = set(p1_targets.keys()) & set(p2_sources.keys())
            for idx in shared:
                assert p1_targets[idx] == p2_sources[idx], (
                    f"Match violation on backupCmdDisp: "
                    f"{p1_name}[{idx}] -> '{p1_targets[idx]}' but "
                    f"{p2_name}[{idx}] <- '{p2_sources[idx]}'"
                )


# ── Health monitoring ────────────────────────────────────────────────────


class TestHealthMonitoring:
    def _get_active_queued_instances(self, topo, components):
        """Return instances with kind active or queued that have ping ports."""
        result = []
        for name, inst_def in topo["instances"].items():
            if name == "health":
                continue
            comp = components[inst_def["component"]]
            if comp["kind"] not in ("active", "queued"):
                continue
            port_names = {p["name"] for p in comp["ports"]}
            if "pingIn" in port_names and "pingOut" in port_names:
                result.append(name)
        return sorted(result)

    def test_all_active_components_health_monitored(self, topo, components):
        """Every active/queued component with ping ports must have PingSend/PingReturn."""
        monitored = self._get_active_queued_instances(topo, components)
        for inst in monitored:
            send_conns = _find_conns(topo["connections"],
                                     source="health", source_port="PingSend",
                                     target=inst, target_port="pingIn")
            assert len(send_conns) >= 1, (
                f"Missing health.PingSend -> {inst}.pingIn connection"
            )
            ret_conns = _find_conns(topo["connections"],
                                    source=inst, source_port="pingOut",
                                    target="health", target_port="PingReturn")
            assert len(ret_conns) >= 1, (
                f"Missing {inst}.pingOut -> health.PingReturn connection"
            )

    def test_health_ping_indices_matched(self, topo, components):
        """PingSend[i] target must equal PingReturn[i] source (match specifier)."""
        send_targets = {}
        ret_sources = {}
        for conn in topo["connections"]:
            if conn["source"] == "health" and conn["source_port"] == "PingSend":
                send_targets[conn["source_index"]] = conn["target"]
            if conn["target"] == "health" and conn["target_port"] == "PingReturn":
                ret_sources[conn["target_index"]] = conn["source"]
        shared = set(send_targets.keys()) & set(ret_sources.keys())
        for idx in shared:
            assert send_targets[idx] == ret_sources[idx], (
                f"Health match violation: PingSend[{idx}] -> '{send_targets[idx]}' "
                f"but PingReturn[{idx}] <- '{ret_sources[idx]}'"
            )


# ── Infrastructure wiring ────────────────────────────────────────────────


class TestInfrastructureWiring:
    def _instances_with_port(self, topo, components, port_name):
        result = []
        for inst_name, inst_def in topo["instances"].items():
            comp = components[inst_def["component"]]
            for p in comp["ports"]:
                if p["name"] == port_name and p["direction"] == "output":
                    result.append(inst_name)
        return result

    def test_telemetry_wiring(self, topo, components):
        """All components with Tlm or tlmOut output ports must connect to tlmChan."""
        for port_name in ("Tlm", "tlmOut"):
            for inst in self._instances_with_port(topo, components, port_name):
                conns = _find_conns(topo["connections"],
                                    source=inst, source_port=port_name,
                                    target="tlmChan", target_port="TlmRecv")
                assert len(conns) >= 1, (
                    f"Missing {inst}.{port_name} -> tlmChan.TlmRecv"
                )

    def test_event_wiring(self, topo, components):
        """All components with Log or logOut must connect to eventLog."""
        for port_name in ("Log", "logOut"):
            for inst in self._instances_with_port(topo, components, port_name):
                conns = _find_conns(topo["connections"],
                                    source=inst, source_port=port_name,
                                    target="eventLog", target_port="LogRecv")
                assert len(conns) >= 1, (
                    f"Missing {inst}.{port_name} -> eventLog.LogRecv"
                )

    def test_text_event_wiring(self, topo, components):
        """All components with LogText must connect to eventLog."""
        for inst in self._instances_with_port(topo, components, "LogText"):
            conns = _find_conns(topo["connections"],
                                source=inst, source_port="LogText",
                                target="eventLog", target_port="TextLogRecv")
            assert len(conns) >= 1, (
                f"Missing {inst}.LogText -> eventLog.TextLogRecv"
            )

    def test_time_wiring(self, topo, components):
        """All components with timeGetOut must connect to timeSrc."""
        for inst in self._instances_with_port(topo, components, "timeGetOut"):
            conns = _find_conns(topo["connections"],
                                source=inst, source_port="timeGetOut",
                                target="timeSrc", target_port="timeGetIn")
            assert len(conns) >= 1, (
                f"Missing {inst}.timeGetOut -> timeSrc.timeGetIn"
            )


# ── Graphviz output ──────────────────────────────────────────────────────


class TestVisualization:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/topology.dot"), "topology.dot not found"

    def test_dot_file_valid(self):
        """The DOT file must be parseable by graphviz."""
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/topology.dot", "-o", "/dev/null"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"dot parsing failed: {result.stderr}"
        )

    def test_dot_contains_all_instances(self, topo):
        with open("/app/topology.dot") as f:
            dot_content = f.read()
        for inst_name in topo["instances"]:
            assert inst_name in dot_content, (
                f"Instance '{inst_name}' not found in DOT file"
            )

    def test_dot_has_color_coded_edges(self):
        with open("/app/topology.dot") as f:
            dot_content = f.read()
        for color in ("red", "green", "blue", "orange", "purple", "brown"):
            assert color in dot_content, (
                f"DOT file should have '{color}' colored edges"
            )

    def test_svg_file_exists(self):
        assert os.path.exists("/app/topology.svg"), "topology.svg not found"

    def test_svg_file_valid(self):
        with open("/app/topology.svg") as f:
            content = f.read()
        assert "<svg" in content, "topology.svg does not contain valid SVG markup"


# ── Scheduling report ────────────────────────────────────────────────────


class TestSchedulingReport:
    def test_report_exists(self):
        path = "/app/scheduling_report.json"
        assert os.path.exists(path), "scheduling_report.json not found"

    def test_report_structure(self, runtime):
        with open("/app/scheduling_report.json") as f:
            report = json.load(f)
        for rg_name in runtime["rate_groups"]:
            assert rg_name in report, f"Missing rate group '{rg_name}' in report"
            rg = report[rg_name]
            assert "period_ms" in rg
            assert "budget_ms" in rg
            assert "members" in rg
            assert "total_wcet_ms" in rg
            assert "utilization_pct" in rg
            assert "feasible" in rg

    def test_report_feasibility(self):
        with open("/app/scheduling_report.json") as f:
            report = json.load(f)
        for rg_name, rg_data in report.items():
            assert rg_data["feasible"] is True, (
                f"Rate group '{rg_name}' reported as infeasible"
            )

    def test_report_utilization_correct(self, runtime):
        with open("/app/scheduling_report.json") as f:
            report = json.load(f)
        for rg_name in runtime["rate_groups"]:
            rg = report[rg_name]
            expected_util = (rg["total_wcet_ms"] / rg["budget_ms"]) * 100.0
            assert abs(rg["utilization_pct"] - expected_util) < 1.0, (
                f"Utilization for {rg_name}: expected ~{expected_util:.1f}%, "
                f"got {rg['utilization_pct']:.1f}%"
            )


# ── Design decisions ─────────────────────────────────────────────────────


class TestDesignDecisions:
    def test_decisions_exist(self):
        path = "/app/design_decisions.json"
        assert os.path.exists(path), "design_decisions.json not found"

    def test_decisions_structure(self):
        with open("/app/design_decisions.json") as f:
            decisions = json.load(f)
        assert isinstance(decisions, list)
        assert len(decisions) >= 3, (
            f"Expected at least 3 design decisions, got {len(decisions)}"
        )
        for i, d in enumerate(decisions):
            assert "decision" in d, f"Decision {i} missing 'decision' key"
            assert "rationale" in d, f"Decision {i} missing 'rationale' key"


# ── Baseline preservation ────────────────────────────────────────────────


class TestBaselinePreservation:
    def test_critical_command_path_preserved(self, topo):
        """Primary command dispatch connections must still exist."""
        conns = _find_conns(topo["connections"],
                            source="cmdDisp", source_port="compCmdSend",
                            source_index=0, target="cmdSeq", target_port="cmdIn")
        assert len(conns) == 1, "cmdDisp.compCmdSend[0] -> cmdSeq.cmdIn must exist"

    def test_rate_driver_connections_preserved(self, topo):
        assert any(
            c["source"] == "rateDriver" and c["target"] == "rg10Hz"
            for c in topo["connections"]
        ), "rateDriver -> rg10Hz must exist"
        assert any(
            c["source"] == "rateDriver" and c["target"] == "rg1Hz"
            for c in topo["connections"]
        ), "rateDriver -> rg1Hz must exist"

    def test_seq_cmd_path_preserved(self, topo):
        conns = _find_conns(topo["connections"],
                            source="cmdSeq", source_port="comCmdOut",
                            target="cmdDisp", target_port="seqCmdBuff")
        assert len(conns) == 1, "cmdSeq.comCmdOut -> cmdDisp.seqCmdBuff must exist"

    def test_primary_cmddisp_match_preserved(self, topo):
        """Primary cmdDisp match specifiers must still hold."""
        send_targets = {}
        reg_sources = {}
        for conn in topo["connections"]:
            if conn["source"] == "cmdDisp" and conn["source_port"] == "compCmdSend":
                send_targets[conn["source_index"]] = conn["target"]
            if conn["target"] == "cmdDisp" and conn["target_port"] == "compCmdReg":
                reg_sources[conn["target_index"]] = conn["source"]
        shared = set(send_targets.keys()) & set(reg_sources.keys())
        for idx in shared:
            assert send_targets[idx] == reg_sources[idx], (
                f"Primary cmdDisp match violation at index {idx}"
            )
