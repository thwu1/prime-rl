#!/usr/bin/env python3
"""
Static Timing Analysis engine for gate-level netlists with Liberty NLDM models.

"""

import json
import re
import sys
from collections import defaultdict


# ─── Liberty Parser ─────────────────────────────────────────────────

def find_matching_brace(text, start):
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
        i += 1
    return i


def parse_liberty(filepath):
    with open(filepath) as f:
        content = f.read()
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'//.*', '', content)

    lib = {"cells": {}, "templates": {}}

    # Parse table templates for index values
    for m in re.finditer(r'lu_table_template\s*\(\s*(\w+)\s*\)\s*\{', content):
        tname = m.group(1)
        tbody = content[m.end():find_matching_brace(content, m.end()) - 1]
        indices = {}
        for im in re.finditer(r'index_(\d)\s*\(\s*"([^"]+)"\s*\)', tbody):
            idx_num = int(im.group(1))
            vals = [float(x.strip()) for x in im.group(2).split(',')]
            indices[idx_num] = vals
        lib["templates"][tname] = indices

    for m in re.finditer(r'cell\s*\(\s*(\w+)\s*\)\s*\{', content):
        cell_name = m.group(1)
        cell_body = content[m.end():find_matching_brace(content, m.end()) - 1]
        lib["cells"][cell_name] = parse_cell(cell_name, cell_body, lib["templates"])

    return lib


def parse_cell(name, body, templates):
    cell = {"name": name, "pins": {}, "is_ff": False}

    m = re.search(r'\barea\s*:\s*([\-\d.eE+]+)\s*;', body)
    cell["area"] = float(m.group(1)) if m else 0

    if re.search(r'\bff\s*\(', body):
        cell["is_ff"] = True

    for pm in re.finditer(r'pin\s*\(\s*(\w+)\s*\)\s*\{', body):
        pin_name = pm.group(1)
        pin_body = body[pm.end():find_matching_brace(body, pm.end()) - 1]
        cell["pins"][pin_name] = parse_pin(pin_name, pin_body, templates)

    return cell


def parse_pin(name, body, templates):
    pin = {"name": name, "timing_groups": [], "constraints": []}

    m = re.search(r'\bdirection\s*:\s*(\w+)\s*;', body)
    pin["direction"] = m.group(1) if m else None

    m = re.search(r'(?<!\w)capacitance\s*:\s*([\-\d.eE+]+)\s*;', body)
    pin["capacitance"] = float(m.group(1)) if m else 0.006

    pin["is_clock"] = bool(re.search(r'clock\s*:\s*true', body))

    for tm in re.finditer(r'timing\s*\(\s*\)\s*\{', body):
        tg_body = body[tm.end():find_matching_brace(body, tm.end()) - 1]
        tg = parse_timing_group(tg_body, templates)
        if tg.get("timing_type") in ("setup_rising", "hold_rising",
                                      "setup_falling", "hold_falling"):
            pin["constraints"].append(tg)
        else:
            pin["timing_groups"].append(tg)

    return pin


def parse_timing_group(body, templates):
    tg = {"tables": {}}

    m = re.search(r'related_pin\s*:\s*"(\w+)"\s*;', body)
    tg["related_pin"] = m.group(1) if m else None

    m = re.search(r'timing_type\s*:\s*(\w+)\s*;', body)
    tg["timing_type"] = m.group(1) if m else "combinational"

    m = re.search(r'timing_sense\s*:\s*(\w+)\s*;', body)
    tg["timing_sense"] = m.group(1) if m else "non_unate"

    table_types = ["cell_rise", "cell_fall", "rise_transition", "fall_transition",
                   "rise_constraint", "fall_constraint"]
    for tt in table_types:
        pattern = tt + r'\s*\(\s*(\w+)\s*\)\s*\{'
        for tm in re.finditer(pattern, body):
            template_name = tm.group(1)
            tbl_body = body[tm.end():find_matching_brace(body, tm.end()) - 1]
            values_m = re.search(r'values\s*\((.*?)\)\s*;', tbl_body, re.DOTALL)
            if values_m:
                rows = re.findall(r'"([^"]+)"', values_m.group(1))
                table = [[float(x.strip()) for x in row.split(',')] for row in rows]
                idx = templates.get(template_name, {})
                tg["tables"][tt] = {
                    "data": table,
                    "index_1": idx.get(1, []),
                    "index_2": idx.get(2, []),
                }

    return tg


# ─── NLDM Interpolation ────────────────────────────────────────────

