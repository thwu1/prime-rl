"""
Tests for SBML simulator conformance.

"""

import csv
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import pytest


CASES = ["case_001", "case_002", "case_003", "case_004"]
MODELS_DIR = "/app/models"
SIMULATOR = "/app/sbml_sim.py"
TESTS_DIR = "/tests"


def parse_settings(settings_path):
    """Parse an SBML test suite settings file."""
    settings = {}
    with open(settings_path) as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            key, val = line.split(":", 1)
            settings[key.strip()] = val.strip()
    return settings


def parse_csv(csv_path):
    """Parse a CSV results file, returning header and list of rows (floats)."""
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        header = [h.strip() for h in header]
        rows = []
        for row in reader:
            if not any(row):
                continue
            rows.append([float(v.strip()) for v in row])
    return header, rows


def check_tolerance(expected_rows, actual_rows, abs_tol, rel_tol, header):
    """Check SBML tolerance: |C_ij - U_ij| <= (T_a + T_r * |C_ij|)"""
    errors = []
    assert len(expected_rows) == len(actual_rows), (
        f"Row count mismatch: expected {len(expected_rows)}, got {len(actual_rows)}"
    )
    for i, (exp_row, act_row) in enumerate(zip(expected_rows, actual_rows)):
        assert len(exp_row) == len(act_row), (
            f"Column count mismatch at row {i}: expected {len(exp_row)}, got {len(act_row)}"
        )
        for j, (c_ij, u_ij) in enumerate(zip(exp_row, act_row)):
            tol = abs_tol + rel_tol * abs(c_ij)
            diff = abs(c_ij - u_ij)
            if diff > tol:
                col_name = header[j] if j < len(header) else f"col{j}"
                errors.append(
                    f"Row {i}, column '{col_name}': |{c_ij} - {u_ij}| = {diff:.6e} > tol {tol:.6e}"
                )
    return errors


def run_simulator(case_name):
    """Run the simulator on a given case and return the output CSV path."""
    case_dir = os.path.join(MODELS_DIR, case_name)
    model_path = os.path.join(case_dir, "model.xml")
    settings_path = os.path.join(case_dir, "settings.txt")
    output_path = os.path.join("/app", f"output_{case_name}.csv")

    assert os.path.exists(SIMULATOR), f"Simulator not found at {SIMULATOR}"
    assert os.path.exists(model_path), f"Model not found at {model_path}"
    assert os.path.exists(settings_path), f"Settings not found at {settings_path}"

    result = subprocess.run(
        ["python3", SIMULATOR, model_path, settings_path, output_path],
        capture_output=True,
        text=True,
        timeout=120,
        cwd="/app",
    )

    assert result.returncode == 0, (
        f"Simulator failed for {case_name}:\n"
        f"stdout: {result.stdout[-500:]}\n"
        f"stderr: {result.stderr[-500:]}"
    )
    assert os.path.exists(output_path), f"Output CSV not created at {output_path}"
    return output_path


def get_expected_csv_path(case_name):
    """Get path to expected CSV in the tests directory."""
    return os.path.join(TESTS_DIR, f"{case_name}_expected.csv")


class TestSimulatorExists:
    def test_simulator_file_exists(self):
        assert os.path.exists(SIMULATOR), f"{SIMULATOR} does not exist"

    def test_simulator_is_python(self):
        with open(SIMULATOR) as f:
            content = f.read(500)
        assert "import" in content or "def " in content or "class " in content, (
            "sbml_sim.py does not appear to be a Python file"
        )


class TestCase001CyclicReactions:
    """Cyclic reaction network A->B->C->D->A with MathML kinetic laws."""

    def test_runs_successfully(self):
        run_simulator("case_001")

    def test_output_header(self):
        output_path = run_simulator("case_001")
        header, _ = parse_csv(output_path)
        assert header == ["time", "A", "B", "C", "D"], f"Wrong header: {header}"

    def test_row_count(self):
        output_path = run_simulator("case_001")
        _, rows = parse_csv(output_path)
        assert len(rows) == 51, f"Expected 51 rows, got {len(rows)}"

    def test_tolerance(self):
        output_path = run_simulator("case_001")
        settings = parse_settings(os.path.join(MODELS_DIR, "case_001", "settings.txt"))
        abs_tol = float(settings["absolute"])
        rel_tol = float(settings["relative"])
        exp_header, exp_rows = parse_csv(get_expected_csv_path("case_001"))
        act_header, act_rows = parse_csv(output_path)
        errors = check_tolerance(exp_rows, act_rows, abs_tol, rel_tol, exp_header)
        assert not errors, (
            f"Tolerance failures for case_001:\n" + "\n".join(errors[:10])
        )

    def test_mass_conservation(self):
        """A+B+C+D should be conserved (=1.5) throughout."""
        output_path = run_simulator("case_001")
        _, rows = parse_csv(output_path)
        for i, row in enumerate(rows):
            total = sum(row[1:])  # skip time column
            assert abs(total - 1.5) < 0.01, (
                f"Mass not conserved at row {i}: A+B+C+D = {total}, expected 1.5"
            )


