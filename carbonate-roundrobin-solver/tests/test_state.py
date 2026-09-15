
import sys
import os
import json
import math
import csv
import subprocess
import tempfile
import pytest
import numpy as np

sys.path.insert(0, "/app")
import carbonate

import PyCO2SYS as pyco2


# --- Helper: get PyCO2SYS reference result ---
def pyco2_ref(par1, par2, par1_type, par2_type, temperature=25.0, salinity=35.0,
              pressure=0.0, total_silicate=0.0, total_phosphate=0.0):
    """Get reference values from PyCO2SYS."""
    r = pyco2.sys(
        par1=par1, par2=par2, par1_type=par1_type, par2_type=par2_type,
        temperature=temperature, salinity=salinity, pressure=pressure,
        total_silicate=total_silicate, total_phosphate=total_phosphate,
        opt_k_carbonic=10, opt_k_bisulfate=1, opt_k_fluoride=1,
        opt_total_borate=2, opt_pH_scale=1,
    )
    return {
        "TA": float(r["alkalinity"]),
        "DIC": float(r["dic"]),
        "pH": float(r["pH_total"]),
        "pCO2": float(r["pCO2"]),
        "fCO2": float(r["fCO2"]),
        "CO3": float(r["carbonate"]),
        "HCO3": float(r["bicarbonate"]),
        "CO2aq": float(r["aqueous_CO2"]),
    }


# --- Helper: compare results ---
def assert_close(result, ref, rtol=1e-4, atol_pH=1e-6):
    """Assert that solver result matches reference."""
    for key in ["TA", "DIC", "pCO2", "fCO2", "CO3", "HCO3", "CO2aq"]:
        val = result[key]
        rval = ref[key]
        if abs(rval) > 1e-10:
            rel_err = abs(val - rval) / abs(rval)
            assert rel_err < rtol, (
                f"{key}: solver={val}, ref={rval}, rel_err={rel_err:.2e} > {rtol}"
            )
        else:
            assert abs(val - rval) < 1e-10, (
                f"{key}: solver={val}, ref={rval}, abs_diff={abs(val-rval):.2e}"
            )
    assert abs(result["pH"] - ref["pH"]) < atol_pH, (
        f"pH: solver={result['pH']}, ref={ref['pH']}, "
        f"diff={abs(result['pH'] - ref['pH']):.2e} > {atol_pH}"
    )


# ===========================================================================
# TEST 1: Golden values - surface ocean conditions
# ===========================================================================
class TestGoldenSurface:
    """Compare solver outputs against PyCO2SYS golden values at P=0."""

    def test_standard_25C_35S(self):
        """T=25C, S=35, P=0, TA=2300, DIC=2100."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=25.0, salinity=35.0, pressure=0.0)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=25.0, salinity=35.0, pressure=0.0)
        assert_close(result, ref)

    def test_warm_tropical(self):
        """T=28C, S=36, P=0, TA=2280, DIC=2050."""
        ref = pyco2_ref(2280, 2050, 1, 2, temperature=28.0, salinity=36.0, pressure=0.0)
        result = carbonate.solve(2280, 2050, 1, 2, temperature=28.0, salinity=36.0, pressure=0.0)
        assert_close(result, ref)

    def test_low_salinity(self):
        """T=20C, S=20, P=0, TA=2200, DIC=2100."""
        ref = pyco2_ref(2200, 2100, 1, 2, temperature=20.0, salinity=20.0, pressure=0.0)
        result = carbonate.solve(2200, 2100, 1, 2, temperature=20.0, salinity=20.0, pressure=0.0)
        assert_close(result, ref)

    def test_high_co2(self):
        """Low TA/DIC ratio -> high CO2. T=25, S=35, P=0."""
        ref = pyco2_ref(2100, 2100, 1, 2, temperature=25.0, salinity=35.0, pressure=0.0)
        result = carbonate.solve(2100, 2100, 1, 2, temperature=25.0, salinity=35.0, pressure=0.0)
        assert_close(result, ref)

    def test_cold_surface(self):
        """T=2C, S=33, P=0, TA=2350, DIC=2200."""
        ref = pyco2_ref(2350, 2200, 1, 2, temperature=2.0, salinity=33.0, pressure=0.0)
        result = carbonate.solve(2350, 2200, 1, 2, temperature=2.0, salinity=33.0, pressure=0.0)
        assert_close(result, ref)


# ===========================================================================
# TEST 2: Golden values - pressurized (deep ocean) conditions
# ===========================================================================
class TestGoldenPressure:
    """Compare solver outputs at non-zero pressure."""

    def test_deep_cold(self):
        """T=2C, S=34.5, P=2000, TA=2350, DIC=2200."""
        ref = pyco2_ref(2350, 2200, 1, 2, temperature=2.0, salinity=34.5, pressure=2000.0)
        result = carbonate.solve(2350, 2200, 1, 2, temperature=2.0, salinity=34.5, pressure=2000.0)
        assert_close(result, ref)

    def test_mid_depth(self):
        """T=10C, S=35, P=500, TA=2300, DIC=2150."""
        ref = pyco2_ref(2300, 2150, 1, 2, temperature=10.0, salinity=35.0, pressure=500.0)
        result = carbonate.solve(2300, 2150, 1, 2, temperature=10.0, salinity=35.0, pressure=500.0)
        assert_close(result, ref)

    def test_pressure_100(self):
        """T=15C, S=35, P=100."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=15.0, salinity=35.0, pressure=100.0)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=15.0, salinity=35.0, pressure=100.0)
        assert_close(result, ref)

    def test_pressure_1000(self):
        """T=5C, S=35, P=1000."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=5.0, salinity=35.0, pressure=1000.0)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=5.0, salinity=35.0, pressure=1000.0)
        assert_close(result, ref)

    @pytest.mark.parametrize("pressure", [100.0, 500.0, 1000.0, 2000.0])
    def test_pressure_sweep(self, pressure):
        """Pressured results must match PyCO2SYS across pressure range."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=10.0, salinity=35.0, pressure=pressure)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=10.0, salinity=35.0, pressure=pressure)
        assert_close(result, ref)