def bilinear_interp(table_info, val1, val2):
    table = table_info["data"]
    idx1 = table_info["index_1"]
    idx2 = table_info["index_2"]

    def find_interval(val, indices):
        for i in range(len(indices) - 1):
            if val <= indices[i + 1]:
                return i
        return len(indices) - 2

    si = find_interval(val1, idx1)
    li = find_interval(val2, idx2)

    s0, s1 = idx1[si], idx1[si + 1]
    l0, l1 = idx2[li], idx2[li + 1]

    sv = max(s0, min(s1, val1))
    lv = max(l0, min(l1, val2))

    ts = (sv - s0) / (s1 - s0) if s1 != s0 else 0
    tl = (lv - l0) / (l1 - l0) if l1 != l0 else 0

    v00 = table[si][li]
    v01 = table[si][li + 1]
    v10 = table[si + 1][li]
    v11 = table[si + 1][li + 1]

    return v00 * (1 - ts) * (1 - tl) + v01 * (1 - ts) * tl + \
           v10 * ts * (1 - tl) + v11 * ts * tl


# ─── Netlist Parser ─────────────────────────────────────────────────

def parse_netlist(filepath):
    with open(filepath) as f:
        content = f.read()
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'//.*', '', content)

    instances = {}
    # Match: CELL_TYPE instance_name (.PORT(net), ...);
    pattern = r'(\w+)\s+(\w+)\s*\(([^;]+)\)\s*;'
    for m in re.finditer(pattern, content):
        cell_type = m.group(1)
        inst_name = m.group(2)
        ports_str = m.group(3)

        # Skip module declarations (wire, input, output, reg, etc.)
        if cell_type in ('module', 'input', 'output', 'wire', 'reg',
                         'assign', 'endmodule', 'inout'):
            continue

        ports = {}
        for pm in re.finditer(r'\.(\w+)\s*\(([^)]*)\)', ports_str):
            port_name = pm.group(1)
            net_name = pm.group(2).strip()
            if net_name:
                ports[port_name] = net_name
        instances[inst_name] = {"type": cell_type, "ports": ports}

    return instances


# ─── Timing Graph & STA ────────────────────────────────────────────

def build_timing_graph(instances, lib):
    """Build a timing graph: for each net, track driver and loads."""
    net_driver = {}   # net -> (instance, pin)
    net_loads = defaultdict(list)  # net -> [(instance, pin)]

    for inst_name, inst in instances.items():
        cell = lib["cells"].get(inst["type"])
        if not cell:
            continue
        for port, net in inst["ports"].items():
            pin_info = cell["pins"].get(port)
            if not pin_info:
                continue
            if pin_info["direction"] == "output":
                net_driver[net] = (inst_name, port)
            elif pin_info["direction"] == "input":
                net_loads[net].append((inst_name, port))

    return net_driver, net_loads


def compute_net_load(net, net_loads, instances, lib):
    """Compute total capacitive load on a net."""
    total = 0.0
    for inst_name, pin_name in net_loads.get(net, []):
        cell = lib["cells"][instances[inst_name]["type"]]
        pin = cell["pins"][pin_name]
        total += pin.get("capacitance", 0.006)
    return total