class TestCase002RulesInteraction:
    """Rate rules + assignment rule: S1 decays, S2 accumulates, S3 = S_total-S1-S2."""

    def test_runs_successfully(self):
        run_simulator("case_002")

    def test_output_header(self):
        output_path = run_simulator("case_002")
        header, _ = parse_csv(output_path)
        assert header == ["time", "S1", "S2", "S3"], f"Wrong header: {header}"

    def test_row_count(self):
        output_path = run_simulator("case_002")
        _, rows = parse_csv(output_path)
        assert len(rows) == 76, f"Expected 76 rows, got {len(rows)}"

    def test_tolerance(self):
        output_path = run_simulator("case_002")
        settings = parse_settings(os.path.join(MODELS_DIR, "case_002", "settings.txt"))
        abs_tol = float(settings["absolute"])
        rel_tol = float(settings["relative"])
        exp_header, exp_rows = parse_csv(get_expected_csv_path("case_002"))
        act_header, act_rows = parse_csv(output_path)
        errors = check_tolerance(exp_rows, act_rows, abs_tol, rel_tol, exp_header)
        assert not errors, (
            f"Tolerance failures for case_002:\n" + "\n".join(errors[:10])
        )

    def test_conservation(self):
        """S1 + S2 + S3 should equal S_total (10) at all times."""
        output_path = run_simulator("case_002")
        _, rows = parse_csv(output_path)
        for i, row in enumerate(rows):
            total = row[1] + row[2] + row[3]
            assert abs(total - 10.0) < 0.01, (
                f"Conservation violated at row {i}: S1+S2+S3={total}"
            )


class TestCase003EventSawtooth:
    """Exponential decay with event-driven reset creating a sawtooth pattern."""

    def test_runs_successfully(self):
        run_simulator("case_003")

    def test_output_header(self):
        output_path = run_simulator("case_003")
        header, _ = parse_csv(output_path)
        assert header == ["time", "X"], f"Wrong header: {header}"

    def test_row_count(self):
        output_path = run_simulator("case_003")
        _, rows = parse_csv(output_path)
        assert len(rows) == 101, f"Expected 101 rows, got {len(rows)}"

    def test_tolerance(self):
        output_path = run_simulator("case_003")
        settings = parse_settings(os.path.join(MODELS_DIR, "case_003", "settings.txt"))
        abs_tol = float(settings["absolute"])
        rel_tol = float(settings["relative"])
        exp_header, exp_rows = parse_csv(get_expected_csv_path("case_003"))
        act_header, act_rows = parse_csv(output_path)
        errors = check_tolerance(exp_rows, act_rows, abs_tol, rel_tol, exp_header)
        assert not errors, (
            f"Tolerance failures for case_003:\n" + "\n".join(errors[:10])
        )

    def test_sawtooth_resets(self):
        """X should reset (jump up) at least twice during the simulation."""
        output_path = run_simulator("case_003")
        _, rows = parse_csv(output_path)
        resets = 0
        for i in range(1, len(rows)):
            if rows[i][1] > rows[i - 1][1] + 1.0:
                resets += 1
        assert resets >= 2, (
            f"Expected at least 2 reset events, found {resets}"
        )

    def test_x_stays_above_threshold(self):
        """X should never drop significantly below 5.0 (event fires at 5.0)."""
        output_path = run_simulator("case_003")
        _, rows = parse_csv(output_path)
        for i, row in enumerate(rows):
            assert row[1] >= 4.5, (
                f"X dropped to {row[1]} at row {i}, should stay >= 5.0 (threshold)"
            )


