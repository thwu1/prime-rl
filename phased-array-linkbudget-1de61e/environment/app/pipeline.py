#!/usr/bin/env python3
"""Phased array antenna analysis pipeline.

Processes scenario files through a beamforming engine and writes
JSON results. Supports batch processing and output verification.
"""

import json
import sys
import os
import glob
import math

from lib.formats import read_s1p, read_coupling_matrix
from beamformer import Beamformer

DATA_DIR = "/app/data"
SCENARIOS_DIR = "/app/scenarios"
OUTPUT_DIR = "/app/output"
REFERENCE_DIR = "/app/reference"

# Per-field verification tolerances used by --verify mode
TOLERANCES = {
    "ideal_weights": 0.02,
    "coupled_weights": 0.05,
    "array_directivity_dBi": 1.0,
    "coupled_directivity_dBi": 1.5,
    "tx_element_impedance_ohms": 2.0,
    "tx_input_impedance_ohms": 2.0,
    "tx_reflection_coefficient_mag": 0.02,
    "tx_vswr": 0.5,
    "tx_mismatch_loss_dB": 0.3,
    "rx_input_impedance_ohms": 2.0,
    "rx_reflection_coefficient_mag": 0.02,
    "rx_vswr": 0.5,
    "rx_mismatch_loss_dB": 0.3,
    "free_space_path_loss_dB": 0.1,
    "received_power_dBm": 3.0,
}


def load_scenario_data(scenario):
    """Load external data files referenced by a scenario.

    Returns (s_data, coupling) where:
      - s_data is the dict from read_s1p()
      - coupling is the list-of-lists from read_coupling_matrix()
    """
    s1p_path = os.path.join(DATA_DIR, scenario["element_data_file"])
    s_data = read_s1p(s1p_path)

    n = scenario["array"]["num_elements"]
    coupling_path = os.path.join(DATA_DIR, "coupling_{}.csv".format(n))
    coupling = read_coupling_matrix(coupling_path)

    return s_data, coupling


def process_scenario(scenario_path):
    """Process a single scenario file and write output JSON."""
    with open(scenario_path) as f:
        scenario = json.load(f)

    name = os.path.splitext(os.path.basename(scenario_path))[0]
    s_data, coupling = load_scenario_data(scenario)

    bf = Beamformer()
    result = bf.analyze(scenario, s_data, coupling)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, "{}.json".format(name))
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    return name, result


def _compare(actual, expected, tol):
    """Compare scalar or list values within tolerance."""
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False, "length mismatch"
        for i, (a, e) in enumerate(zip(actual, expected)):
            if abs(a - e) > tol:
                return False, "[{}]: {:.6f} vs {:.6f} (tol={})".format(i, a, e, tol)
        return True, ""
    else:
        if abs(actual - expected) > tol:
            return False, "{:.6f} vs {:.6f} (tol={})".format(actual, expected, tol)
        return True, ""


def verify_all():
    """Verify all outputs against reference data in REFERENCE_DIR."""
    ref_files = sorted(glob.glob(os.path.join(REFERENCE_DIR, "*.json")))
    all_pass = True

    for ref_path in ref_files:
        name = os.path.splitext(os.path.basename(ref_path))[0]
        out_path = os.path.join(OUTPUT_DIR, "{}.json".format(name))

        if not os.path.exists(out_path):
            print("FAIL {}: output file missing".format(name))
            all_pass = False
            continue

        with open(ref_path) as f:
            ref = json.load(f)
        with open(out_path) as f:
            out = json.load(f)

        scenario_pass = True
        for field, tol in TOLERANCES.items():
            if field not in ref:
                continue
            if field not in out:
                print("  FAIL {}.{}: missing in output".format(name, field))
                scenario_pass = False
                continue
            ok, msg = _compare(out[field], ref[field], tol)
            if not ok:
                print("  FAIL {}.{} {}".format(name, field, msg))
                scenario_pass = False

        status = "PASS" if scenario_pass else "FAIL"
        print("{} {}".format(status, name))
        if not scenario_pass:
            all_pass = False

    return all_pass


def main():
    if len(sys.argv) < 2:
        print("Usage: pipeline.py [--run-all | --verify | <scenario.json>]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "--run-all":
        scenarios = sorted(glob.glob(os.path.join(SCENARIOS_DIR, "*.json")))
        if not scenarios:
            print("No scenario files found in {}".format(SCENARIOS_DIR))
            sys.exit(1)
        for sp in scenarios:
            name, _ = process_scenario(sp)
            print("Processed {}".format(name))

    elif cmd == "--verify":
        scenarios = sorted(glob.glob(os.path.join(SCENARIOS_DIR, "*.json")))
        for sp in scenarios:
            process_scenario(sp)
        if not verify_all():
            sys.exit(1)

    else:
        name, _ = process_scenario(cmd)
        print("Processed {}".format(name))


if __name__ == "__main__":
    main()