# ===========================================================================
# TEST 3: Golden values with nutrients
# ===========================================================================
class TestGoldenNutrients:
    """Compare solver outputs when silicate and phosphate are present."""

    def test_nutrients_standard(self):
        """T=15C, S=33, P=500, Si=50, PO4=2."""
        ref = pyco2_ref(2300, 2150, 1, 2, temperature=15.0, salinity=33.0,
                        pressure=500.0, total_silicate=50.0, total_phosphate=2.0)
        result = carbonate.solve(2300, 2150, 1, 2, temperature=15.0, salinity=33.0,
                                 pressure=500.0, total_silicate=50.0, total_phosphate=2.0)
        assert_close(result, ref)

    def test_silicate_only(self):
        """T=25C, S=35, P=0, Si=50, PO4=0."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=25.0, salinity=35.0,
                        pressure=0.0, total_silicate=50.0, total_phosphate=0.0)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=25.0, salinity=35.0,
                                 pressure=0.0, total_silicate=50.0, total_phosphate=0.0)
        assert_close(result, ref)

    def test_phosphate_only(self):
        """T=25C, S=35, P=0, Si=0, PO4=2."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=25.0, salinity=35.0,
                        pressure=0.0, total_silicate=0.0, total_phosphate=2.0)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=25.0, salinity=35.0,
                                 pressure=0.0, total_silicate=0.0, total_phosphate=2.0)
        assert_close(result, ref)

    def test_nutrients_deep(self):
        """T=2C, S=35, P=2000, Si=40, PO4=1.5."""
        ref = pyco2_ref(2350, 2250, 1, 2, temperature=2.0, salinity=35.0,
                        pressure=2000.0, total_silicate=40.0, total_phosphate=1.5)
        result = carbonate.solve(2350, 2250, 1, 2, temperature=2.0, salinity=35.0,
                                 pressure=2000.0, total_silicate=40.0, total_phosphate=1.5)
        assert_close(result, ref)