class TestCase004VariableCompartment:
    """Variable compartment size with hasOnlySubstanceUnits=true and concentration output."""

    def test_runs_successfully(self):
        run_simulator("case_004")

    def test_output_header(self):
        output_path = run_simulator("case_004")
        header, _ = parse_csv(output_path)
        assert header == ["time", "S", "C", "P"], f"Wrong header: {header}"

    def test_row_count(self):
        output_path = run_simulator("case_004")
        _, rows = parse_csv(output_path)
        assert len(rows) == 51, f"Expected 51 rows, got {len(rows)}"

    def test_tolerance(self):
        output_path = run_simulator("case_004")
        settings = parse_settings(os.path.join(MODELS_DIR, "case_004", "settings.txt"))
        abs_tol = float(settings["absolute"])
        rel_tol = float(settings["relative"])
        exp_header, exp_rows = parse_csv(get_expected_csv_path("case_004"))
        act_header, act_rows = parse_csv(output_path)
        errors = check_tolerance(exp_rows, act_rows, abs_tol, rel_tol, exp_header)
        assert not errors, (
            f"Tolerance failures for case_004:\n" + "\n".join(errors[:10])
        )

    def test_concentration_decreasing_rate(self):
        """Concentration S should increase but at a decreasing rate (concave)."""
        output_path = run_simulator("case_004")
        _, rows = parse_csv(output_path)
        # Check that S increases monotonically
        for i in range(1, len(rows)):
            assert rows[i][1] >= rows[i - 1][1] - 1e-6, (
                f"S decreased at row {i}: {rows[i][1]} < {rows[i - 1][1]}"
            )
        # Check concavity: differences should decrease
        diffs = [rows[i + 1][1] - rows[i][1] for i in range(len(rows) - 1)]
        for i in range(1, len(diffs)):
            assert diffs[i] <= diffs[i - 1] + 1e-6, (
                f"S growth rate increased at step {i}: not concave"
            )

    def test_compartment_linear_growth(self):
        """Compartment C should grow linearly from 1.0 to 2.0."""
        output_path = run_simulator("case_004")
        _, rows = parse_csv(output_path)
        assert abs(rows[0][2] - 1.0) < 1e-6, f"C(0) = {rows[0][2]}, expected 1.0"
        assert abs(rows[-1][2] - 2.0) < 1e-6, f"C(10) = {rows[-1][2]}, expected 2.0"

    def test_p_equals_amount_times_volume(self):
        """P = amount_S * C, and S(concentration) = amount_S / C, so P = S * C^2."""
        output_path = run_simulator("case_004")
        _, rows = parse_csv(output_path)
        for i, row in enumerate(rows):
            t = row[0]
            s_conc = row[1]
            c_size = row[2]
            p_val = row[3]
            # amount_S = s_conc * c_size
            amount_s = s_conc * c_size
            # P should be amount_S * C = s_conc * c_size * c_size
            expected_p = amount_s * c_size
            assert abs(p_val - expected_p) < 0.01, (
                f"Row {i}: P={p_val}, expected amount*C = {expected_p}"
            )


class TestConformanceReport:
    """Check that conformance_report.json is generated correctly."""

    def test_report_exists(self):
        # Run all cases first
        for case in CASES:
            run_simulator(case)
        assert os.path.exists("/app/conformance_report.json"), (
            "conformance_report.json not found at /app/conformance_report.json"
        )

    def test_report_content(self):
        for case in CASES:
            run_simulator(case)
        with open("/app/conformance_report.json") as f:
            report = json.load(f)
        for case in CASES:
            assert case in report, f"{case} missing from conformance report"
            assert report[case] == "pass", (
                f"{case} not marked as 'pass' in report: {report[case]}"
            )


