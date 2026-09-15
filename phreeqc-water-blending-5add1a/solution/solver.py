#!/usr/bin/env python3

"""
PHREEQC-based water blending CCPP analysis solver.

Reads water source analyses and blending scenarios, generates PHREEQC input
files, runs them, parses SELECTED_OUTPUT, and writes results.json.
"""

import json
import os
import csv
import subprocess
import sys
import tempfile

PHREEQC_BIN = os.environ["PHREEQC_BIN"]
PHREEQC_DB = os.environ["PHREEQC_DB"]


def build_solution_block(source_id, source, sol_num):
    """Build a PHREEQC SOLUTION input block from source data."""
    lines = [f"SOLUTION {sol_num}  {source_id}"]
    lines.append(f"  temp {source['temp_c']}")
    lines.append(f"  pH {source['pH']}")
    lines.append("  units ppm")
    lines.append(f"  Ca {source['Ca']}")
    lines.append(f"  Mg {source['Mg']}")
    lines.append(f"  Na {source['Na']}")
    lines.append(f"  K {source['K']}")
    lines.append(f"  Cl {source['Cl']} charge")
    lines.append(f"  Alkalinity {source['Alkalinity_as_CaCO3']} as CaCO3")
    lines.append(f"  S(6) {source['S_6']}")
    lines.append(f"  Si {source['Si']}")
    return "\n".join(lines)


def build_phreeqc_input(sources, scenario, temp, sel_file):
    """Build complete PHREEQC input string for one scenario at one temperature."""
    blend = scenario["blend"]
    source_ids = sorted(blend.keys())

    lines = []

    # SELECTED_OUTPUT: capture pH, SI, and equilibrium phase deltas
    lines.append("SELECTED_OUTPUT 1")
    lines.append(f"  -file {sel_file}")
    lines.append("  -reset true")
    lines.append("  -simulation true")
    lines.append("  -state true")
    lines.append("  -pH true")
    lines.append("  -si Calcite")
    lines.append("  -equilibrium_phases Calcite")
    lines.append("")

    # Simulation 1: Define source solutions (initial speciation)
    for i, sid in enumerate(source_ids, 1):
        lines.append(build_solution_block(sid, sources[sid], i))
    lines.append("END")
    lines.append("")

    # Simulation 2: Mix sources and set evaluation temperature
    if len(source_ids) > 1:
        lines.append("MIX 1")
        for i, sid in enumerate(source_ids, 1):
            lines.append(f"  {i} {blend[sid]}")
    else:
        lines.append("USE solution 1")
    lines.append("REACTION_TEMPERATURE 1")
    lines.append(f"  {temp}")
    lines.append("SAVE solution 100")
    lines.append("END")
    lines.append("")

    # Simulation 3: CCPP in closed system (calcite only)
    lines.append("USE solution 100")
    lines.append("EQUILIBRIUM_PHASES 1")
    lines.append("  Calcite 0.0 10.0")
    lines.append("END")
    lines.append("")

    # Simulation 4: CCPP in open system (calcite + atmospheric CO2)
    lines.append("USE solution 100")
    lines.append("EQUILIBRIUM_PHASES 2")
    lines.append("  Calcite 0.0 10.0")
    lines.append("  CO2(g) -3.5 10.0")
    lines.append("END")

    return "\n".join(lines)


def run_and_parse(sources, scenario, temp):
    """Run PHREEQC for one scenario/temperature and parse selected output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sel_file = os.path.join(tmpdir, "selected.out")
        input_file = os.path.join(tmpdir, "input.pqi")
        output_file = os.path.join(tmpdir, "output.pqo")

        input_str = build_phreeqc_input(sources, scenario, temp, sel_file)

        with open(input_file, "w") as f:
            f.write(input_str)

        result = subprocess.run(
            [PHREEQC_BIN, input_file, output_file, PHREEQC_DB],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            print(f"PHREEQC error for {scenario['id']} at {temp}C:", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            if os.path.exists(output_file):
                with open(output_file) as f:
                    tail = f.readlines()[-20:]
                print("Output tail:", file=sys.stderr)
                print("".join(tail), file=sys.stderr)
            sys.exit(1)

        # Parse the tab-delimited selected output file
        with open(sel_file, "r") as f:
            reader = csv.reader(f, delimiter="\t")
            rows = list(reader)

        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]

        # Build column index map
        col_map = {}
        for i, h in enumerate(headers):
            col_map[h.lower()] = i

        # Find column indices
        sim_idx = col_map.get("sim", col_map.get("simulation"))
        ph_idx = col_map.get("ph")

        # SI column for Calcite
        si_idx = None
        for k, v in col_map.items():
            if "si" in k and "calcite" in k:
                si_idx = v
                break

        # Delta Calcite column
        d_idx = None
        for k, v in col_map.items():
            if k.startswith("d_") and "calcite" in k:
                d_idx = v
                break

        if any(idx is None for idx in [sim_idx, ph_idx, si_idx, d_idx]):
            print(f"Column detection failed. Headers: {headers}", file=sys.stderr)
            sys.exit(1)

        # Group rows by simulation number
        sims = {}
        for row in data_rows:
            if len(row) <= max(sim_idx, ph_idx, si_idx, d_idx):
                continue
            try:
                sim = int(float(row[sim_idx].strip()))
            except (ValueError, IndexError):
                continue
            sims.setdefault(sim, []).append(row)

        max_sim = max(sims.keys())

        # Simulation (max-2): mix + temperature -> pH, calcite SI
        # Simulation (max-1): CCPP closed -> d_Calcite
        # Simulation (max): CCPP open -> d_Calcite
        mix_row = sims[max_sim - 2][-1]
        closed_row = sims[max_sim - 1][-1]
        open_row = sims[max_sim][-1]

        pH_val = float(mix_row[ph_idx].strip())
        si_val = float(mix_row[si_idx].strip())
        ccpp_closed = float(closed_row[d_idx].strip()) * 1000  # mol to mmol
        ccpp_open = float(open_row[d_idx].strip()) * 1000  # mol to mmol

        return {
            "pH": round(pH_val, 6),
            "calcite_si": round(si_val, 6),
            "ccpp_closed_mmol_per_kgw": round(ccpp_closed, 6),
            "ccpp_open_mmol_per_kgw": round(ccpp_open, 6),
        }


def main():
    # Load input data
    with open("/app/sources.json") as f:
        sources_data = json.load(f)
    with open("/app/scenarios.json") as f:
        scenarios_data = json.load(f)

    sources = sources_data["sources"]
    scenarios = scenarios_data["scenarios"]
    temperatures = scenarios_data["temperatures_c"]

    results = {"scenarios": []}

    for scenario in scenarios:
        print(f"Processing scenario: {scenario['id']}")
        scenario_result = {
            "scenario_id": scenario["id"],
            "results_by_temperature": {},
        }

        for temp in temperatures:
            print(f"  Temperature: {temp}C")
            vals = run_and_parse(sources, scenario, temp)
            scenario_result["results_by_temperature"][str(temp)] = vals
            print(f"    pH={vals['pH']:.4f}, SI={vals['calcite_si']:.4f}, "
                  f"CCPP_closed={vals['ccpp_closed_mmol_per_kgw']:.4f}, "
                  f"CCPP_open={vals['ccpp_open_mmol_per_kgw']:.4f}")

        results["scenarios"].append(scenario_result)

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\nResults written to /app/results.json")


if __name__ == "__main__":
    main()