# ===========================================================================
# TEST 4: Different input pair types against PyCO2SYS
# ===========================================================================
class TestInputPairTypes:
    """Test different input pair types match PyCO2SYS."""

    def _get_base_ref(self):
        return pyco2_ref(2300, 2100, 1, 2, temperature=25.0, salinity=35.0, pressure=0.0)

    def test_ta_ph(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["TA"], base["pH"], 1, 3)
        result = carbonate.solve(base["TA"], base["pH"], 1, 3)
        assert_close(result, ref)

    def test_ta_pco2(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["TA"], base["pCO2"], 1, 4)
        result = carbonate.solve(base["TA"], base["pCO2"], 1, 4)
        assert_close(result, ref)

    def test_ta_co3(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["TA"], base["CO3"], 1, 6)
        result = carbonate.solve(base["TA"], base["CO3"], 1, 6)
        assert_close(result, ref)

    def test_ta_hco3(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["TA"], base["HCO3"], 1, 7)
        result = carbonate.solve(base["TA"], base["HCO3"], 1, 7)
        assert_close(result, ref)

    def test_dic_ph(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["DIC"], base["pH"], 2, 3)
        result = carbonate.solve(base["DIC"], base["pH"], 2, 3)
        assert_close(result, ref)

    def test_dic_pco2(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["DIC"], base["pCO2"], 2, 4)
        result = carbonate.solve(base["DIC"], base["pCO2"], 2, 4)
        assert_close(result, ref)

    def test_dic_co3(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["DIC"], base["CO3"], 2, 6)
        result = carbonate.solve(base["DIC"], base["CO3"], 2, 6)
        assert_close(result, ref)

    def test_ph_pco2(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["pH"], base["pCO2"], 3, 4)
        result = carbonate.solve(base["pH"], base["pCO2"], 3, 4)
        assert_close(result, ref)

    def test_ph_co3(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["pH"], base["CO3"], 3, 6)
        result = carbonate.solve(base["pH"], base["CO3"], 3, 6)
        assert_close(result, ref)

    def test_co3_hco3(self):
        base = self._get_base_ref()
        ref = pyco2_ref(base["CO3"], base["HCO3"], 6, 7)
        result = carbonate.solve(base["CO3"], base["HCO3"], 6, 7)
        assert_close(result, ref)


# ===========================================================================
# TEST 5: Round-robin internal consistency
# ===========================================================================
class TestRoundRobin:
    """Solve from one pair, then re-solve from every valid output pair."""

    TYPE_TO_KEY = {1: "TA", 2: "DIC", 3: "pH", 4: "pCO2", 5: "fCO2", 6: "CO3", 7: "HCO3"}
    INVALID_PAIRS = {(4, 5)}

    def _run_roundrobin(self, temperature, salinity, pressure,
                        total_silicate=0.0, total_phosphate=0.0):
        """Run round-robin from TA+DIC under given conditions."""
        base = carbonate.solve(
            2300, 2100, 1, 2,
            temperature=temperature, salinity=salinity, pressure=pressure,
            total_silicate=total_silicate, total_phosphate=total_phosphate,
        )
        errors = []
        for t1 in range(1, 8):
            for t2 in range(t1 + 1, 8):
                if (t1, t2) in self.INVALID_PAIRS:
                    continue
                p1 = base[self.TYPE_TO_KEY[t1]]
                p2 = base[self.TYPE_TO_KEY[t2]]
                result = carbonate.solve(
                    p1, p2, t1, t2,
                    temperature=temperature, salinity=salinity, pressure=pressure,
                    total_silicate=total_silicate, total_phosphate=total_phosphate,
                )
                for key in base:
                    ref_val = base[key]
                    res_val = result[key]
                    if key == "pH":
                        tol = 1e-8
                    elif key in ("pCO2", "fCO2"):
                        tol = 1e-6
                    else:
                        tol = 1e-6
                    diff = abs(res_val - ref_val)
                    if diff > tol:
                        errors.append(
                            f"pair ({t1},{t2}) key={key}: "
                            f"base={ref_val}, result={res_val}, diff={diff:.2e}"
                        )
        assert len(errors) == 0, (
            f"Round-robin failed with {len(errors)} errors:\n" + "\n".join(errors[:10])
        )

    def test_roundrobin_surface(self):
        self._run_roundrobin(25.0, 35.0, 0.0)

    def test_roundrobin_deep(self):
        self._run_roundrobin(2.0, 34.5, 2000.0)

    def test_roundrobin_nutrients(self):
        self._run_roundrobin(15.0, 33.0, 500.0, total_silicate=30.0, total_phosphate=1.5)


# ===========================================================================
# TEST 6: T/S/P grid
# ===========================================================================
class TestGrid:
    """Test a grid of T, S, P conditions."""

    @pytest.mark.parametrize("temperature", [2.0, 15.0, 25.0])
    @pytest.mark.parametrize("salinity", [20.0, 33.0, 35.0])
    @pytest.mark.parametrize("pressure", [0.0, 500.0, 2000.0])
    def test_grid_ta_dic(self, temperature, salinity, pressure):
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=temperature,
                        salinity=salinity, pressure=pressure)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=temperature,
                                 salinity=salinity, pressure=pressure)
        assert_close(result, ref)


