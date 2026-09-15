
"""
Verification tests for PHREEQC water blending CCPP analysis.

Independently computes reference values by running PHREEQC and compares
against the agent's /app/results.json.
"""

import json
import os
import csv
import subprocess
import tempfile
import pytest

PHREEQC_BIN = os.environ.get("PHREEQC_BIN", "")
PHREEQC_DB = os.environ.get("PHREEQC_DB", "")


def build_solution_block(source_id, source, sol_num):
    """Build a PHREEQC SOLUTION block from source data."""
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
    """Build complete PHREEQC input for one scenario at one temperature."""
    blend = scenario["blend"]
    source_ids = sorted(blend.keys())

    lines = []

    # SELECTED_OUTPUT configuration
    lines.append("SELECTED_OUTPUT 1")
    lines.append(f"  -file {sel_file}")
    lines.append("  -reset true")
    lines.append("  -simulation true")
    lines.append("  -state true")
    lines.append("  -pH true")
    lines.append("  -si Calcite")
    lines.append("  -equilibrium_phases Calcite")
    lines.append("")

    # Define source solutions (Simulation 1)
    for i, sid in enumerate(source_ids, 1):
        lines.append(build_solution_block(sid, sources[sid], i))
    lines.append("END")
    lines.append("")

    # Simulation 2: Mix and adjust temperature
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

    # Simulation 3: CCPP closed (calcite only)
    lines.append("USE solution 100")
    lines.append("EQUILIBRIUM_PHASES 1")
    lines.append("  Calcite 0.0 10.0")
    lines.append("END")
    lines.append("")

    # Simulation 4: CCPP open (calcite + atmospheric CO2)
    lines.append("USE solution 100")
    lines.append("EQUILIBRIUM_PHASES 2")
    lines.append("  Calcite 0.0 10.0")
    lines.append("  CO2(g) -3.5 10.0")
    lines.append("END")

    return "\n".join(lines)


def run_phreeqc_scenario(sources, scenario, temp):
    """Run PHREEQC for one scenario/temperature and return computed values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sel_file = os.path.join(tmpdir, "sel.out")
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
            raise RuntimeError(
                f"PHREEQC failed for {scenario['id']} at {temp}C: {result.stderr}"
            )

        # Parse selected output (tab-delimited)
        with open(sel_file, "r") as f:
            reader = csv.reader(f, delimiter="\t")
            rows = list(reader)

        headers = [h.strip() for h in rows[0]]
        data_rows = rows[1:]

        # Find column indices
        col_map = {}
        for i, h in enumerate(headers):
            col_map[h.lower()] = i

        sim_idx = col_map.get("sim", col_map.get("simulation", None))
        ph_idx = col_map.get("ph", None)

        # Find SI column for Calcite
        si_idx = None
        for k, v in col_map.items():
            if "si" in k and "calcite" in k:
                si_idx = v
                break

        # Find delta Calcite column
        d_idx = None
        for k, v in col_map.items():
            if k.startswith("d_") and "calcite" in k:
                d_idx = v
                break

        assert sim_idx is not None, f"Could not find sim column in headers: {headers}"
        assert ph_idx is not None, f"Could not find pH column in headers: {headers}"
        assert si_idx is not None, f"Could not find SI Calcite column in headers: {headers}"
        assert d_idx is not None, f"Could not find d_Calcite column in headers: {headers}"

        # Group rows by simulation number
        sims = {}
        for row in data_rows:
            if len(row) <= sim_idx:
                continue
            try:
                sim = int(float(row[sim_idx].strip()))
            except (ValueError, IndexError):
                continue
            sims.setdefault(sim, []).append(row)

        max_sim = max(sims.keys())

        # mix/temp row is max_sim - 2, CCPP_closed is max_sim - 1, CCPP_open is max_sim
        mix_row = sims[max_sim - 2][-1]
        closed_row = sims[max_sim - 1][-1]
        open_row = sims[max_sim][-1]

        pH_val = float(mix_row[ph_idx].strip())
        si_val = float(mix_row[si_idx].strip())
        ccpp_closed = float(closed_row[d_idx].strip()) * 1000  # mol to mmol
        ccpp_open = float(open_row[d_idx].strip()) * 1000  # mol to mmol

        return {
            "pH": pH_val,
            "calcite_si": si_val,
            "ccpp_closed_mmol_per_kgw": ccpp_closed,
            "ccpp_open_mmol_per_kgw": ccpp_open,
        }


def compute_all_reference_values():
    """Compute reference values for all scenarios and temperatures."""
    with open("/app/sources.json") as f:
        sources_data = json.load(f)
    with open("/app/scenarios.json") as f:
        scenarios_data = json.load(f)

    sources = sources_data["sources"]
    scenarios = scenarios_data["scenarios"]
    temperatures = scenarios_data["temperatures_c"]

    refs = {}
    for scenario in scenarios:
        refs[scenario["id"]] = {}
        for temp in temperatures:
            vals = run_phreeqc_scenario(sources, scenario, temp)
            refs[scenario["id"]][str(temp)] = vals

    return refs


@pytest.fixture(scope="module")
def reference_values():
    """Compute reference values once for all tests."""
    assert PHREEQC_BIN, "PHREEQC_BIN environment variable not set"
    assert PHREEQC_DB, "PHREEQC_DB environment variable not set"
    assert os.path.isfile(PHREEQC_BIN), f"PHREEQC binary not found: {PHREEQC_BIN}"
    assert os.path.isfile(PHREEQC_DB), f"PHREEQC database not found: {PHREEQC_DB}"
    return compute_all_reference_values()


@pytest.fixture(scope="module")
def agent_results():
    """Load the agent's results."""
    results_path = "/app/results.json"
    assert os.path.isfile(results_path), "Agent did not produce /app/results.json"
    with open(results_path) as f:
        return json.load(f)


