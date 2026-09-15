#!/usr/bin/env python3
"""
Hubris RTOS Configuration Analyzer and Repair Tool

Parses Hubris-style app.toml and chip.toml, validates against RTOS constraints,
computes ARM Cortex-M MPU-aligned memory layout, analyzes IPC dependency graph,
generates a corrected configuration, and produces optimization report.
"""

import argparse
import copy
import json
import os
import tomllib
from collections import defaultdict

import tomli_w


def load_configs():
    with open("/app/config/app.toml", "rb") as f:
        app = tomllib.load(f)
    with open("/app/config/chip.toml", "rb") as f:
        chip = tomllib.load(f)
    return app, chip


def next_power_of_2(n):
    if n <= 1:
        return 1
    p = 1
    while p < n:
        p <<= 1
    return p


def align_up(addr, alignment):
    if alignment == 0:
        return addr
    return ((addr + alignment - 1) // alignment) * alignment


def tasks_sorted(app):
    result = []
    for name, cfg in app.get("tasks", {}).items():
        result.append((cfg.get("priority", 255), name, cfg))
    result.sort(key=lambda x: (x[0], x[1]))
    return result


def find_cycles(adj, all_nodes):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in all_nodes}
    path = []
    cycles = []

    def dfs(u):
        color[u] = GRAY
        path.append(u)
        for v in adj.get(u, []):
            if color[v] == GRAY:
                idx = path.index(v)
                cycles.append(path[idx:] + [v])
            elif color[v] == WHITE:
                dfs(v)
        path.pop()
        color[u] = BLACK

    for node in sorted(all_nodes):
        if color[node] == WHITE:
            dfs(node)
    return cycles


def validate(app, chip):
    errors = []
    tasks = app.get("tasks", {})
    task_names = set(tasks.keys())
    chip_periphs = set(chip.get("peripherals", {}).keys())

    # 1. Peripheral exclusivity
    periph_owners = defaultdict(list)
    for tname, tcfg in tasks.items():
        for p in tcfg.get("uses", []):
            periph_owners[p].append(tname)
    for p, owners in sorted(periph_owners.items()):
        if len(owners) > 1:
            errors.append({
                "error_type": "peripheral_conflict",
                "description": (
                    f"Peripheral '{p}' is used by multiple tasks: "
                    f"{', '.join(sorted(owners))}"
                ),
                "affected_tasks": sorted(owners),
            })

    # 2. Peripheral existence
    for tname in sorted(tasks):
        for p in tasks[tname].get("uses", []):
            if p not in chip_periphs:
                errors.append({
                    "error_type": "nonexistent_peripheral",
                    "description": (
                        f"Task '{tname}' references nonexistent peripheral '{p}'"
                    ),
                    "affected_tasks": [tname],
                })

    # 3. Task-slot validity
    for tname in sorted(tasks):
        for slot in tasks[tname].get("task-slots", []):
            if slot not in task_names:
                errors.append({
                    "error_type": "nonexistent_task_reference",
                    "description": (
                        f"Task '{tname}' references nonexistent task "
                        f"'{slot}' in task-slots"
                    ),
                    "affected_tasks": [tname],
                })

    # 4. Interrupt-notification consistency
    for tname in sorted(tasks):
        tcfg = tasks[tname]
        notifs = set(tcfg.get("notifications", []))
        for irq, notif_name in tcfg.get("interrupts", {}).items():
            if notif_name not in notifs:
                errors.append({
                    "error_type": "interrupt_notification_mismatch",
                    "description": (
                        f"Task '{tname}' maps interrupt '{irq}' to notification "
                        f"'{notif_name}' which is not declared in notifications"
                    ),
                    "affected_tasks": [tname],
                })

    # 5. Priority inversions
    for tname in sorted(tasks):
        tcfg = tasks[tname]
        my_prio = tcfg.get("priority", 255)
        for slot in tcfg.get("task-slots", []):
            if slot in tasks:
                slot_prio = tasks[slot].get("priority", 255)
                if slot_prio > my_prio:
                    errors.append({
                        "error_type": "priority_inversion",
                        "description": (
                            f"Task '{tname}' (priority {my_prio}) has IPC "
                            f"dependency on '{slot}' (priority {slot_prio}), "
                            f"creating priority inversion risk"
                        ),
                        "affected_tasks": [tname, slot],
                    })

    # 6. Circular dependencies
    adj = defaultdict(list)
    for tname, tcfg in tasks.items():
        for slot in tcfg.get("task-slots", []):
            if slot in task_names:
                adj[tname].append(slot)

    cycles = find_cycles(adj, task_names)
    for cycle in cycles:
        errors.append({
            "error_type": "circular_dependency",
            "description": (
                f"Circular task-slot dependency detected: "
                f"{' -> '.join(cycle)}"
            ),
            "affected_tasks": sorted(set(cycle)),
        })

    return errors, adj


