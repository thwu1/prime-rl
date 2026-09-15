#!/usr/bin/env python3
"""
Liberty (.lib) timing library anomaly detector.

Parses a Liberty file and applies physical design rule checks to
identify data integrity anomalies.

"""

import json
import re
import sys


def find_matching_brace(text, start):
    """Find the position after the closing brace that matches the opening at start-1."""
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
    """Parse a Liberty file and extract cell-level information."""
    with open(filepath) as f:
        content = f.read()

    # Strip comments
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    content = re.sub(r'//.*', '', content)

    cells = {}
    for m in re.finditer(r'cell\s*\(\s*(\w+)\s*\)\s*\{', content):
        cell_name = m.group(1)
        cell_body = content[m.end():find_matching_brace(content, m.end()) - 1]
        cells[cell_name] = _parse_cell(cell_name, cell_body)
    return cells


def _parse_cell(name, body):
    cell = {"name": name, "pins": {}}

    m = re.search(r'area\s*:\s*([\-\d.eE+]+)\s*;', body)
    cell["area"] = float(m.group(1)) if m else None

    m = re.search(r'cell_leakage_power\s*:\s*([\-\d.eE+]+)\s*;', body)
    cell["leakage_power"] = float(m.group(1)) if m else None

    cell["is_sequential"] = bool(re.search(r'\bff\s*\(', body))

    for pm in re.finditer(r'pin\s*\(\s*(\w+)\s*\)\s*\{', body):
        pin_name = pm.group(1)
        pin_body = body[pm.end():find_matching_brace(body, pm.end()) - 1]
        cell["pins"][pin_name] = _parse_pin(pin_name, pin_body)

    return cell


def _parse_pin(name, body):
    pin = {"name": name, "timing_groups": []}

    m = re.search(r'\bdirection\s*:\s*(\w+)\s*;', body)
    pin["direction"] = m.group(1) if m else None

    m = re.search(r'(?<!\w)capacitance\s*:\s*([\-\d.eE+]+)\s*;', body)
    pin["capacitance"] = float(m.group(1)) if m else None

    m = re.search(r'function\s*:\s*"([^"]+)"\s*;', body)
    pin["function"] = m.group(1) if m else None

    m = re.search(r'max_capacitance\s*:\s*([\-\d.eE+]+)\s*;', body)
    pin["max_capacitance"] = float(m.group(1)) if m else None

    pin["is_clock"] = bool(re.search(r'clock\s*:\s*true', body))

    for tm in re.finditer(r'timing\s*\(\s*\)\s*\{', body):
        tg_body = body[tm.end():find_matching_brace(body, tm.end()) - 1]
        pin["timing_groups"].append(_parse_timing_group(tg_body))

    return pin


def _parse_timing_group(body):
    tg = {"tables": {}}

    m = re.search(r'related_pin\s*:\s*"(\w+)"\s*;', body)
    tg["related_pin"] = m.group(1) if m else None

    m = re.search(r'timing_type\s*:\s*(\w+)\s*;', body)
    tg["timing_type"] = m.group(1) if m else None

    m = re.search(r'timing_sense\s*:\s*(\w+)\s*;', body)
    tg["timing_sense"] = m.group(1) if m else None

    # Extract all named table groups: cell_rise(...), rise_constraint(...), etc.
    for tm in re.finditer(r'(\w+)\s*\(\s*\w+\s*\)\s*\{', body):
        table_name = tm.group(1)
        tbl_body = body[tm.end():find_matching_brace(body, tm.end()) - 1]
        values_m = re.search(r'values\s*\((.*?)\)\s*;', tbl_body, re.DOTALL)
        if values_m:
            rows = re.findall(r'"([^"]+)"', values_m.group(1))
            tg["tables"][table_name] = [
                [float(x.strip()) for x in row.split(',')]
                for row in rows
            ]

    return tg


