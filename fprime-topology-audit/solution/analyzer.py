"""
F-Prime FPP Topology Analyzer and Corrector.

Loads the topology specification, validates it against all six FPP connection
rules, identifies errors, applies corrections, and writes the fixed topology
and error report.

"""

import json
import copy
from collections import defaultdict


def load_spec():
    with open("/app/spec/port_types.json") as f:
        port_types = json.load(f)
    with open("/app/spec/components.json") as f:
        components = json.load(f)
    with open("/app/spec/topology.json") as f:
        topology = json.load(f)
    return port_types, components, topology


def get_port_def(components, comp_name, port_name):
    comp = components.get(comp_name)
    if comp is None:
        return None
    for p in comp["ports"]:
        if p["name"] == port_name:
            return p
    return None


def validate_topology(port_types, components, topology):
    """Validate the topology against all six FPP rules. Returns list of errors."""
    errors = []
    instances = topology["instances"]
    connections = topology["connections"]

    for i, conn in enumerate(connections):
        src_inst = instances.get(conn["source"])
        tgt_inst = instances.get(conn["target"])
        if src_inst is None or tgt_inst is None:
            errors.append({
                "connection_index": i,
                "rule_violated": "instance_not_found",
                "description": f"Instance not found: source='{conn['source']}' target='{conn['target']}'"
            })
            continue

        src_comp = src_inst["component"]
        tgt_comp = tgt_inst["component"]
        src_port = get_port_def(components, src_comp, conn["source_port"])
        tgt_port = get_port_def(components, tgt_comp, conn["target_port"])

        # Rule 5: Port name validity
        if src_port is None:
            errors.append({
                "connection_index": i,
                "rule_violated": "port_name_validity",
                "description": (
                    f"Source port '{conn['source_port']}' does not exist on "
                    f"component '{src_comp}' (instance '{conn['source']}')"
                )
            })
            continue
        if tgt_port is None:
            errors.append({
                "connection_index": i,
                "rule_violated": "port_name_validity",
                "description": (
                    f"Target port '{conn['target_port']}' does not exist on "
                    f"component '{tgt_comp}' (instance '{conn['target']}')"
                )
            })
            continue

        # Rule 1: Direction
        if src_port["direction"] != "output":
            errors.append({
                "connection_index": i,
                "rule_violated": "port_direction",
                "description": (
                    f"Source '{conn['source']}.{conn['source_port']}' has direction "
                    f"'{src_port['direction']}', expected 'output'"
                )
            })
        if tgt_port["direction"] != "input":
            errors.append({
                "connection_index": i,
                "rule_violated": "port_direction",
                "description": (
                    f"Target '{conn['target']}.{conn['target_port']}' has direction "
                    f"'{tgt_port['direction']}', expected 'input'"
                )
            })

        # Rule 2: Type compatibility
        src_type = src_port["type"]
        tgt_type = tgt_port["type"]
        src_serial = port_types.get(src_type, {}).get("is_serial", False)
        tgt_serial = port_types.get(tgt_type, {}).get("is_serial", False)
        if src_serial or tgt_serial:
            typed = tgt_type if src_serial else src_type
            if not port_types.get(typed, {}).get("is_serial", False):
                if port_types[typed]["has_return_type"]:
                    errors.append({
                        "connection_index": i,
                        "rule_violated": "type_compatibility",
                        "description": (
                            f"Serial port connected to typed port '{typed}' "
                            f"which has a return type"
                        )
                    })
        elif src_type != tgt_type:
            errors.append({
                "connection_index": i,
                "rule_violated": "type_compatibility",
                "description": (
                    f"Type mismatch: '{conn['source']}.{conn['source_port']}' "
                    f"({src_type}) -> '{conn['target']}.{conn['target_port']}' ({tgt_type})"
                )
            })

        # Rule 3: Array bounds
        if conn["source_index"] < 0 or conn["source_index"] >= src_port["size"]:
            errors.append({
                "connection_index": i,
                "rule_violated": "array_bounds",
                "description": (
                    f"Source index {conn['source_index']} out of bounds for "
                    f"'{conn['source']}.{conn['source_port']}' (size {src_port['size']})"
                )
            })
        if conn["target_index"] < 0 or conn["target_index"] >= tgt_port["size"]:
            errors.append({
                "connection_index": i,
                "rule_violated": "array_bounds",
                "description": (
                    f"Target index {conn['target_index']} out of bounds for "
                    f"'{conn['target']}.{conn['target_port']}' (size {tgt_port['size']})"
                )
            })

    # Rule 4: Output uniqueness
    output_map = defaultdict(list)
    for i, conn in enumerate(connections):
        key = (conn["source"], conn["source_port"], conn["source_index"])
        output_map[key].append(i)
    for key, indices in output_map.items():
        if len(indices) > 1:
            errors.append({
                "connection_index": indices[1],
                "rule_violated": "output_uniqueness",
                "description": (
                    f"Duplicate output: {key[0]}.{key[1]}[{key[2]}] "
                    f"used in connections {indices}"
                )
            })

    # Rule 6: Match specifiers
    for inst_name, inst_def in instances.items():
        comp = components[inst_def["component"]]
        for match in comp.get("match_specifiers", []):
            p1 = match["port1"]
            p2 = match["port2"]
            p1_targets = {}
            p2_sources = {}
            for conn in connections:
                if conn["source"] == inst_name and conn["source_port"] == p1:
                    p1_targets[conn["source_index"]] = conn["target"]
                if conn["target"] == inst_name and conn["target_port"] == p2:
                    p2_sources[conn["target_index"]] = conn["source"]
            shared = set(p1_targets.keys()) & set(p2_sources.keys())
            for idx in shared:
                if p1_targets[idx] != p2_sources[idx]:
                    errors.append({
                        "connection_index": -1,
                        "rule_violated": "match_specifier",
                        "description": (
                            f"Match violation on '{inst_name}': "
                            f"{p1}[{idx}] -> '{p1_targets[idx]}' but "
                            f"{p2}[{idx}] <- '{p2_sources[idx]}'"
                        )
                    })

    return errors