def compute_memory_layout(app, chip):
    kernel = app.get("kernel", {})
    kreq = kernel.get("requires", {})
    kflash = kreq.get("flash", 0)
    kram = kreq.get("ram", 0)

    flash_base = chip["memory"]["flash"]["address"]
    flash_total = chip["memory"]["flash"]["size"]
    ram_base = chip["memory"]["ram"]["address"]
    ram_total = chip["memory"]["ram"]["size"]

    flash_layout = {}
    ram_layout = {}
    flash_overflow = False
    ram_overflow = False

    kf_sz = next_power_of_2(kflash)
    kr_sz = next_power_of_2(kram)

    flash_pos = align_up(flash_base, kf_sz)
    flash_layout["kernel"] = {"address": flash_pos, "size": kf_sz}
    flash_pos += kf_sz

    ram_pos = align_up(ram_base, kr_sz)
    ram_layout["kernel"] = {"address": ram_pos, "size": kr_sz}
    ram_pos += kr_sz

    for _prio, tname, tcfg in tasks_sorted(app):
        msizes = tcfg.get("max-sizes", {})
        tf = msizes.get("flash", 0)
        tr = msizes.get("ram", 0)

        if tf > 0:
            tf_sz = next_power_of_2(tf)
            flash_pos = align_up(flash_pos, tf_sz)
            if flash_pos + tf_sz > flash_base + flash_total:
                flash_overflow = True
            flash_layout[tname] = {"address": flash_pos, "size": tf_sz}
            flash_pos += tf_sz

        if tr > 0:
            tr_sz = next_power_of_2(tr)
            ram_pos = align_up(ram_pos, tr_sz)
            if ram_pos + tr_sz > ram_base + ram_total:
                ram_overflow = True
            ram_layout[tname] = {"address": ram_pos, "size": tr_sz}
            ram_pos += tr_sz

    total_ram = ram_pos - ram_base
    total_flash = flash_pos - flash_base

    return {
        "flash": flash_layout,
        "ram": ram_layout,
        "flash_overflow": flash_overflow,
        "ram_overflow": ram_overflow,
    }, total_ram, total_flash


def build_task_graph(app, adj):
    tasks = app.get("tasks", {})
    task_names = set(tasks.keys())

    edges = []
    for tname in sorted(tasks):
        for slot in tasks[tname].get("task-slots", []):
            if slot in task_names:
                edges.append([tname, slot])

    cycles = find_cycles(adj, task_names)

    priority_inversions = []
    for tname in sorted(tasks):
        tcfg = tasks[tname]
        my_prio = tcfg.get("priority", 255)
        for slot in tcfg.get("task-slots", []):
            if slot in tasks:
                slot_prio = tasks[slot].get("priority", 255)
                if slot_prio > my_prio:
                    priority_inversions.append({
                        "high_priority_task": tname,
                        "low_priority_task": slot,
                    })

    return {
        "edges": edges,
        "cycles": cycles,
        "priority_inversions": priority_inversions,
    }