def run_sta(instances, lib, clk_slew=0.030):
    """Perform forward static timing analysis."""
    net_driver, net_loads = build_timing_graph(instances, lib)

    # Initialize arrival times
    # For each net: {rise_arrival, fall_arrival, rise_slew, fall_slew}
    net_timing = {}

    # Find all DFF instances (startpoints)
    dff_instances = []
    comb_instances = []
    for inst_name, inst in instances.items():
        cell = lib["cells"].get(inst["type"])
        if cell and cell["is_ff"]:
            dff_instances.append(inst_name)
        elif cell:
            comb_instances.append(inst_name)

    # Initialize DFF outputs with CLK-to-Q delays
    for inst_name in dff_instances:
        inst = instances[inst_name]
        cell = lib["cells"][inst["type"]]
        for pin_name, pin_info in cell["pins"].items():
            if pin_info["direction"] != "output":
                continue
            net = inst["ports"].get(pin_name)
            if not net:
                continue
            load = compute_net_load(net, net_loads, instances, lib)
            for tg in pin_info["timing_groups"]:
                if tg.get("timing_type") == "rising_edge":
                    cr = tg["tables"].get("cell_rise")
                    cf = tg["tables"].get("cell_fall")
                    rt = tg["tables"].get("rise_transition")
                    ft = tg["tables"].get("fall_transition")
                    if cr and cf:
                        rise_delay = bilinear_interp(cr, clk_slew, load)
                        fall_delay = bilinear_interp(cf, clk_slew, load)
                        rise_trans = bilinear_interp(rt, clk_slew, load) if rt else 0.02
                        fall_trans = bilinear_interp(ft, clk_slew, load) if ft else 0.02
                        net_timing[net] = {
                            "rise_arrival": rise_delay,
                            "fall_arrival": fall_delay,
                            "rise_slew": rise_trans,
                            "fall_slew": fall_trans,
                            "source_inst": inst_name,
                            "source_pin": pin_name,
                        }

    # Topological traversal of combinational gates
    visited = set()
    changed = True
    max_iters = 100
    iteration = 0
    while changed and iteration < max_iters:
        changed = False
        iteration += 1
        for inst_name in comb_instances:
            if inst_name in visited:
                continue
            inst = instances[inst_name]
            cell = lib["cells"][inst["type"]]

            # Check if all inputs have timing
            all_ready = True
            for pin_name, pin_info in cell["pins"].items():
                if pin_info["direction"] == "input":
                    net = inst["ports"].get(pin_name)
                    if net and net not in net_timing:
                        all_ready = False
                        break

            if not all_ready:
                continue

            visited.add(inst_name)
            changed = True

            # Process each output pin
            for out_pin, out_info in cell["pins"].items():
                if out_info["direction"] != "output":
                    continue
                out_net = inst["ports"].get(out_pin)
                if not out_net:
                    continue
                load = compute_net_load(out_net, net_loads, instances, lib)

                best_rise = -1
                best_fall = -1
                best_rise_slew = 0.02
                best_fall_slew = 0.02

                for tg in out_info["timing_groups"]:
                    rp = tg["related_pin"]
                    in_net = inst["ports"].get(rp)
                    if not in_net or in_net not in net_timing:
                        continue

                    in_timing = net_timing[in_net]
                    sense = tg.get("timing_sense", "non_unate")

                    cr = tg["tables"].get("cell_rise")
                    cf = tg["tables"].get("cell_fall")
                    rt = tg["tables"].get("rise_transition")
                    ft = tg["tables"].get("fall_transition")

                    if sense == "positive_unate":
                        r_delay = bilinear_interp(cr, in_timing["rise_slew"], load) if cr else 0
                        f_delay = bilinear_interp(cf, in_timing["fall_slew"], load) if cf else 0
                        r_arr = in_timing["rise_arrival"] + r_delay
                        f_arr = in_timing["fall_arrival"] + f_delay
                        r_slew = bilinear_interp(rt, in_timing["rise_slew"], load) if rt else 0.02
                        f_slew = bilinear_interp(ft, in_timing["fall_slew"], load) if ft else 0.02
                    elif sense == "negative_unate":
                        r_delay = bilinear_interp(cr, in_timing["fall_slew"], load) if cr else 0
                        f_delay = bilinear_interp(cf, in_timing["rise_slew"], load) if cf else 0
                        r_arr = in_timing["fall_arrival"] + r_delay
                        f_arr = in_timing["rise_arrival"] + f_delay
                        r_slew = bilinear_interp(rt, in_timing["fall_slew"], load) if rt else 0.02
                        f_slew = bilinear_interp(ft, in_timing["rise_slew"], load) if ft else 0.02
                    else:  # non_unate
                        r_delay = bilinear_interp(cr, max(in_timing["rise_slew"], in_timing["fall_slew"]), load) if cr else 0
                        f_delay = bilinear_interp(cf, max(in_timing["rise_slew"], in_timing["fall_slew"]), load) if cf else 0
                        r_arr = max(in_timing["rise_arrival"], in_timing["fall_arrival"]) + r_delay
                        f_arr = max(in_timing["rise_arrival"], in_timing["fall_arrival"]) + f_delay
                        r_slew = bilinear_interp(rt, max(in_timing["rise_slew"], in_timing["fall_slew"]), load) if rt else 0.02
                        f_slew = bilinear_interp(ft, max(in_timing["rise_slew"], in_timing["fall_slew"]), load) if ft else 0.02

                    if r_arr > best_rise:
                        best_rise = r_arr
                        best_rise_slew = r_slew
                    if f_arr > best_fall:
                        best_fall = f_arr
                        best_fall_slew = f_slew

                if best_rise >= 0:
                    net_timing[out_net] = {
                        "rise_arrival": best_rise,
                        "fall_arrival": best_fall,
                        "rise_slew": best_rise_slew,
                        "fall_slew": best_fall_slew,
                        "source_inst": inst_name,
                        "source_pin": out_pin,
                    }

    # Find worst endpoint (DFF data input)
    worst_slack = float('inf')
    worst_path_info = None

    for inst_name in dff_instances:
        inst = instances[inst_name]
        cell = lib["cells"][inst["type"]]
        for pin_name, pin_info in cell["pins"].items():
            if pin_info["direction"] != "input":
                continue
            if pin_info.get("is_clock"):
                continue
            net = inst["ports"].get(pin_name)
            if not net or net not in net_timing:
                continue

            in_timing = net_timing[net]
            data_arrival = max(in_timing["rise_arrival"], in_timing["fall_arrival"])
            data_slew = max(in_timing["rise_slew"], in_timing["fall_slew"])

            # Find setup constraint
            setup_time = 0.030  # default
            for ct in pin_info.get("constraints", []):
                if "setup" in ct.get("timing_type", ""):
                    rc = ct["tables"].get("rise_constraint")
                    fc = ct["tables"].get("fall_constraint")
                    if rc:
                        setup_time = max(setup_time,
                                         bilinear_interp(rc, clk_slew, data_slew))
                    if fc:
                        setup_time = max(setup_time,
                                         bilinear_interp(fc, clk_slew, data_slew))

            if data_arrival + setup_time > 0:
                if worst_path_info is None or data_arrival > worst_path_info["arrival"]:
                    worst_path_info = {
                        "endpoint": inst_name,
                        "endpoint_pin": pin_name,
                        "arrival": data_arrival,
                        "setup_time": setup_time,
                    }

    return net_timing, worst_path_info