def apply_corrections(topology):
    """Apply corrections to the known errors in the topology."""
    topo = copy.deepcopy(topology)
    conns = topo["connections"]
    report = []

    # E1 (index 15): cmdSeq.comCmdOut -> cmdDisp.compCmdReg[3]
    # Fix: target should be seqCmdBuff[0]
    c = conns[15]
    assert c["source"] == "cmdSeq" and c["source_port"] == "comCmdOut"
    report.append({
        "connection_index": 15,
        "rule_violated": "type_compatibility",
        "description": (
            "cmdSeq.comCmdOut[0] (Fw.Com) was connected to cmdDisp.compCmdReg[3] "
            "(Fw.CmdReg) — type mismatch. Fixed: connect to cmdDisp.seqCmdBuff[0] (Fw.Com)."
        )
    })
    c["target_port"] = "seqCmdBuff"
    c["target_index"] = 0

    # E2 (index 32): sensorMgr.tlmOut -> eventLog.LogRecv
    # Fix: target should be tlmChan.TlmRecv[0]
    c = conns[32]
    assert c["source"] == "sensorMgr" and c["source_port"] == "tlmOut"
    report.append({
        "connection_index": 32,
        "rule_violated": "type_compatibility",
        "description": (
            "sensorMgr.tlmOut[0] (Fw.Tlm) was connected to eventLog.LogRecv[0] "
            "(Fw.Log) — type mismatch. Fixed: connect to tlmChan.TlmRecv[0] (Fw.Tlm)."
        )
    })
    c["target"] = "tlmChan"
    c["target_port"] = "TlmRecv"
    c["target_index"] = 0

    # E3 (index 3): rg10Hz.RateGroupMemberOut[10] — index overflow (size 10)
    # Fix: use index 1
    c = conns[3]
    assert c["source"] == "rg10Hz" and c["source_port"] == "RateGroupMemberOut"
    report.append({
        "connection_index": 3,
        "rule_violated": "array_bounds",
        "description": (
            "rg10Hz.RateGroupMemberOut[10] — index 10 exceeds array size 10 "
            "(valid: 0-9). Fixed: use index 1."
        )
    })
    c["source_index"] = 1

    # E4 (index 19): health.PingSend[0] -> rg1Hz — duplicate output
    # PingSend[0] already used at index 17 for rg10Hz
    # Fix: use PingSend[1]
    c = conns[19]
    assert c["source"] == "health" and c["source_port"] == "PingSend" and c["source_index"] == 0
    report.append({
        "connection_index": 19,
        "rule_violated": "output_uniqueness",
        "description": (
            "health.PingSend[0] was already used for rg10Hz.pingIn (connection 17). "
            "Duplicate output to rg1Hz.pingIn. Fixed: use PingSend[1]."
        )
    })
    c["source_index"] = 1

    # E5 (index 34): eventLog.LogRecv[0] -> cmdSeq.logOut[0]
    # Direction violation: LogRecv is input (used as source), logOut is output (used as target)
    # Fix: reverse to cmdSeq.logOut[0] -> eventLog.LogRecv[0]
    c = conns[34]
    assert c["source"] == "eventLog" and c["source_port"] == "LogRecv"
    report.append({
        "connection_index": 34,
        "rule_violated": "port_direction",
        "description": (
            "eventLog.LogRecv (input) was used as source and cmdSeq.logOut (output) "
            "as target — direction reversed. Fixed: cmdSeq.logOut[0] -> eventLog.LogRecv[0]."
        )
    })
    c["source"] = "cmdSeq"
    c["source_port"] = "logOut"
    c["source_index"] = 0
    c["target"] = "eventLog"
    c["target_port"] = "LogRecv"
    c["target_index"] = 0

    # E6 (indices 10, 11): match violation — compCmdReg indices swapped
    # compCmdSend[1] -> health, so compCmdReg[1] should come from health
    # compCmdSend[2] -> sensorMgr, so compCmdReg[2] should come from sensorMgr
    # Currently: health -> [2], sensorMgr -> [1] (swapped)
    # Fix: swap target_index values
    c10 = conns[10]
    c11 = conns[11]
    assert c10["source"] == "health" and c10["target_port"] == "compCmdReg"
    assert c11["source"] == "sensorMgr" and c11["target_port"] == "compCmdReg"
    report.append({
        "connection_index": 10,
        "rule_violated": "match_specifier",
        "description": (
            "health.CmdReg -> cmdDisp.compCmdReg[2] but compCmdSend[1] -> health, "
            "violating match constraint. Fixed: health.CmdReg -> cmdDisp.compCmdReg[1]."
        )
    })
    report.append({
        "connection_index": 11,
        "rule_violated": "match_specifier",
        "description": (
            "sensorMgr.cmdRegOut -> cmdDisp.compCmdReg[1] but compCmdSend[2] -> sensorMgr, "
            "violating match constraint. Fixed: sensorMgr.cmdRegOut -> cmdDisp.compCmdReg[2]."
        )
    })
    c10["target_index"] = 1
    c11["target_index"] = 2

    # E7 (index 5): rg1Hz.SchedOut[0] — port name does not exist
    # ActiveRateGroup has RateGroupMemberOut, not SchedOut
    # Fix: use RateGroupMemberOut[1]
    c = conns[5]
    assert c["source"] == "rg1Hz" and c["source_port"] == "SchedOut"
    report.append({
        "connection_index": 5,
        "rule_violated": "port_name_validity",
        "description": (
            "rg1Hz.SchedOut does not exist on Svc.ActiveRateGroup. "
            "Fixed: use rg1Hz.RateGroupMemberOut[1]."
        )
    })
    c["source_port"] = "RateGroupMemberOut"
    c["source_index"] = 1

    # E8 (index 44): sensorMgr.timeGetOut -> cmdSeq.timeGetOut
    # Both are output ports — direction violation (output-to-output)
    # Fix: connect to timeSrc.timeGetIn[0]
    c = conns[44]
    assert c["source"] == "sensorMgr" and c["source_port"] == "timeGetOut"
    report.append({
        "connection_index": 44,
        "rule_violated": "port_direction",
        "description": (
            "sensorMgr.timeGetOut (output) connected to cmdSeq.timeGetOut (output) — "
            "both are outputs. Fixed: connect to timeSrc.timeGetIn[0] (input)."
        )
    })
    c["target"] = "timeSrc"
    c["target_port"] = "timeGetIn"
    c["target_index"] = 0

    return topo, report


def main():
    port_types, components, topology = load_spec()

    # Validate original topology
    original_errors = validate_topology(port_types, components, topology)
    print(f"Found {len(original_errors)} errors in original topology:")
    for e in original_errors:
        print(f"  [{e['rule_violated']}] conn {e['connection_index']}: {e['description']}")

    # Apply corrections
    corrected, report = apply_corrections(topology)

    # Validate corrected topology
    remaining_errors = validate_topology(port_types, components, corrected)
    if remaining_errors:
        print(f"\nWARNING: {len(remaining_errors)} errors remain after correction:")
        for e in remaining_errors:
            print(f"  [{e['rule_violated']}] conn {e['connection_index']}: {e['description']}")
    else:
        print("\nCorrected topology passes all validation checks.")

    # Write outputs
    with open("/app/corrected_topology.json", "w") as f:
        json.dump(corrected, f, indent=4)
    print("Wrote /app/corrected_topology.json")

    with open("/app/error_report.json", "w") as f:
        json.dump(report, f, indent=4)
    print("Wrote /app/error_report.json")


if __name__ == "__main__":
    main()