def generate_fixed_config(app, hash_dma, i2c1_gpio, sensor_ram_actual):
    """Generate a corrected app.toml that resolves all validation errors."""
    fixed = copy.deepcopy(app)
    tasks = fixed["tasks"]

    # Fix 1: Resolve gpio_b peripheral conflict (spi_driver vs i2c_driver).
    # Move i2c_driver to alternative GPIO port determined by sqlite3 query.
    i2c_uses = tasks["i2c_driver"]["uses"]
    tasks["i2c_driver"]["uses"] = [
        i2c1_gpio if p == "gpio_b" else p for p in i2c_uses
    ]

    # Fix 2: Replace nonexistent dma2 with correct DMA controller
    # determined by sqlite3 query of chip_reference.db.
    crypto_uses = tasks["crypto"]["uses"]
    tasks["crypto"]["uses"] = [
        hash_dma if p == "dma2" else p for p in crypto_uses
    ]

    # Fix 3: Remove nonexistent hash_driver from crypto task-slots.
    tasks["crypto"]["task-slots"] = [
        s for s in tasks["crypto"].get("task-slots", [])
        if s != "hash_driver"
    ]

    # Fix 4: Add eth_irq to net's notifications to match interrupt mapping.
    net_notifs = list(tasks["net"]["notifications"])
    if "eth_irq" not in net_notifs:
        net_notifs.append("eth_irq")
        tasks["net"]["notifications"] = net_notifs

    # Fix 5: Break sys_monitor <-> logger cycle by removing the
    # back-edge (logger -> sys_monitor).
    tasks["logger"]["task-slots"] = [
        s for s in tasks["logger"].get("task-slots", [])
        if s != "sys_monitor"
    ]

    # Fix 6: Resolve priority inversion — sys_monitor (P1) depends on
    # logger (P4). Raise logger to same priority level.
    tasks["logger"]["priority"] = tasks["sys_monitor"]["priority"]

    # Fix 7: Reduce sensor_hub RAM allocation. The build manifest shows
    # actual RAM usage is far below the 262144-byte budget.
    # Use next power-of-2 of actual usage.
    new_ram = next_power_of_2(sensor_ram_actual)
    tasks["sensor_hub"]["max-sizes"]["ram"] = new_ram

    return fixed