class TestDynamicPerturbation:
    """Run the simulator on dynamically modified models to verify genuine computation.

    These tests create model variants at test time with altered initial conditions
    and parameters. A simulator that hardcodes outputs will fail these tests.
    """

    SBML_NS = "http://www.sbml.org/sbml/level3/version2/core"

    @pytest.fixture
    def perturbed_case_001(self, tmp_path):
        """Create a modified case_001 with A(0)=2.5, C(0)=1.0 (total mass 3.5)."""
        model_path = os.path.join(MODELS_DIR, "case_001", "model.xml")
        tree = ET.parse(model_path)
        root = tree.getroot()

        ns = {"s": self.SBML_NS}
        for species in root.findall(".//s:species", ns):
            sid = species.get("id")
            if sid == "A":
                species.set("initialAmount", "2.5")
            elif sid == "C":
                species.set("initialAmount", "1.0")

        mod_dir = str(tmp_path / "perturbed_001")
        os.makedirs(mod_dir, exist_ok=True)
        mod_model = os.path.join(mod_dir, "model.xml")
        tree.write(mod_model, xml_declaration=True, encoding="UTF-8")

        shutil.copy(
            os.path.join(MODELS_DIR, "case_001", "settings.txt"),
            os.path.join(mod_dir, "settings.txt"),
        )
        output_path = os.path.join(mod_dir, "output.csv")
        return mod_dir, mod_model, os.path.join(mod_dir, "settings.txt"), output_path

    @pytest.fixture
    def perturbed_case_001_rates(self, tmp_path):
        """Create case_001 with doubled rate constants."""
        model_path = os.path.join(MODELS_DIR, "case_001", "model.xml")
        tree = ET.parse(model_path)
        root = tree.getroot()

        ns = {"s": self.SBML_NS}
        for param in root.findall(".//s:parameter", ns):
            val = float(param.get("value", "0"))
            param.set("value", str(val * 2.0))

        mod_dir = str(tmp_path / "perturbed_001_rates")
        os.makedirs(mod_dir, exist_ok=True)
        mod_model = os.path.join(mod_dir, "model.xml")
        tree.write(mod_model, xml_declaration=True, encoding="UTF-8")

        shutil.copy(
            os.path.join(MODELS_DIR, "case_001", "settings.txt"),
            os.path.join(mod_dir, "settings.txt"),
        )
        output_path = os.path.join(mod_dir, "output.csv")
        return mod_dir, mod_model, os.path.join(mod_dir, "settings.txt"), output_path

    def _run_on(self, model_path, settings_path, output_path):
        """Run the simulator on arbitrary model and settings."""
        assert os.path.exists(SIMULATOR), f"Simulator not found at {SIMULATOR}"
        result = subprocess.run(
            ["python3", SIMULATOR, model_path, settings_path, output_path],
            capture_output=True,
            text=True,
            timeout=120,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Simulator failed on perturbed model:\n"
            f"stdout: {result.stdout[-500:]}\n"
            f"stderr: {result.stderr[-500:]}"
        )
        return output_path

    def test_perturbed_initial_conditions(self, perturbed_case_001):
        """A(0)=2.5, B(0)=0, C(0)=1.0, D(0)=0 must appear in first row."""
        _, model, settings, output = perturbed_case_001
        self._run_on(model, settings, output)
        _, rows = parse_csv(output)
        assert abs(rows[0][1] - 2.5) < 1e-6, f"A(0) should be 2.5, got {rows[0][1]}"
        assert abs(rows[0][2]) < 1e-6, f"B(0) should be 0, got {rows[0][2]}"
        assert abs(rows[0][3] - 1.0) < 1e-6, f"C(0) should be 1.0, got {rows[0][3]}"
        assert abs(rows[0][4]) < 1e-6, f"D(0) should be 0, got {rows[0][4]}"

    def test_perturbed_mass_conservation(self, perturbed_case_001):
        """A+B+C+D should conserve at 3.5 (=2.5+0+1.0+0) throughout."""
        _, model, settings, output = perturbed_case_001
        self._run_on(model, settings, output)
        _, rows = parse_csv(output)
        expected_total = 3.5
        for i, row in enumerate(rows):
            total = sum(row[1:])
            assert abs(total - expected_total) < 0.02, (
                f"Mass not conserved at row {i}: sum={total:.6f}, expected {expected_total}"
            )

    def test_perturbed_differs_from_original(self, perturbed_case_001):
        """Perturbed output must differ significantly from original case_001."""
        _, model, settings, output = perturbed_case_001
        self._run_on(model, settings, output)
        _, mod_rows = parse_csv(output)

        orig_output = run_simulator("case_001")
        _, orig_rows = parse_csv(orig_output)

        large_diffs = 0
        for orig_row, mod_row in zip(orig_rows, mod_rows):
            for o, m in zip(orig_row[1:], mod_row[1:]):
                if abs(o - m) > 0.05:
                    large_diffs += 1
        assert large_diffs > 20, (
            f"Perturbed model output too similar to original: only {large_diffs} "
            f"values differ by more than 0.05"
        )

    def test_perturbed_rates_changes_dynamics(self, perturbed_case_001_rates):
        """Doubling rate constants should change the transient dynamics."""
        _, model, settings, output = perturbed_case_001_rates
        self._run_on(model, settings, output)
        _, fast_rows = parse_csv(output)

        orig_output = run_simulator("case_001")
        _, orig_rows = parse_csv(orig_output)

        # Mass should still be conserved at 1.5 (same initial conditions)
        for i, row in enumerate(fast_rows):
            total = sum(row[1:])
            assert abs(total - 1.5) < 0.02, (
                f"Mass not conserved with doubled rates at row {i}: sum={total:.6f}"
            )

        # But transient values should differ (faster approach to steady state)
        mid = len(orig_rows) // 4  # early in simulation where transient differs most
        diffs_at_mid = sum(
            abs(o - f) for o, f in zip(orig_rows[mid][1:], fast_rows[mid][1:])
        )
        assert diffs_at_mid > 0.05, (
            f"Doubled rate constants didn't change transient dynamics at t={orig_rows[mid][0]}: "
            f"total difference = {diffs_at_mid:.6f}"
        )

    def test_perturbed_row_count(self, perturbed_case_001):
        """Perturbed model should produce the same number of rows (same settings)."""
        _, model, settings, output = perturbed_case_001
        self._run_on(model, settings, output)
        _, rows = parse_csv(output)
        assert len(rows) == 51, f"Expected 51 rows, got {len(rows)}"
