"""
Tests for corrected PHREEQC reactive transport model.

Verifies that the agent diagnosed and fixed the broken drain_model.pqi,
producing results consistent with a reference simulation using the correct
geochemical and transport parameters.

"""
import json
import os
import subprocess
import tempfile

import pytest

# Reference PHREEQC input with the CORRECT parameters.
# This embodies all five fixes the agent must discover:
#   - Alkalinity 150 as CaCO3 in initial porewater
#   - Calcite SI target = 0.0 (equilibrium)
#   - flux flux boundary conditions
#   - dispersivity = 0.05 m
#   - SELECTED_OUTPUT with -totals, -equilibrium_phases
REFERENCE_INPUT_TEMPLATE = """
TITLE Reference simulation - corrected ALD model

SOLUTION 0  AMD Influent
    units   mg/L
    temp    15
    pH      3.0
    pe      4.0
    Ca      150
    Mg      40
    Na      30
    S(6)    600
    Cl      20
    K       5

SOLUTION 1-10  Initial porewater
    units   mg/L
    temp    15
    pH      7.5
    pe      4.0
    Ca      60
    Mg      5
    Na      10
    K       2
    Alkalinity  150 as CaCO3
    S(6)    20
    Cl      10

EQUILIBRIUM_PHASES 1-10
    Calcite    0.0    5.0
    Gypsum     0.0    0.0

SELECTED_OUTPUT
    -file   {output_file}
    -totals  Ca S(6) Mg Na
    -saturation_indices  Calcite Gypsum
    -equilibrium_phases  Calcite

TRANSPORT
    -cells   10
    -shifts  30
    -time_step  3600
    -flow_direction  forward
    -boundary_conditions  flux  flux
    -lengths  0.5
    -dispersivities  0.05

END
"""