def generate_dot_graph(app):
    """Generate Graphviz DOT representation of the task dependency graph."""
    tasks = app.get("tasks", {})
    task_names = set(tasks.keys())
    lines = ["digraph hubris_tasks {"]
    lines.append("    rankdir=LR;")
    lines.append("    node [shape=box, style=filled, fillcolor=lightblue];")
    lines.append("")

    # Add nodes with priority labels
    for tname in sorted(tasks):
        prio = tasks[tname].get("priority", 255)
        lines.append(f'    {tname} [label="{tname}\\nP{prio}"];')

    lines.append("")

    # Add edges from task-slots
    for tname in sorted(tasks):
        for slot in tasks[tname].get("task-slots", []):
            if slot in task_names:
                lines.append(f"    {tname} -> {slot};")

    lines.append("}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash-dma", required=True,
                        help="DMA controller for hash (from sqlite3)")
    parser.add_argument("--i2c1-gpio", required=True,
                        help="Alternative GPIO for i2c1 (from sqlite3)")
    parser.add_argument("--sensor-ram", type=int, required=True,
                        help="Actual sensor_hub RAM usage (from jq)")
    args = parser.parse_args()

    app, chip = load_configs()
    os.makedirs("/app/output", exist_ok=True)

    # --- Original config analysis ---
    errors, adj = validate(app, chip)
    layout, orig_ram_total, orig_flash_total = compute_memory_layout(app, chip)
    graph = build_task_graph(app, adj)

    # Add memory overflow to validation errors
    if layout["ram_overflow"]:
        errors.append({
            "error_type": "memory_overflow",
            "description": (
                "Total RAM allocation with MPU alignment exceeds "
                "chip RAM capacity (512 KB)"
            ),
            "affected_tasks": sorted(app.get("tasks", {}).keys()),
        })
    if layout["flash_overflow"]:
        errors.append({
            "error_type": "memory_overflow",
            "description": (
                "Total flash allocation with MPU alignment exceeds "
                "chip flash capacity"
            ),
            "affected_tasks": sorted(app.get("tasks", {}).keys()),
        })

    # --- Generate fixed configuration ---
    fixed = generate_fixed_config(
        app, args.hash_dma, args.i2c1_gpio, args.sensor_ram
    )
    fixed_layout, fixed_ram_total, fixed_flash_total = compute_memory_layout(
        fixed, chip
    )

    # --- Generate DOT graph for fixed config ---
    dot_content = generate_dot_graph(fixed)

    # --- Generate optimization report ---
    ram_capacity = chip["memory"]["ram"]["size"]
    report = {
        "original_ram_used": orig_ram_total,
        "fixed_ram_used": fixed_ram_total,
        "ram_capacity": ram_capacity,
        "original_overflow": layout["ram_overflow"],
        "fixed_overflow": fixed_layout["ram_overflow"],
        "fixes_applied": [
            {
                "error_type": "peripheral_conflict",
                "description": (
                    f"Moved i2c_driver from gpio_b to {args.i2c1_gpio} "
                    f"to resolve conflict with spi_driver"
                ),
                "justification": (
                    f"sqlite3 query of chip_reference.db pin_assignments table "
                    f"confirmed i2c1 has alternative pins on {args.i2c1_gpio} "
                    f"port, avoiding shared gpio_b with spi1"
                ),
            },
            {
                "error_type": "nonexistent_peripheral",
                "description": (
                    f"Changed crypto DMA from dma2 to {args.hash_dma}"
                ),
                "justification": (
                    f"sqlite3 query of chip_reference.db dma_channels table "
                    f"confirmed hash peripheral is wired to {args.hash_dma}, "
                    f"and dma2 is not available in chip.toml"
                ),
            },
            {
                "error_type": "nonexistent_task_reference",
                "description": (
                    "Removed hash_driver from crypto task-slots"
                ),
                "justification": (
                    "hash_driver task does not exist in the configuration; "
                    "crypto accesses hash peripheral directly via memory-mapped "
                    "registers, not through a separate driver task"
                ),
            },
            {
                "error_type": "interrupt_notification_mismatch",
                "description": (
                    "Added eth_irq to net task notifications list"
                ),
                "justification": (
                    "net task maps eth_irq interrupt but did not declare "
                    "eth_irq in its notifications list; the kernel requires "
                    "the notification name to be declared for interrupt routing"
                ),
            },
            {
                "error_type": "circular_dependency",
                "description": (
                    "Removed sys_monitor from logger task-slots, "
                    "breaking bidirectional dependency cycle"
                ),
                "justification": (
                    "sys_monitor -> logger (for logging) is the primary "
                    "dependency; logger -> sys_monitor back-edge creates "
                    "deadlock risk in synchronous IPC and is not required "
                    "for logger's core functionality"
                ),
            },
            {
                "error_type": "priority_inversion",
                "description": (
                    "Changed logger priority from 4 to 1 to match "
                    "sys_monitor priority level"
                ),
                "justification": (
                    "sys_monitor (P1) sends synchronous IPC to logger (P4), "
                    "blocking at lower priority; raising logger to P1 "
                    "eliminates priority inversion while maintaining correct "
                    "scheduling for log message handling"
                ),
            },
            {
                "error_type": "memory_overflow",
                "description": (
                    f"Reduced sensor_hub RAM from 262144 to "
                    f"{next_power_of_2(args.sensor_ram)} bytes"
                ),
                "justification": (
                    f"jq query of build_manifest.json shows sensor_hub actual "
                    f"RAM usage is {args.sensor_ram} bytes; the 262144-byte "
                    f"allocation was for raw DMA ring buffers but streaming "
                    f"mode requires only ~25KB; MPU alignment of 256KB caused "
                    f"160KB+ wasted gap triggering RAM overflow"
                ),
            },
        ],
    }

    # --- Write all outputs ---
    with open("/app/output/validation_errors.json", "w") as f:
        json.dump(errors, f, indent=2)

    with open("/app/output/memory_layout.json", "w") as f:
        json.dump(layout, f, indent=2)

    with open("/app/output/task_graph.json", "w") as f:
        json.dump(graph, f, indent=2)

    with open("/app/output/fixed_app.toml", "wb") as f:
        tomli_w.dump(fixed, f)

    with open("/app/output/task_graph.dot", "w") as f:
        f.write(dot_content)

    with open("/app/output/optimization_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Analysis complete. Found {len(errors)} issues.")
    print(f"Original RAM: {orig_ram_total} / {ram_capacity} "
          f"(overflow: {layout['ram_overflow']})")
    print(f"Fixed RAM: {fixed_ram_total} / {ram_capacity} "
          f"(overflow: {fixed_layout['ram_overflow']})")


if __name__ == "__main__":
    main()