def test_results_file_exists():
    """Check that the results file exists."""
    assert os.path.isfile("/app/results.json"), "/app/results.json not found"


def test_results_schema(agent_results):
    """Verify the structure of results.json."""
    assert "scenarios" in agent_results, "Missing 'scenarios' key"
    scenarios = agent_results["scenarios"]
    assert len(scenarios) == 3, f"Expected 3 scenarios, got {len(scenarios)}"

    expected_ids = ["pure_limestone", "gw_blend", "tri_blend"]
    actual_ids = [s["scenario_id"] for s in scenarios]
    assert actual_ids == expected_ids, f"Scenario IDs mismatch: {actual_ids} != {expected_ids}"

    for s in scenarios:
        assert "results_by_temperature" in s, f"Missing results_by_temperature for {s['scenario_id']}"
        temps = s["results_by_temperature"]
        for t in ["5.0", "15.0", "25.0"]:
            assert t in temps, f"Missing temperature {t} for {s['scenario_id']}"
            vals = temps[t]
            for key in ["pH", "calcite_si", "ccpp_closed_mmol_per_kgw", "ccpp_open_mmol_per_kgw"]:
                assert key in vals, f"Missing {key} for {s['scenario_id']} at {t}C"
                assert isinstance(vals[key], (int, float)), f"{key} is not numeric"


def _within_tolerance(actual, expected, abs_tol, rel_tol_pct):
    """Check if actual is within tolerance of expected."""
    diff = abs(actual - expected)
    rel_tol = abs(expected) * rel_tol_pct / 100.0 if expected != 0 else 0
    return diff <= max(abs_tol, rel_tol)


def test_ph_values(agent_results, reference_values):
    """Verify pH values against independently computed references."""
    for scenario in agent_results["scenarios"]:
        sid = scenario["scenario_id"]
        for temp_str, vals in scenario["results_by_temperature"].items():
            ref = reference_values[sid][temp_str]
            diff = abs(vals["pH"] - ref["pH"])
            assert diff <= 0.02, (
                f"pH mismatch for {sid} at {temp_str}C: "
                f"got {vals['pH']}, expected {ref['pH']}, diff={diff:.4f}"
            )


def test_calcite_si_values(agent_results, reference_values):
    """Verify calcite SI values against independently computed references."""
    for scenario in agent_results["scenarios"]:
        sid = scenario["scenario_id"]
        for temp_str, vals in scenario["results_by_temperature"].items():
            ref = reference_values[sid][temp_str]
            diff = abs(vals["calcite_si"] - ref["calcite_si"])
            assert diff <= 0.05, (
                f"Calcite SI mismatch for {sid} at {temp_str}C: "
                f"got {vals['calcite_si']}, expected {ref['calcite_si']}, diff={diff:.4f}"
            )


def test_ccpp_closed_values(agent_results, reference_values):
    """Verify CCPP closed-system values against independently computed references."""
    for scenario in agent_results["scenarios"]:
        sid = scenario["scenario_id"]
        for temp_str, vals in scenario["results_by_temperature"].items():
            ref = reference_values[sid][temp_str]
            actual = vals["ccpp_closed_mmol_per_kgw"]
            expected = ref["ccpp_closed_mmol_per_kgw"]
            assert _within_tolerance(actual, expected, 0.02, 5.0), (
                f"CCPP closed mismatch for {sid} at {temp_str}C: "
                f"got {actual}, expected {expected}"
            )


def test_ccpp_open_values(agent_results, reference_values):
    """Verify CCPP open-system values against independently computed references."""
    for scenario in agent_results["scenarios"]:
        sid = scenario["scenario_id"]
        for temp_str, vals in scenario["results_by_temperature"].items():
            ref = reference_values[sid][temp_str]
            actual = vals["ccpp_open_mmol_per_kgw"]
            expected = ref["ccpp_open_mmol_per_kgw"]
            assert _within_tolerance(actual, expected, 0.02, 5.0), (
                f"CCPP open mismatch for {sid} at {temp_str}C: "
                f"got {actual}, expected {expected}"
            )


def test_physical_consistency(agent_results):
    """Sanity checks on the physical consistency of results."""
    for scenario in agent_results["scenarios"]:
        sid = scenario["scenario_id"]
        temps = scenario["results_by_temperature"]

        for temp_str, vals in temps.items():
            # pH should be in a reasonable range for natural water
            assert 5.0 < vals["pH"] < 10.0, (
                f"pH out of range for {sid} at {temp_str}C: {vals['pH']}"
            )

            # If calcite_si > 0, CCPP_closed should be positive (or near zero)
            if vals["calcite_si"] > 0.1:
                assert vals["ccpp_closed_mmol_per_kgw"] > -0.01, (
                    f"Inconsistency: SI > 0 but CCPP_closed < 0 for {sid} at {temp_str}C"
                )

            # If calcite_si < -0.1, CCPP_closed should be negative (dissolution)
            if vals["calcite_si"] < -0.1:
                assert vals["ccpp_closed_mmol_per_kgw"] < 0.01, (
                    f"Inconsistency: SI < 0 but CCPP_closed > 0 for {sid} at {temp_str}C"
                )

        # Calcite solubility is retrograde: SI should generally increase with temperature
        if "5.0" in temps and "25.0" in temps:
            si_5 = temps["5.0"]["calcite_si"]
            si_25 = temps["25.0"]["calcite_si"]
            # Allow small violations due to activity coefficient changes
            assert si_25 >= si_5 - 0.15, (
                f"Retrograde solubility violation for {sid}: "
                f"SI at 5C={si_5:.3f}, SI at 25C={si_25:.3f}"
            )