def trace_critical_path(instances, lib, net_timing, endpoint_inst, endpoint_pin):
    """Backtrace the critical path from endpoint to startpoint."""
    net_driver, net_loads = build_timing_graph(instances, lib)
    path = []

    current_inst = endpoint_inst
    current_pin = endpoint_pin
    current_net = instances[current_inst]["ports"].get(current_pin)

    while current_net and current_net in net_timing:
        timing = net_timing[current_net]
        driver_inst = timing.get("source_inst")
        driver_pin = timing.get("source_pin")
        if not driver_inst:
            break

        cell_type = instances[driver_inst]["type"]
        cell = lib["cells"].get(cell_type)

        # Find which input pin contributes to worst arrival
        if cell and cell["is_ff"]:
            path.append({
                "cell": cell_type,
                "instance": driver_inst,
                "arc": f"CLK->{driver_pin}",
            })
            break

        # Find the input arc
        best_input = None
        best_arrival = -1
        for tg in cell["pins"][driver_pin]["timing_groups"]:
            rp = tg["related_pin"]
            in_net = instances[driver_inst]["ports"].get(rp)
            if in_net and in_net in net_timing:
                in_arr = max(net_timing[in_net]["rise_arrival"],
                             net_timing[in_net]["fall_arrival"])
                if in_arr > best_arrival:
                    best_arrival = in_arr
                    best_input = rp
                    best_input_net = in_net

        if best_input:
            path.append({
                "cell": cell_type,
                "instance": driver_inst,
                "arc": f"{best_input}->{driver_pin}",
            })
            current_net = best_input_net
        else:
            break

    path.reverse()
    return path


def analyze_netlist(netlist_path, lib_path, clock_period, clk_slew=0.030):
    """Full STA analysis of a netlist."""
    lib = parse_liberty(lib_path)
    instances = parse_netlist(netlist_path)

    # Cell metrics
    total_cells = len(instances)
    cell_counts = defaultdict(int)
    total_area = 0.0
    for inst in instances.values():
        ct = inst["type"]
        cell_counts[ct] += 1
        cell_info = lib["cells"].get(ct)
        if cell_info:
            total_area += cell_info["area"]

    # STA
    net_timing, worst_path = run_sta(instances, lib, clk_slew)

    if worst_path:
        critical_delay = worst_path["arrival"]
        setup_time = worst_path["setup_time"]
        slack = clock_period - critical_delay - setup_time
        path_stages = trace_critical_path(
            instances, lib, net_timing,
            worst_path["endpoint"], worst_path["endpoint_pin"]
        )
    else:
        critical_delay = 0
        setup_time = 0
        slack = clock_period
        path_stages = []

    return {
        "total_cells": total_cells,
        "cell_counts": dict(cell_counts),
        "total_area_um2": round(total_area, 3),
        "critical_path_delay_ns": round(critical_delay, 5),
        "critical_path_stages": path_stages,
        "setup_time_ns": round(setup_time, 5),
        "clock_period_ns": clock_period,
        "worst_slack_ns": round(slack, 5),
        "meets_timing": slack >= 0,
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: sta_engine.py <netlist.v> <cells.lib> [clock_period_ns]")
        sys.exit(1)

    netlist_path = sys.argv[1]
    lib_path = sys.argv[2]
    clock_period = float(sys.argv[3]) if len(sys.argv) > 3 else 0.250

    result = analyze_netlist(netlist_path, lib_path, clock_period)
    print(json.dumps(result, indent=2))