def find_phreeqc():
    """Locate a working PHREEQC binary on the system."""
    candidates = [
        "/app/phreeqc3_src/build/phreeqc",
        "/app/phreeqc3_src/build/src/phreeqc",
        "/app/phreeqc3/build/phreeqc",
        "/app/phreeqc3/build/src/phreeqc",
        "/app/build/phreeqc",
        "/app/phreeqc",
        "/usr/local/bin/phreeqc",
        "/app/phreeqc3_src/build/phreeqc3",
        "/app/phreeqc3/build/phreeqc3",
        "/app/phreeqc3_src/build/src/phreeqc3",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    # Broad search fallback
    try:
        result = subprocess.run(
            ["find", "/app", "-maxdepth", "5", "-name", "phreeqc*", "-type", "f"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and os.access(line, os.X_OK):
                return line
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["which", "phreeqc"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


def find_database():
    """Locate phreeqc.dat thermodynamic database."""
    candidates = [
        "/app/phreeqc3_src/database/phreeqc.dat",
        "/app/phreeqc3/database/phreeqc.dat",
        "/app/database/phreeqc.dat",
        "/usr/local/share/doc/phreeqc/database/phreeqc.dat",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    try:
        result = subprocess.run(
            ["find", "/app", "-maxdepth", "5", "-name", "phreeqc.dat", "-type", "f"],
            capture_output=True, text=True, timeout=15,
        )
        for line in result.stdout.strip().split("\n"):
            if line.strip() and os.path.isfile(line.strip()):
                return line.strip()
    except Exception:
        pass
    return None


def parse_selected_output(filepath):
    """Parse a PHREEQC SELECTED_OUTPUT tab-separated file."""
    with open(filepath, "r") as fh:
        lines = fh.readlines()

    header_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            header_idx = i
            break

    headers = [h.strip() for h in lines[header_idx].split("\t")]
    rows = []
    for line in lines[header_idx + 1:]:
        if not line.strip():
            continue
        values = [v.strip() for v in line.split("\t")]
        row = {}
        for h, v in zip(headers, values):
            if not h:
                continue
            try:
                row[h] = float(v)
            except (ValueError, TypeError):
                row[h] = v
        rows.append(row)
    return headers, rows


def get_cell_at_final_shift(rows, cell_num):
    """Return the row for cell_num at the final transport shift."""
    transport = [
        r for r in rows
        if float(r.get("step", 0)) > 0
    ]
    if not transport:
        return None
    max_step = max(r["step"] for r in transport)
    for r in transport:
        if abs(r["step"] - max_step) < 0.5:
            soln = float(r.get("soln", -999))
            if abs(soln - cell_num) < 0.5:
                return r
    return None


def _find_col(headers, exact_name):
    for h in headers:
        if h.strip() == exact_name:
            return h
    return None


def _run_reference_simulation():
    """Run the reference PHREEQC simulation and return parsed data."""
    phreeqc = find_phreeqc()
    assert phreeqc is not None, "PHREEQC binary not found — agent must build it"
    database = find_database()
    assert database is not None, "phreeqc.dat database not found"

    tmpdir = tempfile.mkdtemp()
    ref_tsv = os.path.join(tmpdir, "ref_transport.tsv")
    ref_input = os.path.join(tmpdir, "ref_input.pqi")
    ref_stdout = os.path.join(tmpdir, "ref_output.txt")

    with open(ref_input, "w") as f:
        f.write(REFERENCE_INPUT_TEMPLATE.format(output_file=ref_tsv))

    result = subprocess.run(
        [phreeqc, ref_input, ref_stdout, database],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"Reference PHREEQC simulation failed (rc={result.returncode}).\n"
        f"stderr: {result.stderr[:2000]}"
    )
    assert os.path.isfile(ref_tsv), "Reference SELECTED_OUTPUT file was not created"

    headers, rows = parse_selected_output(ref_tsv)
    cell10 = get_cell_at_final_shift(rows, 10)
    cell1 = get_cell_at_final_shift(rows, 1)
    assert cell10 is not None, "Could not locate cell-10 data in reference output"
    assert cell1 is not None, "Could not locate cell-1 data in reference output"
    return headers, rows, cell10, cell1


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPHREEQCBuild:
    """Verify that PHREEQC was built and is functional."""

    def test_phreeqc_binary_exists(self):
        phreeqc = find_phreeqc()
        assert phreeqc is not None, (
            "No executable PHREEQC binary found under /app"
        )

    def test_database_exists(self):
        db = find_database()
        assert db is not None, "phreeqc.dat thermodynamic database not found"


class TestCorrectedModel:
    """Verify the corrected model file exists and is well-formed."""

    def test_corrected_model_exists(self):
        assert os.path.isfile("/app/corrected_model.pqi"), (
            "/app/corrected_model.pqi not found"
        )

    def test_corrected_model_has_required_keywords(self):
        with open("/app/corrected_model.pqi", "r") as f:
            content = f.read().upper()
        for kw in ["SOLUTION", "EQUILIBRIUM_PHASES", "TRANSPORT", "SELECTED_OUTPUT"]:
            assert kw in content, f"Missing required PHREEQC keyword: {kw}"

    def test_transport_output_exists(self):
        assert os.path.isfile("/app/transport_results.tsv"), (
            "/app/transport_results.tsv not found — corrected simulation was not run"
        )

    def test_transport_output_has_data(self):
        with open("/app/transport_results.tsv", "r") as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) > 10, (
            "transport_results.tsv has too few lines — simulation may have failed"
        )


class TestResultsAccuracy:
    """Verify results.json correctness against independent reference simulation."""

    def test_results_file_exists(self):
        assert os.path.isfile("/app/results.json"), "/app/results.json not found"

    def test_results_has_required_keys(self):
        with open("/app/results.json", "r") as f:
            results = json.load(f)
        required = [
            "effluent_pH",
            "effluent_Ca_mol_kgw",
            "effluent_SO4_mol_kgw",
            "calcite_remaining_cell1",
            "gypsum_si_cell10",
        ]
        for key in required:
            assert key in results, f"Missing key in results.json: {key}"
            assert isinstance(results[key], (int, float)), (
                f"results.json['{key}'] must be numeric, got {type(results[key]).__name__}"
            )

    def test_results_match_reference(self):
        """Run a reference simulation with correct parameters and compare."""
        headers, rows, ref10, ref1 = _run_reference_simulation()

        ca_col = _find_col(headers, "Ca")
        so4_col = _find_col(headers, "S(6)")
        calcite_col = _find_col(headers, "Calcite")
        si_gypsum_col = _find_col(headers, "si_Gypsum")

        assert ca_col is not None, f"Ca column not in reference. Headers: {headers}"
        assert so4_col is not None, f"S(6) column not in reference. Headers: {headers}"
        assert calcite_col is not None, f"Calcite column not in reference. Headers: {headers}"
        assert si_gypsum_col is not None, f"si_Gypsum column not in reference. Headers: {headers}"

        ref_pH = ref10["pH"]
        ref_Ca = ref10[ca_col]
        ref_SO4 = ref10[so4_col]
        ref_calcite = ref1[calcite_col]
        ref_gypsum_si = ref10[si_gypsum_col]

        with open("/app/results.json", "r") as f:
            results = json.load(f)

        # pH tolerance: 0.1 pH unit
        assert abs(results["effluent_pH"] - ref_pH) < 0.1, (
            f"effluent_pH mismatch: got {results['effluent_pH']}, reference {ref_pH}"
        )
        # Ca tolerance: 5% relative
        if abs(ref_Ca) > 1e-10:
            assert abs(results["effluent_Ca_mol_kgw"] - ref_Ca) / abs(ref_Ca) < 0.05, (
                f"effluent_Ca mismatch: got {results['effluent_Ca_mol_kgw']}, reference {ref_Ca}"
            )
        # SO4 tolerance: 5% relative
        if abs(ref_SO4) > 1e-10:
            assert abs(results["effluent_SO4_mol_kgw"] - ref_SO4) / abs(ref_SO4) < 0.05, (
                f"effluent_SO4 mismatch: got {results['effluent_SO4_mol_kgw']}, reference {ref_SO4}"
            )
        # Calcite tolerance: 5% relative
        if abs(ref_calcite) > 1e-10:
            assert abs(results["calcite_remaining_cell1"] - ref_calcite) / abs(ref_calcite) < 0.05, (
                f"calcite_remaining mismatch: got {results['calcite_remaining_cell1']}, reference {ref_calcite}"
            )
        # Gypsum SI tolerance: 0.2 SI units
        assert abs(results["gypsum_si_cell10"] - ref_gypsum_si) < 0.2, (
            f"gypsum_si mismatch: got {results['gypsum_si_cell10']}, reference {ref_gypsum_si}"
        )

    def test_physical_reasonableness(self):
        """Sanity check that results are geochemically plausible."""
        with open("/app/results.json", "r") as f:
            results = json.load(f)

        # Limestone neutralization must raise pH well above acid input of 3.0
        assert results["effluent_pH"] > 5.0, (
            f"Effluent pH {results['effluent_pH']} too low — limestone not neutralizing"
        )
        assert results["effluent_pH"] < 9.0, (
            f"Effluent pH {results['effluent_pH']} unreasonably high"
        )

        # Calcite dissolution elevates dissolved Ca
        assert results["effluent_Ca_mol_kgw"] > 1e-3, (
            f"Ca {results['effluent_Ca_mol_kgw']} mol/kgw too low"
        )
        assert results["effluent_Ca_mol_kgw"] < 0.1, (
            f"Ca {results['effluent_Ca_mol_kgw']} mol/kgw unreasonably high"
        )

        # Sulfate present from acid water
        assert results["effluent_SO4_mol_kgw"] > 1e-4, (
            f"SO4 {results['effluent_SO4_mol_kgw']} mol/kgw too low"
        )
        assert results["effluent_SO4_mol_kgw"] < 0.05, (
            f"SO4 {results['effluent_SO4_mol_kgw']} mol/kgw unreasonably high"
        )

        # Partial calcite consumption after 30 shifts (5 mol initial)
        assert 4.0 < results["calcite_remaining_cell1"] < 5.0, (
            f"Calcite in cell 1 = {results['calcite_remaining_cell1']} mol outside range"
        )

        # Gypsum generally undersaturated to near-saturated
        assert results["gypsum_si_cell10"] < 1.0, (
            f"Gypsum SI {results['gypsum_si_cell10']} unreasonably high"
        )
