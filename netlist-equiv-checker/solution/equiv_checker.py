#!/usr/bin/env python3
"""
ASAP7 Netlist Equivalence Checker

Validates post-optimization netlists against pre-optimization netlists
for post-placement buffering and gate sizing in ASAP7 7nm technology.

Checks: instance presence, buffer/inverter path parity, physical/macro/IO locations.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple, Optional

BUFFER_SEED = "BUFx2_ASAP7_75t_L"
INVERTER_SEED = "INVx1_ASAP7_75t_L"


@dataclass(frozen=True)
class PinNode:
    pin_name: str
    inst_id: int
    inst_name: str
    is_driver: bool


def load_nodes(node_file: str) -> Dict[str, Tuple[str, str, float, float]]:
    nodes = {}
    with open(node_file) as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) >= 5:
                nodes[row[0].strip()] = (
                    row[1].strip(), row[2].strip(),
                    float(row[3].strip()), float(row[4].strip())
                )
    return nodes


def load_nets(net_file: str):
    nets = {}
    with open(net_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            net_name = parts[0].strip()
            pins = []
            for p in parts[1:]:
                p = p.strip()
                if not p:
                    continue
                if " " in p:
                    inst, pin = p.rsplit(" ", 1)
                    pins.append((inst.strip(), pin.strip()))
                else:
                    pins.append((p.strip(), ""))
            if pins:
                nets[net_name] = (pins[0], pins[1:])
    return nets


def load_equiv_cells(equiv_file: str):
    equiv_groups = {}
    buffer_masters = set()
    inverter_masters = set()

    with open(equiv_file) as f:
        for group_id, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            cells = [c.strip() for c in line.split(",") if c.strip()]
            for cell in cells:
                equiv_groups[cell] = group_id
            if BUFFER_SEED in cells:
                buffer_masters = set(cells)
            if INVERTER_SEED in cells:
                inverter_masters = set(cells)

    return equiv_groups, buffer_masters, inverter_masters


def check_instance_presence(pre_nodes, post_nodes, equiv_groups,
                            buffer_masters, inverter_masters):
    violations = []

    for name, (master, node_type, _, _) in pre_nodes.items():
        if node_type == "IO":
            continue
        if name not in post_nodes:
            violations.append(f"Missing instance: {name}")
            continue
        post_master = post_nodes[name][0]
        if master != post_master:
            pre_grp = equiv_groups.get(master)
            post_grp = equiv_groups.get(post_master)
            if pre_grp is None or post_grp is None or pre_grp != post_grp:
                violations.append(
                    f"Invalid cell substitution: {name} ({master} -> {post_master})"
                )

    pre_insts = {n for n, (_, t, _, _) in pre_nodes.items() if t != "IO"}
    for name, (master, node_type, _, _) in post_nodes.items():
        if node_type == "IO" or name in pre_insts:
            continue
        if master not in buffer_masters and master not in inverter_masters:
            violations.append(
                f"Invalid newly added instance: {name} (master: {master})"
            )

    return len(violations) == 0, violations


def build_graph(post_nets, post_nodes, pre_nodes, buffer_masters, inverter_masters):
    inst_registry = {}
    id_to_inst = {}
    inst_is_matched = {}
    buffer_ids = set()
    inverter_ids = set()
    inst_driver_pins = defaultdict(set)
    inst_sink_pins = defaultdict(set)
    net_edges = defaultdict(list)
    next_id = 0

    for inst_name, (master, _, _, _) in post_nodes.items():
        inst_registry[inst_name] = next_id
        id_to_inst[next_id] = inst_name
        inst_is_matched[next_id] = inst_name in pre_nodes
        if master in buffer_masters:
            buffer_ids.add(next_id)
        elif master in inverter_masters:
            inverter_ids.add(next_id)
        next_id += 1

    for _, (driver, sinks) in post_nets.items():
        driver_inst, driver_pin = driver

        if driver_inst not in inst_registry:
            inst_registry[driver_inst] = next_id
            id_to_inst[next_id] = driver_inst
            inst_is_matched[next_id] = driver_inst in pre_nodes
            next_id += 1

        driver_id = inst_registry[driver_inst]
        inst_driver_pins[driver_id].add(driver_pin)
        driver_node = PinNode(driver_pin, driver_id, driver_inst, True)

        for sink_inst, sink_pin in sinks:
            if sink_inst not in inst_registry:
                inst_registry[sink_inst] = next_id
                id_to_inst[next_id] = sink_inst
                inst_is_matched[next_id] = sink_inst in pre_nodes
                next_id += 1

            sink_id = inst_registry[sink_inst]
            inst_sink_pins[sink_id].add(sink_pin)
            sink_node = PinNode(sink_pin, sink_id, sink_inst, False)
            net_edges[driver_node].append(sink_node)

    internal_edges = defaultdict(list)
    for inst_id in buffer_ids | inverter_ids:
        if inst_is_matched[inst_id]:
            continue
        inst_name = id_to_inst[inst_id]
        for sink_pin in inst_sink_pins[inst_id]:
            sink_node = PinNode(sink_pin, inst_id, inst_name, False)
            for driver_pin in inst_driver_pins[inst_id]:
                drv_node = PinNode(driver_pin, inst_id, inst_name, True)
                internal_edges[sink_node].append(drv_node)

    return (inst_registry, inst_is_matched, buffer_ids, inverter_ids,
            net_edges, internal_edges)


def bfs_from_driver(driver_inst, driver_pin, inst_registry, inst_is_matched,
                    buffer_ids, inverter_ids, net_edges, internal_edges):
    start_id = inst_registry.get(driver_inst)
    if start_id is None:
        return set(), set()

    start_node = PinNode(driver_pin, start_id, driver_inst, True)
    visited = set()
    valid_sinks = set()
    invalid_sinks = set()

    queue = deque([(start_node, 0)])

    while queue:
        node, inv_count = queue.popleft()
        state = (node, inv_count % 2)
        if state in visited:
            continue
        visited.add(state)

        if node.is_driver:
            for sink_node in net_edges.get(node, []):
                is_matched = inst_is_matched.get(sink_node.inst_id, False)
                is_unmatched_buf = (not is_matched and
                                    sink_node.inst_id in buffer_ids)
                is_unmatched_inv = (not is_matched and
                                    sink_node.inst_id in inverter_ids)

                if is_unmatched_buf:
                    if (sink_node, inv_count % 2) not in visited:
                        queue.append((sink_node, inv_count))
                elif is_unmatched_inv:
                    if (sink_node, (inv_count + 1) % 2) not in visited:
                        queue.append((sink_node, inv_count + 1))
                else:
                    sink_key = (sink_node.inst_name, sink_node.pin_name)
                    if inv_count % 2 == 0:
                        valid_sinks.add(sink_key)
                    elif sink_key not in valid_sinks:
                        invalid_sinks.add(sink_key)
        else:
            for driver_node in internal_edges.get(node, []):
                if (driver_node, inv_count % 2) not in visited:
                    queue.append((driver_node, inv_count))

    return valid_sinks, invalid_sinks


def check_buffer_inverter_paths(pre_nets, post_nets, inst_registry,
                                inst_is_matched, buffer_ids, inverter_ids,
                                net_edges, internal_edges):
    violations = []

    # Build direct edge lookup
    direct_edges = set()
    for _, (driver, sinks) in post_nets.items():
        for sink in sinks:
            direct_edges.add((driver[0], driver[1], sink[0], sink[1]))

    # Check pre-opt pairs
    needs_bfs = defaultdict(list)
    for net_name, (driver, sinks) in pre_nets.items():
        d_inst, d_pin = driver
        for s_inst, s_pin in sinks:
            if d_pin == "_IO_" and s_pin == "_IO_":
                continue
            if (d_inst, d_pin, s_inst, s_pin) in direct_edges:
                pass  # direct match
            else:
                needs_bfs[(d_inst, d_pin)].append((net_name, s_inst, s_pin))

    for (d_inst, d_pin), sinks_to_check in needs_bfs.items():
        valid, invalid = bfs_from_driver(
            d_inst, d_pin, inst_registry, inst_is_matched,
            buffer_ids, inverter_ids, net_edges, internal_edges
        )

        for net_name, s_inst, s_pin in sinks_to_check:
            key = (s_inst, s_pin)
            if key in valid:
                continue
            if key in invalid:
                violations.append(
                    f"Net {net_name}: {d_inst}.{d_pin} -> "
                    f"{s_inst}.{s_pin} (odd inverters)"
                )
            else:
                violations.append(
                    f"Net {net_name}: No path {d_inst}.{d_pin} -> "
                    f"{s_inst}.{s_pin}"
                )

    return len(violations) == 0, violations


def check_locations(pre_nodes, post_nodes, node_type, equiv_groups=None):
    violations = []

    for name, (master, ntype, pre_x, pre_y) in pre_nodes.items():
        if ntype != node_type:
            continue
        if node_type == "Inst" and equiv_groups and master in equiv_groups:
            continue
        if name not in post_nodes:
            violations.append(f"Missing {node_type}: {name}")
            continue
        _, _, post_x, post_y = post_nodes[name]
        if abs(pre_x - post_x) > 1e-6 or abs(pre_y - post_y) > 1e-6:
            violations.append(
                f"{node_type} moved: {name} "
                f"({pre_x},{pre_y}) -> ({post_x},{post_y})"
            )

    return len(violations) == 0, violations


def compute_movement_stats(pre_nodes, post_nodes, equiv_groups):
    total_movement = 0.0
    count = 0
    moved_count = 0
    max_movement = 0.0

    for name, (master, node_type, pre_x, pre_y) in pre_nodes.items():
        if node_type != "Inst":
            continue
        if master not in equiv_groups:
            continue
        if name not in post_nodes:
            continue

        _, _, post_x, post_y = post_nodes[name]
        movement = abs(post_x - pre_x) + abs(post_y - pre_y)

        total_movement += movement
        count += 1
        if movement > 1e-6:
            moved_count += 1
        if movement > max_movement:
            max_movement = movement

    avg_movement = total_movement / count if count > 0 else 0.0
    return {
        "matched_cells": count,
        "moved_cells": moved_count,
        "avg_displacement": avg_movement,
        "max_displacement": max_movement,
    }


def main():
    parser = argparse.ArgumentParser(
        description="ASAP7 netlist equivalence checker"
    )
    parser.add_argument("--pre_opt", required=True)
    parser.add_argument("--post_opt", required=True)
    parser.add_argument("--equiv_cells", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    pre_node_file = os.path.join(args.pre_opt, "node.csv")
    pre_net_file = os.path.join(args.pre_opt, "nets.csv")
    post_node_file = os.path.join(args.post_opt, "node.csv")
    post_net_file = os.path.join(args.post_opt, "nets.csv")

    for f in [pre_node_file, pre_net_file, post_node_file, post_net_file, args.equiv_cells]:
        if not os.path.exists(f):
            print(f"Error: File not found: {f}", file=sys.stderr)
            sys.exit(1)

    pre_nodes = load_nodes(pre_node_file)
    post_nodes = load_nodes(post_node_file)
    pre_nets = load_nets(pre_net_file)
    post_nets = load_nets(post_net_file)
    equiv_groups, buf_masters, inv_masters = load_equiv_cells(args.equiv_cells)

    results = {}

    # Check 1: Instance presence
    passed, viols = check_instance_presence(
        pre_nodes, post_nodes, equiv_groups, buf_masters, inv_masters
    )
    results["check_1_instance_presence"] = {
        "pass": passed, "violation_count": len(viols)
    }

    # Build graph for check 2
    graph_data = build_graph(
        post_nets, post_nodes, pre_nodes, buf_masters, inv_masters
    )
    inst_reg, inst_matched, buf_ids, inv_ids, n_edges, i_edges = graph_data

    # Check 2: Buffer/inverter paths
    passed, viols = check_buffer_inverter_paths(
        pre_nets, post_nets, inst_reg, inst_matched,
        buf_ids, inv_ids, n_edges, i_edges
    )
    results["check_2_buffer_inverter_paths"] = {
        "pass": passed, "violation_count": len(viols)
    }

    # Check 3: Physical cell locations
    passed, viols = check_locations(pre_nodes, post_nodes, "Inst", equiv_groups)
    results["check_3_physical_cells"] = {
        "pass": passed, "violation_count": len(viols)
    }

    # Check 4: Macro locations
    passed, viols = check_locations(pre_nodes, post_nodes, "Macro")
    results["check_4_macros"] = {
        "pass": passed, "violation_count": len(viols)
    }

    # Check 5: IO locations
    passed, viols = check_locations(pre_nodes, post_nodes, "IO")
    results["check_5_io"] = {
        "pass": passed, "violation_count": len(viols)
    }

    # Movement statistics
    results["movement_stats"] = compute_movement_stats(
        pre_nodes, post_nodes, equiv_groups
    )

    # Overall result
    all_pass = all(
        results[k]["pass"]
        for k in [
            "check_1_instance_presence",
            "check_2_buffer_inverter_paths",
            "check_3_physical_cells",
            "check_4_macros",
            "check_5_io",
        ]
    )
    results["overall"] = "EQUIVALENT" if all_pass else "NOT_EQUIVALENT"

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Result: {results['overall']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
