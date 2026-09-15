
import subprocess
import csv
import os
import pytest


def run_r_expr(expr):
    """Run an R expression and return stdout, stderr, returncode."""
    result = subprocess.run(
        ["Rscript", "-e", expr],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def get_risk(calculator, **kwargs):
    """Call a calculator function and return the numeric result or None."""
    func_map = {
        "accaha": "ascvd_10y_accaha",
        "frs": "ascvd_10y_frs",
        "frs_simple": "ascvd_10y_frs_simple",
        "mesa": "chd_10y_mesa",
        "mesa_cac": "chd_10y_mesa_cac",
    }
    func = func_map[calculator]

    parts = []
    for k, v in kwargs.items():
        if isinstance(v, str):
            parts.append(f"{k} = '{v}'")
        else:
            parts.append(f"{k} = {v}")
    args_str = ", ".join(parts)

    expr = f'source("/app/R/{calculator}.R"); result <- {func}({args_str}); cat(result)'
    stdout, stderr, rc = run_r_expr(expr)

    if stdout == "NA" or not stdout:
        return None
    try:
        return float(stdout)
    except ValueError:
        return None


# =====================================================================
# ACC/AHA 2013 Pooled Cohort Equations
# =====================================================================


class TestACCAHA:
    """Test ACC/AHA 2013 Pooled Cohort Equations."""

    def test_aa_male(self):
        result = get_risk(
            "accaha", race="aa", gender="male", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(7.95, abs=0.01)

    def test_aa_female(self):
        result = get_risk(
            "accaha", race="aa", gender="female", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(5.08, abs=0.01)

    def test_white_female(self):
        result = get_risk(
            "accaha", race="white", gender="female", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(2.76, abs=0.01)

    def test_white_male(self):
        result = get_risk(
            "accaha", race="white", gender="male", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(7.01, abs=0.01)

    def test_other_race_uses_white(self):
        result = get_risk(
            "accaha", race="other", gender="male", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(7.01, abs=0.01)

    def test_invalid_age_high(self):
        result = get_risk(
            "accaha", race="aa", gender="female", age=80,
            totchol=190, hdl=50, sbp=120,
            bp_med=0, smoker=1, diabetes=0,
        )
        assert result is None

    def test_invalid_age_low(self):
        result = get_risk(
            "accaha", race="white", gender="male", age=19,
            totchol=200, hdl=50, sbp=120,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is None

    def test_invalid_totchol(self):
        result = get_risk(
            "accaha", race="aa", gender="female", age=60,
            totchol=9999, hdl=50, sbp=120,
            bp_med=0, smoker=1, diabetes=0,
        )
        assert result is None

    def test_invalid_hdl(self):
        result = get_risk(
            "accaha", race="white", gender="male", age=55,
            totchol=200, hdl=150, sbp=120,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is None

    def test_invalid_sbp(self):
        result = get_risk(
            "accaha", race="white", gender="male", age=55,
            totchol=200, hdl=50, sbp=250,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is None

    def test_bp_med_treated_increases_risk(self):
        """Treated SBP uses different coefficients; for white male treated > untreated."""
        untreated = get_risk(
            "accaha", race="white", gender="male", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=0, smoker=0, diabetes=0,
        )
        treated = get_risk(
            "accaha", race="white", gender="male", age=55,
            totchol=213, hdl=50, sbp=140,
            bp_med=1, smoker=0, diabetes=0,
        )
        assert untreated is not None
        assert treated is not None
        assert treated > untreated

    def test_valid_age_boundary_20(self):
        """Age 20 should be valid for ACC/AHA."""
        result = get_risk(
            "accaha", race="white", gender="male", age=20,
            totchol=200, hdl=50, sbp=120,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result >= 1

    def test_valid_age_boundary_79(self):
        """Age 79 should be valid for ACC/AHA."""
        result = get_risk(
            "accaha", race="white", gender="male", age=79,
            totchol=200, hdl=50, sbp=120,
            bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result >= 1


# =====================================================================
# Framingham 2008 Lab-Based
# =====================================================================


class TestFRS:
    """Test Framingham 2008 lab-based risk score."""

    def test_male_55(self):
        result = get_risk(
            "frs", gender="male", age=55, hdl=50,
            totchol=213, sbp=140, bp_med=0,
            smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(13.53, abs=0.01)

    def test_age_below_30(self):
        result = get_risk(
            "frs", gender="male", age=29, hdl=50,
            totchol=213, sbp=140, bp_med=0,
            smoker=0, diabetes=0,
        )
        assert result is None

    def test_age_above_74(self):
        result = get_risk(
            "frs", gender="male", age=75, hdl=50,
            totchol=213, sbp=140, bp_med=0,
            smoker=0, diabetes=0,
        )
        assert result is None

    def test_age_74_valid(self):
        """Age 74 should be valid for Framingham."""
        result = get_risk(
            "frs", gender="male", age=74, hdl=50,
            totchol=213, sbp=140, bp_med=0,
            smoker=0, diabetes=0,
        )
        assert result is not None
        assert result >= 1

    def test_gender_abbreviation_m(self):
        result = get_risk(
            "frs", gender="m", age=55, hdl=50,
            totchol=213, sbp=140, bp_med=0,
            smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(13.53, abs=0.01)

    def test_gender_abbreviation_f(self):
        result = get_risk(
            "frs", gender="f", age=55, hdl=50,
            totchol=213, sbp=140, bp_med=0,
            smoker=0, diabetes=0,
        )
        assert result is not None
        assert result >= 1


# =====================================================================
# Framingham 2008 BMI-Based (Simple)
# =====================================================================


class TestFRSSimple:
    """Test Framingham 2008 BMI-based risk score."""

    def test_male_55(self):
        result = get_risk(
            "frs_simple", gender="male", age=55, bmi=30,
            sbp=140, bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(16.75, abs=0.01)

    def test_gender_abbreviation_m(self):
        result = get_risk(
            "frs_simple", gender="m", age=55, bmi=30,
            sbp=140, bp_med=0, smoker=0, diabetes=0,
        )
        assert result is not None
        assert result == pytest.approx(16.75, abs=0.01)

    def test_age_below_30(self):
        result = get_risk(
            "frs_simple", gender="male", age=29, bmi=30,
            sbp=140, bp_med=0, smoker=0, diabetes=0,
        )
        assert result is None

    def test_age_above_74(self):
        result = get_risk(
            "frs_simple", gender="male", age=75, bmi=30,
            sbp=140, bp_med=0, smoker=0, diabetes=0,
        )
        assert result is None

    def test_risk_capped_at_30(self):
        result = get_risk(
            "frs_simple", gender="male", age=70, bmi=40,
            sbp=180, bp_med=0, smoker=1, diabetes=1,
        )
        assert result is not None
        assert result <= 30


# =====================================================================
# MESA 2015 CHD (without CAC)
# =====================================================================


class TestMESA:
    """Test MESA 2015 CHD risk score (without CAC)."""

    def test_hispanic_male_70(self):
        result = get_risk(
            "mesa", race="hispanic", gender="male", age=70,
            totchol=190, hdl=50, lipid_med=0,
            sbp=130, bp_med=1, smoker=0,
            diabetes=0, fh_heartattack=0,
        )
        assert result is not None
        assert result == pytest.approx(8.61, abs=0.01)

    def test_risk_capped_at_30(self):
        result = get_risk(
            "mesa", race="white", gender="male", age=85,
            totchol=280, hdl=30, lipid_med=1,
            sbp=180, bp_med=1, smoker=1,
            diabetes=1, fh_heartattack=1,
        )
        assert result is not None
        assert result <= 30

    def test_risk_floor_at_1(self):
        """Very low risk should be floored at 1%."""
        result = get_risk(
            "mesa", race="chinese", gender="female", age=45,
            totchol=160, hdl=80, lipid_med=0,
            sbp=100, bp_med=0, smoker=0,
            diabetes=0, fh_heartattack=0,
        )
        assert result is not None
        assert result >= 1

    def test_invalid_race_errors(self):
        """Invalid race should raise an error (return None from get_risk)."""
        result = get_risk(
            "mesa", race="other", gender="male", age=65,
            totchol=200, hdl=50, lipid_med=0,
            sbp=130, bp_med=0, smoker=0,
            diabetes=0, fh_heartattack=0,
        )
        assert result is None


# =====================================================================
# MESA 2015 CHD (with CAC)
# =====================================================================


class TestMESACAC:
    """Test MESA 2015 CHD risk score (with CAC)."""

    def test_hispanic_male_70_cac0(self):
        result = get_risk(
            "mesa_cac", race="hispanic", gender="male", age=70,
            totchol=190, hdl=50, lipid_med=0,
            sbp=130, bp_med=1, smoker=0,
            diabetes=0, fh_heartattack=0, cac=0,
        )
        assert result is not None
        assert result == pytest.approx(3.06, abs=0.01)

    def test_cac_zero_vs_nonzero(self):
        """CAC=0 should give lower risk than CAC=400."""
        result_zero = get_risk(
            "mesa_cac", race="white", gender="male", age=65,
            totchol=210, hdl=45, lipid_med=0,
            sbp=140, bp_med=0, smoker=0,
            diabetes=0, fh_heartattack=0, cac=0,
        )
        result_high = get_risk(
            "mesa_cac", race="white", gender="male", age=65,
            totchol=210, hdl=45, lipid_med=0,
            sbp=140, bp_med=0, smoker=0,
            diabetes=0, fh_heartattack=0, cac=400,
        )
        assert result_zero is not None
        assert result_high is not None
        assert result_high > result_zero

    def test_cac_zero_produces_finite_result(self):
        """CAC=0 must not cause -Inf from log; result must be finite."""
        result = get_risk(
            "mesa_cac", race="white", gender="female", age=60,
            totchol=200, hdl=55, lipid_med=0,
            sbp=130, bp_med=0, smoker=0,
            diabetes=0, fh_heartattack=0, cac=0,
        )
        assert result is not None
        assert result >= 1


# =====================================================================
# Batch Processing
# =====================================================================


class TestBatchProcessing:
    """Test the batch processing CLI."""

    def _run_batch(self, rows):
        """Write a CSV, run the batch processor, return output rows."""
        input_file = "/tmp/test_input.csv"
        output_file = "/tmp/test_output.csv"

        fieldnames = [
            "patient_id", "race", "gender", "age", "totchol",
            "hdl", "sbp", "bp_med", "smoker", "diabetes",
            "bmi", "lipid_med", "fh_heartattack", "cac",
        ]

        with open(input_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

        result = subprocess.run(
            ["Rscript", "/app/run_batch.R", input_file, output_file],
            capture_output=True, text=True, timeout=60,
        )

        assert result.returncode == 0, f"Batch processing failed: {result.stderr}"

        with open(output_file, "r") as f:
            reader = csv.DictReader(f)
            return list(reader)

    def test_single_patient_all_scores(self):
        """Single patient gets all 5 risk scores with correct values."""
        rows = [
            {
                "patient_id": "P1", "race": "white", "gender": "male",
                "age": 55, "totchol": 213, "hdl": 50, "sbp": 140,
                "bp_med": 0, "smoker": 0, "diabetes": 0,
                "bmi": 30, "lipid_med": 0, "fh_heartattack": 0, "cac": 0,
            }
        ]

        output = self._run_batch(rows)
        assert len(output) == 1

        row = output[0]
        assert "accaha_risk" in row
        assert "frs_risk" in row
        assert "frs_simple_risk" in row
        assert "mesa_risk" in row
        assert "mesa_cac_risk" in row

        assert float(row["accaha_risk"]) == pytest.approx(7.01, abs=0.01)
        assert float(row["frs_risk"]) == pytest.approx(13.53, abs=0.01)
        assert float(row["frs_simple_risk"]) == pytest.approx(16.75, abs=0.01)

    def test_multiple_patients(self):
        """Batch processing with multiple patients."""
        rows = [
            {
                "patient_id": "P1", "race": "aa", "gender": "male",
                "age": 55, "totchol": 213, "hdl": 50, "sbp": 140,
                "bp_med": 0, "smoker": 0, "diabetes": 0,
                "bmi": 30, "lipid_med": 0, "fh_heartattack": 0, "cac": 0,
            },
            {
                "patient_id": "P2", "race": "white", "gender": "female",
                "age": 55, "totchol": 213, "hdl": 50, "sbp": 140,
                "bp_med": 0, "smoker": 0, "diabetes": 0,
                "bmi": 25, "lipid_med": 0, "fh_heartattack": 0, "cac": 0,
            },
        ]

        output = self._run_batch(rows)
        assert len(output) == 2

        assert float(output[0]["accaha_risk"]) == pytest.approx(7.95, abs=0.01)
        assert float(output[1]["accaha_risk"]) == pytest.approx(2.76, abs=0.01)

    def test_batch_mesa_scores(self):
        """Test that MESA and MESA+CAC scores are correct in batch mode."""
        rows = [
            {
                "patient_id": "P1", "race": "hispanic", "gender": "male",
                "age": 70, "totchol": 190, "hdl": 50, "sbp": 130,
                "bp_med": 1, "smoker": 0, "diabetes": 0,
                "bmi": 28, "lipid_med": 0, "fh_heartattack": 0, "cac": 0,
            }
        ]

        output = self._run_batch(rows)
        assert len(output) == 1

        assert float(output[0]["mesa_risk"]) == pytest.approx(8.61, abs=0.01)
        assert float(output[0]["mesa_cac_risk"]) == pytest.approx(3.06, abs=0.01)

    def test_batch_frs_simple_receives_bmi(self):
        """Verify batch dispatch passes BMI to the FRS simple calculator."""
        rows = [
            {
                "patient_id": "P1", "race": "white", "gender": "male",
                "age": 55, "totchol": 213, "hdl": 50, "sbp": 140,
                "bp_med": 0, "smoker": 0, "diabetes": 0,
                "bmi": 30, "lipid_med": 0, "fh_heartattack": 0, "cac": 0,
            }
        ]

        output = self._run_batch(rows)
        frs_simple = output[0]["frs_simple_risk"]
        assert frs_simple != "NA", "frs_simple_risk is NA — bmi may not be passed to calculator"
        assert float(frs_simple) == pytest.approx(16.75, abs=0.01)