def detect_anomalies(cells):
    anomalies = []

    # Collect all input capacitances for statistical comparison
    input_caps = []
    for cell in cells.values():
        for pin in cell["pins"].values():
            if pin["direction"] == "input" and pin["capacitance"] is not None:
                input_caps.append(pin["capacitance"])
    median_cap = sorted(input_caps)[len(input_caps) // 2] if input_caps else 0.015

    for cell_name, cell in cells.items():

        # ── Check 1: zero or negative area ──
        if cell["area"] is not None and cell["area"] <= 0:
            anomalies.append({
                "cell_name": cell_name,
                "anomaly_type": "zero_area",
                "pin": None,
                "severity": "error",
                "description": (
                    f"Cell area is {cell['area']}. "
                    f"Physical cells must have positive area."
                ),
            })

        # ── Check 2: negative leakage power ──
        if cell["leakage_power"] is not None and cell["leakage_power"] < 0:
            anomalies.append({
                "cell_name": cell_name,
                "anomaly_type": "negative_leakage_power",
                "pin": None,
                "severity": "error",
                "description": (
                    f"Cell leakage power is {cell['leakage_power']} nW. "
                    f"Leakage power cannot be negative."
                ),
            })

        # ── Check 3: excessive input capacitance ──
        for pname, pin in cell["pins"].items():
            if (
                pin["direction"] == "input"
                and pin["capacitance"] is not None
                and pin["capacitance"] > median_cap * 20
            ):
                anomalies.append({
                    "cell_name": cell_name,
                    "anomaly_type": "excessive_input_capacitance",
                    "pin": pname,
                    "severity": "error",
                    "description": (
                        f"Input capacitance {pin['capacitance']} pF on pin {pname} "
                        f"is {pin['capacitance'] / median_cap:.0f}x the library median "
                        f"({median_cap:.4f} pF)."
                    ),
                })

        # ── Check 4: negative delays and non-monotonic delay tables ──
        for pname, pin in cell["pins"].items():
            for tg in pin["timing_groups"]:
                related = tg["related_pin"] or "?"
                for tbl_name in ("cell_rise", "cell_fall"):
                    table = tg["tables"].get(tbl_name)
                    if table is None:
                        continue
                    for ri, row in enumerate(table):
                        for ci, val in enumerate(row):
                            if val < 0:
                                anomalies.append({
                                    "cell_name": cell_name,
                                    "anomaly_type": "negative_delay",
                                    "pin": pname,
                                    "severity": "error",
                                    "description": (
                                        f"Negative {tbl_name} value {val} at "
                                        f"index [{ri}][{ci}] in arc "
                                        f"{related}->{pname}."
                                    ),
                                })
                        for ci in range(1, len(row)):
                            if row[ci] < row[ci - 1]:
                                anomalies.append({
                                    "cell_name": cell_name,
                                    "anomaly_type": "non_monotonic_delay",
                                    "pin": pname,
                                    "severity": "error",
                                    "description": (
                                        f"Non-monotonic {tbl_name} in arc "
                                        f"{related}->{pname}: row {ri} col {ci} "
                                        f"({row[ci]}) < col {ci-1} ({row[ci-1]}). "
                                        f"Delay must increase with output capacitance."
                                    ),
                                })

        # ── Check 5: missing timing arcs (combinational multi-input cells) ──
        if not cell["is_sequential"]:
            inp_pins = [
                p for p, info in cell["pins"].items()
                if info["direction"] == "input"
            ]
            out_pins = [
                p for p, info in cell["pins"].items()
                if info["direction"] == "output"
            ]
            if len(inp_pins) >= 2:
                for op in out_pins:
                    related = set()
                    for tg in cell["pins"][op]["timing_groups"]:
                        if tg["related_pin"]:
                            related.add(tg["related_pin"])
                    for ip in inp_pins:
                        if ip not in related:
                            anomalies.append({
                                "cell_name": cell_name,
                                "anomaly_type": "missing_timing_arc",
                                "pin": f"{ip}->{op}",
                                "severity": "error",
                                "description": (
                                    f"No timing arc from input {ip} to output "
                                    f"{op}. All inputs of a combinational cell "
                                    f"must have arcs to each output."
                                ),
                            })

        # ── Check 6: setup/hold constraint violation (sequential cells) ──
        if cell["is_sequential"]:
            for pname, pin in cell["pins"].items():
                setup_vals, hold_vals = [], []
                for tg in pin["timing_groups"]:
                    tt = tg.get("timing_type", "")
                    for tbl_name in ("rise_constraint", "fall_constraint"):
                        table = tg["tables"].get(tbl_name)
                        if table is None:
                            continue
                        for row in table:
                            if tt == "setup_rising":
                                setup_vals.extend(row)
                            elif tt == "hold_rising":
                                hold_vals.extend(row)
                if setup_vals and hold_vals:
                    avg_setup = sum(setup_vals) / len(setup_vals)
                    avg_hold = sum(hold_vals) / len(hold_vals)
                    if avg_hold > avg_setup:
                        anomalies.append({
                            "cell_name": cell_name,
                            "anomaly_type": "setup_hold_violation",
                            "pin": pname,
                            "severity": "error",
                            "description": (
                                f"Average hold constraint ({avg_hold:.3f} ns) "
                                f"exceeds average setup constraint "
                                f"({avg_setup:.3f} ns) on pin {pname}. "
                                f"Hold should not exceed setup for a "
                                f"well-designed flip-flop."
                            ),
                        })

    return anomalies


def main():
    cells = parse_liberty("/app/tech_library.lib")
    anomalies = detect_anomalies(cells)

    with open("/app/anomaly_report.json", "w") as f:
        json.dump(anomalies, f, indent=2)

    print(f"Detected {len(anomalies)} anomalies across {len(cells)} cells:")
    for a in anomalies:
        print(f"  [{a['severity']}] {a['cell_name']}: {a['anomaly_type']}")
        print(f"         {a['description']}")


if __name__ == "__main__":
    main()
