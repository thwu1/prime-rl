#!/usr/bin/env python3
"""
Parse VCD (Value Change Dump) waveform output from Icarus Verilog simulation.
Extracts cycle-by-cycle tmpA/tmpC register traces from the CORX multiply engine.

"""

import re
import json
import sys


def parse_vcd_file(filename):
    """Parse a VCD file produced by Icarus Verilog.

    Returns:
        signal_map: dict  identifier -> {name, width}
        timeline:   list of (timestamp, {identifier: value})
    """
    signal_map = {}       # identifier -> {name, width}
    current_scope = []

    with open(filename) as f:
        content = f.read()

    # ---------- split header / data ----------
    marker = "$enddefinitions $end"
    idx = content.find(marker)
    if idx < 0:
        raise ValueError("Missing $enddefinitions in VCD")
    header = content[:idx]
    data   = content[idx + len(marker):]

    # ---------- parse header ----------
    for line in header.split("\n"):
        line = line.strip()
        m = re.match(r"\$scope\s+module\s+(\S+)\s+\$end", line)
        if m:
            current_scope.append(m.group(1))
            continue
        if re.match(r"\$upscope\s+\$end", line):
            if current_scope:
                current_scope.pop()
            continue
        m = re.match(
            r"\$var\s+\w+\s+(\d+)\s+(\S+)\s+(\S+)(?:\s+\[.*?\])?\s+\$end",
            line,
        )
        if m:
            width, ident, name = m.groups()
            full = ".".join(current_scope + [name])
            signal_map[ident] = {"name": full, "width": int(width)}

    # ---------- parse data ----------
    timeline = []
    current_time = 0
    batch = {}
    in_dumpvars = False

    for line in data.split("\n"):
        line = line.strip()
        if not line:
            continue

        # --- control keywords ---
        if line == "$dumpvars":
            in_dumpvars = True
            continue
        if line == "$end":
            if in_dumpvars:
                in_dumpvars = False
            continue
        if line.startswith("$"):
            continue

        # --- timestamp ---
        if line.startswith("#"):
            if batch:
                timeline.append((current_time, dict(batch)))
                batch = {}
            current_time = int(line[1:])
            continue

        # --- value change: multi-bit ---
        if line[0] in "bB":
            parts = line.split()
            if len(parts) >= 2:
                val_str, ident = parts[0], parts[1]
                cleaned = val_str[1:].replace("x", "0").replace("X", "0") \
                                     .replace("z", "0").replace("Z", "0")
                batch[ident] = int(cleaned, 2) if cleaned else 0
            continue

        # --- value change: single-bit ---
        if line[0] in "01xXzZ":
            val_char = line[0]
            ident = line[1:]
            batch[ident] = int(val_char) if val_char in "01" else 0
            continue

    if batch:
        timeline.append((current_time, dict(batch)))

    return signal_map, timeline


def _find_id(signal_map, *patterns):
    """Find the first signal whose full name matches any pattern (substring)."""
    for ident, info in signal_map.items():
        name = info["name"]
        for pat in patterns:
            if pat in name:
                return ident
    return None


def extract_corx_trace(vcd_path):
    """Extract CORX multiply trace from VCD file.

    Returns dict:
        trace   — list of 17 {tmpA, tmpC} dicts
        product — {high, low}
    """
    signal_map, timeline = parse_vcd_file(vcd_path)

    # Locate signal identifiers inside the DUT hierarchy
    tmpA_id  = _find_id(signal_map, "dut.tmpA", ".tmpA")
    tmpC_id  = _find_id(signal_map, "dut.tmpC", ".tmpC")
    state_id = _find_id(signal_map, "dut.state", ".state")
    clk_id   = _find_id(signal_map, ".clk", "clk")
    rh_id    = _find_id(signal_map, "dut.result_high", "result_high")
    rl_id    = _find_id(signal_map, "dut.result_low", "result_low")

    if not all([tmpA_id, tmpC_id, state_id, clk_id]):
        avail = [(k, v["name"]) for k, v in signal_map.items()]
        raise ValueError(f"Cannot find required signals. Available: {avail}")

    # Walk the timeline, tracking current signal values
    cur = {}          # ident -> value
    prev_clk = 0
    trace = []
    recording = False

    S_LOOP = 2
    S_DONE = 3

    for _ts, changes in timeline:
        cur.update(changes)
        clk_now = cur.get(clk_id, 0)

        if clk_now == 1 and prev_clk == 0:          # rising edge
            st = cur.get(state_id, 0)
            if st == S_LOOP:
                recording = True
                trace.append({
                    "tmpA": cur.get(tmpA_id, 0),
                    "tmpC": cur.get(tmpC_id, 0),
                })
            elif st == S_DONE and recording:
                trace.append({
                    "tmpA": cur.get(tmpA_id, 0),
                    "tmpC": cur.get(tmpC_id, 0),
                })
                recording = False

        prev_clk = cur.get(clk_id, prev_clk)

    product = {
        "high": cur.get(rh_id, 0),
        "low":  cur.get(rl_id, 0),
    }

    return {"trace": trace, "product": product}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: parse_vcd.py <vcd_file> [output.json]")
        sys.exit(1)
    result = extract_corx_trace(sys.argv[1])
    out = json.dumps(result, indent=2)
    if len(sys.argv) >= 3:
        with open(sys.argv[2], "w") as f:
            f.write(out)
    else:
        print(out)