# ===========================================================================
# TEST 7: Fugacity / pCO2 accuracy (sensitive to fugacity factor bugs)
# ===========================================================================
class TestFugacity:
    """Verify pCO2 and fCO2 match reference precisely."""

    @pytest.mark.parametrize("temperature", [2.0, 15.0, 25.0, 28.0])
    def test_pco2_fco2_accuracy(self, temperature):
        """pCO2 and fCO2 must match across temperatures."""
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=temperature, salinity=35.0, pressure=0.0)
        result = carbonate.solve(2300, 2100, 1, 2, temperature=temperature, salinity=35.0, pressure=0.0)
        for key in ["pCO2", "fCO2"]:
            rel_err = abs(result[key] - ref[key]) / abs(ref[key])
            assert rel_err < 1e-4, (
                f"T={temperature}, {key}: solver={result[key]}, ref={ref[key]}, rel_err={rel_err:.2e}"
            )


# ===========================================================================
# TEST 8: Diagnosis file
# ===========================================================================
class TestDiagnosis:
    """Verify diagnosis.json exists and has valid structure."""

    def test_diagnosis_exists(self):
        assert os.path.isfile("/app/diagnosis.json"), "diagnosis.json not found at /app/diagnosis.json"

    def test_diagnosis_valid_json(self):
        with open("/app/diagnosis.json") as f:
            data = json.load(f)
        assert isinstance(data, list), "diagnosis.json must be a JSON array"

    def test_diagnosis_min_entries(self):
        with open("/app/diagnosis.json") as f:
            data = json.load(f)
        assert len(data) >= 3, f"diagnosis.json must have at least 3 entries, found {len(data)}"

    def test_diagnosis_entry_structure(self):
        with open("/app/diagnosis.json") as f:
            data = json.load(f)
        required_keys = {"bug_id", "location", "description", "fix", "conditions_affected"}
        for i, entry in enumerate(data):
            missing = required_keys - set(entry.keys())
            assert not missing, f"Entry {i} missing keys: {missing}"
            for key in required_keys:
                assert isinstance(entry[key], (str, int)), f"Entry {i} key '{key}' must be str or int"


# ===========================================================================
# TEST 9: CLI batch tool
# ===========================================================================
class TestCLITool:
    """Test the co2batch.py CLI tool."""

    def test_cli_exists(self):
        assert os.path.isfile("/app/co2batch.py"), "co2batch.py not found at /app/co2batch.py"

    def test_cli_basic(self):
        """Basic CSV processing with all columns specified."""
        input_csv = "par1,par2,par1_type,par2_type,temperature,salinity,pressure,total_silicate,total_phosphate\n"
        input_csv += "2300,2100,1,2,25.0,35.0,0.0,0.0,0.0\n"
        input_csv += "2280,2050,1,2,28.0,36.0,0.0,0.0,0.0\n"

        proc = subprocess.run(
            [sys.executable, "/app/co2batch.py"],
            input=input_csv, capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"CLI tool failed: {proc.stderr}"

        reader = csv.DictReader(proc.stdout.strip().split("\n"))
        rows = list(reader)
        assert len(rows) == 2, f"Expected 2 output rows, got {len(rows)}"

        # Verify output columns exist
        required_out = {"TA", "DIC", "pH", "pCO2", "fCO2", "CO3", "HCO3", "CO2aq"}
        for col in required_out:
            assert col in rows[0], f"Missing output column: {col}"

        # Verify first row values against PyCO2SYS
        ref = pyco2_ref(2300, 2100, 1, 2, temperature=25.0, salinity=35.0, pressure=0.0)
        for key in ["TA", "DIC", "pCO2", "fCO2", "CO3", "HCO3", "CO2aq"]:
            val = float(rows[0][key])
            rval = ref[key]
            if abs(rval) > 1e-10:
                rel_err = abs(val - rval) / abs(rval)
                assert rel_err < 1e-4, f"CLI {key}: got={val}, ref={rval}, rel_err={rel_err:.2e}"

    def test_cli_missing_optional_columns(self):
        """CSV with only required columns; optional ones should default."""
        input_csv = "par1,par2,par1_type,par2_type\n"
        input_csv += "2300,2100,1,2\n"

        proc = subprocess.run(
            [sys.executable, "/app/co2batch.py"],
            input=input_csv, capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, f"CLI tool failed with missing optional columns: {proc.stderr}"

        reader = csv.DictReader(proc.stdout.strip().split("\n"))
        rows = list(reader)
        assert len(rows) == 1

        # Compare against default conditions (T=25, S=35, P=0, no nutrients)
        ref = pyco2_ref(2300, 2100, 1, 2)
        val = float(rows[0]["pH"])
        assert abs(val - ref["pH"]) < 1e-6, f"CLI pH with defaults: got={val}, ref={ref['pH']}"
