#!/usr/bin/env python3

"""
Solver for EPANET network expansion optimization.
Selects minimum-cost pipe diameters for new pipes to maintain >= 20 psi
at all junctions across a 24-hour extended period simulation.
"""

import subprocess
import json
import re
import os
import sys


def read_json(path):
    with open(path) as f:
        return json.load(f)


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)


def add_to_section(inp_text, section_name, new_lines):
    """Insert new_lines right after a section header and its comment lines."""
    pattern = re.compile(
        rf"(\[{section_name}\]\s*\n(?:;[^\n]*\n)*)", re.IGNORECASE
    )
    m = pattern.search(inp_text)
    if m:
        pos = m.end()
        return inp_text[:pos] + new_lines + inp_text[pos:]
    return inp_text


def set_report_section(inp_text):
    """Replace [REPORT] section to output all nodes."""
    new_report = (
        "[REPORT]\n"
        " Status             No\n"
        " Summary            No\n"
        " Page               0\n"
        " NODES              ALL\n\n"
    )
    return re.sub(
        r"\[REPORT\].*?(?=\[|\Z)", new_report, inp_text,
        flags=re.DOTALL | re.IGNORECASE,
    )


def create_expanded_inp(base_text, spec, diameters):
    """Create an expanded network .inp file with the given pipe diameters."""
    text = base_text

    # Add new junctions
    junc_lines = ""
    for j in spec["new_junctions"]:
        junc_lines += (
            f" {j['id']:<16}\t{j['elevation_ft']:<12}\t"
            f"{j['demand_gpm']:<12}\t{j['pattern']}\t;\n"
        )
    text = add_to_section(text, "JUNCTIONS", junc_lines)

    # Add new pipes with selected diameters
    pipe_lines = ""
    for i, p in enumerate(spec["new_pipes"]):
        d = diameters[i]
        pipe_lines += (
            f" {p['id']:<16}\t{p['from']:<16}\t{p['to']:<16}\t"
            f"{p['length_ft']:<12}\t{d:<12}\t{p['roughness']:<12}\t"
            f"0\tOpen\t;\n"
        )
    text = add_to_section(text, "PIPES", pipe_lines)

    # Add coordinates for new junctions
    coord_lines = ""
    coord_map = {
        "41": (30.00, -20.00),
        "42": (30.00, -50.00),
        "43": (50.00, -20.00),
        "44": (50.00, -50.00),
    }
    for j in spec["new_junctions"]:
        jid = j["id"]
        if jid in coord_map:
            x, y = coord_map[jid]
            coord_lines += f" {jid:<16}\t{x:<16.2f}\t{y:<16.2f}\n"
    text = add_to_section(text, "COORDINATES", coord_lines)

    # Ensure report settings
    text = set_report_section(text)
    return text


def run_epanet(inp_path, rpt_path):
    """Run EPANET. Returns exit code."""
    r = subprocess.run(
        ["/usr/local/bin/runepanet", inp_path, rpt_path],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode


def parse_node_pressures(rpt_path):
    """Parse node pressures from EPANET report.
    Returns {timestep: {node_id: pressure}}.
    """
    with open(rpt_path) as f:
        content = f.read()

    results = {}
    blocks = re.split(r"(?=Node Results)", content)

    for block in blocks:
        if "Node Results" not in block:
            continue
        lines = block.split("\n")

        tm = re.search(r"at\s+(\d+:\d+)", lines[0])
        timestep = tm.group(1) if tm else "0:00"

        # Find pressure column index in the header
        pressure_col = None
        for line in lines:
            stripped = line.strip()
            if "Pressure" in stripped:
                parts = stripped.split()
                if parts[0] != "Node":
                    for k, fld in enumerate(parts):
                        if fld == "Pressure":
                            pressure_col = k
                            break
                    break

        if pressure_col is None:
            continue

        sep_count = 0
        reading = False
        node_data = {}
        for line in lines:
            if "----" in line:
                sep_count += 1
                if sep_count >= 2:
                    reading = True
                continue
            if reading:
                stripped = line.strip()
                if not stripped:
                    break
                parts = stripped.split()
                if len(parts) >= pressure_col + 2:
                    try:
                        node_data[parts[0]] = float(parts[pressure_col + 1])
                    except ValueError:
                        continue

        results[timestep] = node_data

    return results


def get_junction_ids(inp_text):
    """Extract junction IDs from inp text."""
    junctions = []
    in_sec = False
    for line in inp_text.split("\n"):
        if re.match(r"\[JUNCTIONS\]", line, re.IGNORECASE):
            in_sec = True
            continue
        if in_sec and line.strip().startswith("["):
            break
        if in_sec:
            stripped = line.split(";")[0].strip()
            if stripped:
                parts = stripped.split()
                if parts:
                    junctions.append(parts[0])
    return junctions


def find_min_pressure(pressures, junction_ids):
    """Find minimum pressure across all timesteps for given junctions."""
    min_p = float("inf")
    min_node = None
    min_time = None
    for ts, node_ps in pressures.items():
        for nid, p in node_ps.items():
            if nid in junction_ids and p < min_p:
                min_p = p
                min_node = nid
                min_time = ts
    return min_p, min_node, min_time


def compute_cost(diameters, pipes, catalog):
    total = 0
    for d, p in zip(diameters, pipes):
        total += catalog["unit_cost_per_ft"][str(d)] * p["length_ft"]
    return total


def main():
    spec = read_json("/app/expansion_spec.json")
    catalog = read_json("/app/pipe_catalog.json")
    base_network = read_file("/app/network.inp")

    pipes = spec["new_pipes"]
    budget = spec["constraints"]["max_budget_usd"]
    min_p_req = spec["constraints"]["min_pressure_psi"]
    avail = sorted(catalog["available_diameters_in"])

    # ---- Step 1: Baseline analysis ----
    print("Running baseline analysis...")
    baseline_text = set_report_section(base_network)
    write_file("/tmp/baseline.inp", baseline_text)
    ret = run_epanet("/tmp/baseline.inp", "/tmp/baseline.rpt")
    if ret >= 100:
        print(f"Baseline EPANET failed (code {ret})")
        sys.exit(1)

    baseline_pressures = parse_node_pressures("/tmp/baseline.rpt")
    base_juncs = get_junction_ids(base_network)
    bl_min_p, bl_min_node, bl_min_time = find_min_pressure(
        baseline_pressures, set(base_juncs)
    )
    print(f"Baseline min pressure: {bl_min_p:.2f} psi at node {bl_min_node} ({bl_min_time})")

    # ---- Step 2: Greedy diameter optimisation ----
    print("Optimising pipe diameters...")
    all_new_junc_ids = [j["id"] for j in spec["new_junctions"]]
    all_junction_ids = set(base_juncs + all_new_junc_ids)

    # Start with smallest diameters
    dia_idx = [0] * len(pipes)
    current_diams = [avail[i] for i in dia_idx]
    best = None

    for iteration in range(60):
        cost = compute_cost(current_diams, pipes, catalog)
        if cost > budget:
            print(f"  Budget exceeded at ${cost:,.0f}, cannot go larger")
            break

        expanded_text = create_expanded_inp(base_network, spec, current_diams)
        write_file("/tmp/opt.inp", expanded_text)
        ret = run_epanet("/tmp/opt.inp", "/tmp/opt.rpt")

        if ret >= 100:
            # EPANET error - upgrade all pipes
            print(f"  EPANET error (code {ret}), upgrading all pipes")
            for k in range(len(dia_idx)):
                if dia_idx[k] < len(avail) - 1:
                    dia_idx[k] += 1
            current_diams = [avail[i] for i in dia_idx]
            continue

        pressures = parse_node_pressures("/tmp/opt.rpt")
        mp, mn, mt = find_min_pressure(pressures, all_junction_ids)
        print(
            f"  Iter {iteration}: diams={current_diams}, cost=${cost:,.0f}, "
            f"min_p={mp:.2f} at {mn} ({mt})"
        )

        if mp >= min_p_req:
            best = {
                "diameters": list(current_diams),
                "cost": cost,
                "min_p": mp,
                "min_node": mn,
                "min_time": mt,
            }
            print(f"  Valid solution found!")
            break

        # Determine which branch to upgrade
        # Branch 1: pipes 0,1 serve nodes 41,42
        # Branch 2: pipes 2,3 serve nodes 43,44
        worst_new = {}
        for ts, nps in pressures.items():
            for nid in all_new_junc_ids:
                if nid in nps:
                    if nid not in worst_new or nps[nid] < worst_new[nid]:
                        worst_new[nid] = nps[nid]

        b1_min = min(worst_new.get("41", 999), worst_new.get("42", 999))
        b2_min = min(worst_new.get("43", 999), worst_new.get("44", 999))

        if mn not in all_new_junc_ids:
            # Existing node violated: upgrade upstream pipes (both branches)
            upgraded = False
            for k in [0, 2]:
                if dia_idx[k] < len(avail) - 1:
                    dia_idx[k] += 1
                    upgraded = True
            if not upgraded:
                for k in [1, 3]:
                    if dia_idx[k] < len(avail) - 1:
                        dia_idx[k] += 1
        elif b1_min <= b2_min:
            # Branch 1 worse
            if dia_idx[0] < len(avail) - 1:
                dia_idx[0] += 1
            elif dia_idx[1] < len(avail) - 1:
                dia_idx[1] += 1
            else:
                # Branch 1 maxed, try branch 2
                if dia_idx[2] < len(avail) - 1:
                    dia_idx[2] += 1
                elif dia_idx[3] < len(avail) - 1:
                    dia_idx[3] += 1
        else:
            # Branch 2 worse
            if dia_idx[2] < len(avail) - 1:
                dia_idx[2] += 1
            elif dia_idx[3] < len(avail) - 1:
                dia_idx[3] += 1
            else:
                if dia_idx[0] < len(avail) - 1:
                    dia_idx[0] += 1
                elif dia_idx[1] < len(avail) - 1:
                    dia_idx[1] += 1

        current_diams = [avail[i] for i in dia_idx]

    # Fallback: try all-max diameters
    if best is None:
        print("  Trying maximum diameters as fallback...")
        max_diams = [avail[-1]] * len(pipes)
        expanded_text = create_expanded_inp(base_network, spec, max_diams)
        write_file("/tmp/opt.inp", expanded_text)
        ret = run_epanet("/tmp/opt.inp", "/tmp/opt.rpt")
        if ret < 100:
            pressures = parse_node_pressures("/tmp/opt.rpt")
            mp, mn, mt = find_min_pressure(pressures, all_junction_ids)
            best = {
                "diameters": max_diams,
                "cost": compute_cost(max_diams, pipes, catalog),
                "min_p": mp,
                "min_node": mn,
                "min_time": mt,
            }

    if best is None:
        print("ERROR: Could not find a valid solution")
        sys.exit(1)

    # ---- Step 3: Cost reduction pass ----
    print("Attempting cost reduction...")
    diams = list(best["diameters"])
    for i in range(len(diams)):
        cur_idx = avail.index(diams[i])
        if cur_idx == 0:
            continue
        trial = list(diams)
        trial[i] = avail[cur_idx - 1]
        trial_cost = compute_cost(trial, pipes, catalog)
        if trial_cost > budget:
            continue
        expanded_text = create_expanded_inp(base_network, spec, trial)
        write_file("/tmp/opt.inp", expanded_text)
        ret = run_epanet("/tmp/opt.inp", "/tmp/opt.rpt")
        if ret < 100:
            pressures = parse_node_pressures("/tmp/opt.rpt")
            mp, mn, mt = find_min_pressure(pressures, all_junction_ids)
            if mp >= min_p_req:
                diams[i] = trial[i]
                best = {
                    "diameters": list(diams),
                    "cost": trial_cost,
                    "min_p": mp,
                    "min_node": mn,
                    "min_time": mt,
                }
                print(f"  Downgraded pipe {i} -> {trial[i]}\" (cost=${trial_cost:,.0f})")

    # ---- Step 4: Write outputs ----
    print("Writing outputs...")

    # Write expanded network
    final_text = create_expanded_inp(base_network, spec, best["diameters"])
    write_file("/app/expanded_network.inp", final_text)

    # Extract critical timestep hour
    min_time_str = best["min_time"]
    critical_hr = int(min_time_str.split(":")[0])

    # Build pipe_diameters map
    diam_map = {}
    for i, p in enumerate(pipes):
        diam_map[p["id"]] = best["diameters"][i]

    analysis = {
        "baseline_min_pressure_psi": round(bl_min_p, 2),
        "baseline_min_pressure_node": bl_min_node,
        "expanded_min_pressure_psi": round(best["min_p"], 2),
        "expanded_min_pressure_node": best["min_node"],
        "pipe_diameters": diam_map,
        "total_cost_usd": best["cost"],
        "critical_timestep_hr": critical_hr,
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"Done. Cost=${best['cost']:,.0f}, min_p={best['min_p']:.2f} psi")


if __name__ == "__main__":
    main()
