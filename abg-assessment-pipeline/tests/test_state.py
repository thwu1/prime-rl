"""
Comprehensive tests for the ABG assessment pipeline.

"""

import json
import os
import subprocess
import tempfile

import pytest

# --- Test input data: 11 patient panels covering all disorder types and edge cases ---

INPUT_DATA = [
    {
        "id": "P001", "pH": 7.25, "PaCO2": 28, "HCO3": 12,
        "Na": 140, "K": 5.2, "Cl": 100, "albumin": 40,
        "glucose": 25, "urea": 8, "measured_osmolality": 310,
        "ethanol_mg_dl": None, "PaO2": 95, "FiO2": 0.21,
        "SaO2": 0.97, "SvO2": 0.72, "PcvCO2": 33,
        "Ca": 2.2, "Mg": 0.9, "lactate": 2.0, "chronicity": "acute"
    },
    {
        "id": "P002", "pH": 7.52, "PaCO2": 48, "HCO3": 38,
        "Na": 138, "K": 3.0, "Cl": 90, "albumin": 35,
        "glucose": 5.0, "urea": 6, "measured_osmolality": 285,
        "ethanol_mg_dl": None, "PaO2": 80, "FiO2": 0.21,
        "SaO2": 0.96, "SvO2": 0.70, "PcvCO2": 52,
        "Ca": 2.3, "Mg": 1.0, "lactate": 1.0, "chronicity": "acute"
    },
    {
        "id": "P003", "pH": 7.30, "PaCO2": 24, "HCO3": 11,
        "Na": 140, "K": 4.0, "Cl": 117, "albumin": 15,
        "glucose": 6, "urea": 10, "measured_osmolality": 295,
        "ethanol_mg_dl": None, "PaO2": 90, "FiO2": 0.30,
        "SaO2": 0.96, "SvO2": 0.68, "PcvCO2": 30,
        "Ca": 2.0, "Mg": 0.8, "lactate": 4.0, "chronicity": "acute"
    },
    {
        "id": "P004", "pH": 7.15, "PaCO2": 18, "HCO3": 6,
        "Na": 135, "K": 5.5, "Cl": 100, "albumin": 40,
        "glucose": 5, "urea": 3, "measured_osmolality": 340,
        "ethanol_mg_dl": 50, "PaO2": 100, "FiO2": 0.40,
        "SaO2": 0.98, "SvO2": 0.60, "PcvCO2": 25,
        "Ca": 2.1, "Mg": 0.85, "lactate": 6.0, "chronicity": "acute"
    },
    {
        "id": "P005", "pH": 7.32, "PaCO2": 60, "HCO3": 30,
        "Na": 140, "K": 4.5, "Cl": 102, "albumin": 38,
        "glucose": 7, "urea": 5, "measured_osmolality": 290,
        "ethanol_mg_dl": None, "PaO2": 55, "FiO2": 0.60,
        "SaO2": 0.88, "SvO2": 0.55, "PcvCO2": 66,
        "Ca": 2.3, "Mg": 1.0, "lactate": 1.5, "chronicity": "acute"
    },
    {
        "id": "P006", "pH": 7.46, "PaCO2": 25, "HCO3": 17,
        "Na": 136, "K": 3.8, "Cl": 110, "albumin": 30,
        "glucose": 5.5, "urea": 4, "measured_osmolality": 280,
        "ethanol_mg_dl": None, "PaO2": 105, "FiO2": 0.21,
        "SaO2": 0.99, "SvO2": 0.75, "PcvCO2": 30,
        "Ca": 2.2, "Mg": 0.85, "lactate": 1.0, "chronicity": "chronic"
    },
    {
        "id": "P007", "pH": 7.10, "PaCO2": 35, "HCO3": 10,
        "Na": 142, "K": 6.0, "Cl": 102, "albumin": 40,
        "glucose": 8, "urea": 20, "measured_osmolality": 310,
        "ethanol_mg_dl": None, "PaO2": 70, "FiO2": 0.50,
        "SaO2": 0.93, "SvO2": 0.50, "PcvCO2": 45,
        "Ca": 2.0, "Mg": 0.8, "lactate": 8.0, "chronicity": "acute"
    },
    {
        "id": "P008", "pH": 7.40, "PaCO2": 40, "HCO3": 24,
        "Na": 140, "K": 4.0, "Cl": 104, "albumin": 40,
        "glucose": 5.0, "urea": 5, "measured_osmolality": 290,
        "ethanol_mg_dl": None, "PaO2": 100, "FiO2": 0.21,
        "SaO2": 0.98, "SvO2": 0.73, "PcvCO2": 44,
        "Ca": 2.4, "Mg": 1.0, "lactate": 1.0, "chronicity": "acute"
    },
    {
        "id": "P009", "pH": 7.34, "PaCO2": 60, "HCO3": 32,
        "Na": 137, "K": 4.2, "Cl": 95, "albumin": 35,
        "glucose": 6, "urea": 7, "measured_osmolality": 285,
        "ethanol_mg_dl": None, "PaO2": 58, "FiO2": 0.28,
        "SaO2": 0.89, "SvO2": 0.63, "PcvCO2": 65,
        "Ca": 2.3, "Mg": 0.9, "lactate": 1.2, "chronicity": "chronic"
    },
    {
        "id": "P010", "pH": 7.42, "PaCO2": 40, "HCO3": 25,
        "Na": 142, "K": 3.5, "Cl": 98, "albumin": 40,
        "glucose": 5.5, "urea": 6, "measured_osmolality": 292,
        "ethanol_mg_dl": None, "PaO2": 90, "FiO2": 0.21,
        "SaO2": 0.97, "SvO2": 0.70, "PcvCO2": 45,
        "Ca": 2.3, "Mg": 1.0, "lactate": 1.0, "chronicity": "acute"
    },
    {
        "id": "P011", "pH": 7.28, "PaCO2": 33, "HCO3": 14,
        "Na": 138, "K": 4.5, "Cl": 110, "albumin": 40,
        "glucose": 6, "urea": 5, "measured_osmolality": 288,
        "ethanol_mg_dl": None, "PaO2": 88, "FiO2": 0.21,
        "SaO2": 0.96, "SvO2": 0.72, "PcvCO2": 38,
        "Ca": 2.3, "Mg": 0.9, "lactate": 1.0, "chronicity": "acute"
    },
]


# --- Expected output values for each patient ---

EXPECTED = {
    "P001": {
        "pH_status": "acidaemia",
        "primary_disorder": "metabolic_acidosis",
        "anion_gap": 28.0,
        "corrected_anion_gap": 28.0,
        "anion_gap_classification": "high",
        "delta_ratio": 1.33,
        "delta_ratio_interpretation": "pure_hagma",
        "expected_paco2": 26.0,
        "expected_hco3": None,
        "compensation_status": "appropriate",
        "corrected_sodium": 145.32,
        "corrected_potassium": 4.30,
        "calculated_osmolarity": 313.0,
        "osmolar_gap": -3.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 49.40,
        "sid_effective": 22.43,
        "strong_ion_gap": 26.97,
        "pf_ratio": 452.38,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.26,
        "o2er_status": "normal",
        "pco2_gap": 5.0,
        "pco2_gap_status": "normal",
    },
    "P002": {
        "pH_status": "alkalaemia",
        "primary_disorder": "metabolic_alkalosis",
        "anion_gap": 10.0,
        "corrected_anion_gap": 11.25,
        "anion_gap_classification": "normal",
        "delta_ratio": None,
        "delta_ratio_interpretation": None,
        "expected_paco2": 46.6,
        "expected_hco3": None,
        "compensation_status": "appropriate",
        "corrected_sodium": 137.86,
        "corrected_potassium": 3.72,
        "calculated_osmolarity": 287.0,
        "osmolar_gap": -2.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 56.60,
        "sid_effective": 48.29,
        "strong_ion_gap": 8.31,
        "pf_ratio": 380.95,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.27,
        "o2er_status": "normal",
        "pco2_gap": 4.0,
        "pco2_gap_status": "normal",
    },
    "P003": {
        "pH_status": "acidaemia",
        "primary_disorder": "metabolic_acidosis",
        "anion_gap": 12.0,
        "corrected_anion_gap": 18.25,
        "anion_gap_classification": "high",
        "delta_ratio": 0.48,
        "delta_ratio_interpretation": "mixed_hagma_nagma",
        "expected_paco2": 24.5,
        "expected_hco3": None,
        "compensation_status": "appropriate",
        "corrected_sodium": 140.14,
        "corrected_potassium": 3.40,
        "calculated_osmolarity": 296.0,
        "osmolar_gap": -1.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 28.60,
        "sid_effective": 15.00,
        "strong_ion_gap": 13.60,
        "pf_ratio": 300.0,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.29,
        "o2er_status": "normal",
        "pco2_gap": 6.0,
        "pco2_gap_status": "normal",
    },
    "P004": {
        "pH_status": "acidaemia",
        "primary_disorder": "metabolic_acidosis",
        "anion_gap": 29.0,
        "corrected_anion_gap": 29.0,
        "anion_gap_classification": "high",
        "delta_ratio": 0.94,
        "delta_ratio_interpretation": "pure_hagma",
        "expected_paco2": 17.0,
        "expected_hco3": None,
        "compensation_status": "appropriate",
        "corrected_sodium": 134.86,
        "corrected_potassium": 4.0,
        "calculated_osmolarity": 291.59,
        "osmolar_gap": 48.41,
        "osmolar_gap_elevated": True,
        "sid_apparent": 40.40,
        "sid_effective": 15.94,
        "strong_ion_gap": 24.46,
        "pf_ratio": 250.0,
        "ards_severity": "mild",
        "o2_extraction_ratio": 0.39,
        "o2er_status": "high",
        "pco2_gap": 7.0,
        "pco2_gap_status": "elevated",
    },
    "P005": {
        "pH_status": "acidaemia",
        "primary_disorder": "respiratory_acidosis",
        "anion_gap": 8.0,
        "corrected_anion_gap": 8.50,
        "anion_gap_classification": "normal",
        "delta_ratio": None,
        "delta_ratio_interpretation": None,
        "expected_paco2": None,
        "expected_hco3": 26.0,
        "compensation_status": "additional_metabolic_alkalosis",
        "corrected_sodium": 140.41,
        "corrected_potassium": 4.02,
        "calculated_osmolarity": 292.0,
        "osmolar_gap": -2.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 47.60,
        "sid_effective": 40.24,
        "strong_ion_gap": 7.36,
        "pf_ratio": 91.67,
        "ards_severity": "severe",
        "o2_extraction_ratio": 0.37,
        "o2er_status": "high",
        "pco2_gap": 6.0,
        "pco2_gap_status": "normal",
    },
    "P006": {
        "pH_status": "alkalaemia",
        "primary_disorder": "respiratory_alkalosis",
        "anion_gap": 9.0,
        "corrected_anion_gap": 11.50,
        "anion_gap_classification": "normal",
        "delta_ratio": None,
        "delta_ratio_interpretation": None,
        "expected_paco2": None,
        "expected_hco3": 16.5,
        "compensation_status": "appropriate",
        "corrected_sodium": 136.0,
        "corrected_potassium": 4.16,
        "calculated_osmolarity": 281.50,
        "osmolar_gap": -1.50,
        "osmolar_gap_elevated": False,
        "sid_apparent": 34.90,
        "sid_effective": 25.60,
        "strong_ion_gap": 9.30,
        "pf_ratio": 500.0,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.24,
        "o2er_status": "normal",
        "pco2_gap": 5.0,
        "pco2_gap_status": "normal",
    },
    "P007": {
        "pH_status": "acidaemia",
        "primary_disorder": "metabolic_acidosis",
        "anion_gap": 30.0,
        "corrected_anion_gap": 30.0,
        "anion_gap_classification": "high",
        "delta_ratio": 1.29,
        "delta_ratio_interpretation": "pure_hagma",
        "expected_paco2": 23.0,
        "expected_hco3": None,
        "compensation_status": "additional_respiratory_acidosis",
        "corrected_sodium": 142.68,
        "corrected_potassium": 4.20,
        "calculated_osmolarity": 312.0,
        "osmolar_gap": -2.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 43.60,
        "sid_effective": 19.69,
        "strong_ion_gap": 23.91,
        "pf_ratio": 140.0,
        "ards_severity": "moderate",
        "o2_extraction_ratio": 0.46,
        "o2er_status": "high",
        "pco2_gap": 10.0,
        "pco2_gap_status": "elevated",
    },
    "P008": {
        "pH_status": "normal",
        "primary_disorder": "normal",
        "anion_gap": 12.0,
        "corrected_anion_gap": 12.0,
        "anion_gap_classification": "normal",
        "delta_ratio": None,
        "delta_ratio_interpretation": None,
        "expected_paco2": None,
        "expected_hco3": None,
        "compensation_status": None,
        "corrected_sodium": 139.86,
        "corrected_potassium": 4.0,
        "calculated_osmolarity": 290.0,
        "osmolar_gap": 0.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 45.80,
        "sid_effective": 35.17,
        "strong_ion_gap": 10.63,
        "pf_ratio": 476.19,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.26,
        "o2er_status": "normal",
        "pco2_gap": 4.0,
        "pco2_gap_status": "normal",
    },
    "P009": {
        "pH_status": "acidaemia",
        "primary_disorder": "respiratory_acidosis",
        "anion_gap": 10.0,
        "corrected_anion_gap": 11.25,
        "anion_gap_classification": "normal",
        "delta_ratio": None,
        "delta_ratio_interpretation": None,
        "expected_paco2": None,
        "expected_hco3": 32.0,
        "compensation_status": "appropriate",
        "corrected_sodium": 137.14,
        "corrected_potassium": 3.84,
        "calculated_osmolarity": 287.0,
        "osmolar_gap": -2.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 51.40,
        "sid_effective": 41.51,
        "strong_ion_gap": 9.89,
        "pf_ratio": 207.14,
        "ards_severity": "mild",
        "o2_extraction_ratio": 0.29,
        "o2er_status": "normal",
        "pco2_gap": 5.0,
        "pco2_gap_status": "normal",
    },
    "P010": {
        "pH_status": "normal",
        "primary_disorder": "normal",
        "anion_gap": 19.0,
        "corrected_anion_gap": 19.0,
        "anion_gap_classification": "high",
        "delta_ratio": None,
        "delta_ratio_interpretation": "hagma_plus_alkalosis",
        "expected_paco2": None,
        "expected_hco3": None,
        "compensation_status": None,
        "corrected_sodium": 142.0,
        "corrected_potassium": 3.62,
        "calculated_osmolarity": 295.50,
        "osmolar_gap": -3.50,
        "osmolar_gap_elevated": False,
        "sid_apparent": 53.10,
        "sid_effective": 36.27,
        "strong_ion_gap": 16.83,
        "pf_ratio": 428.57,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.28,
        "o2er_status": "normal",
        "pco2_gap": 5.0,
        "pco2_gap_status": "normal",
    },
    "P011": {
        "pH_status": "acidaemia",
        "primary_disorder": "metabolic_acidosis",
        "anion_gap": 14.0,
        "corrected_anion_gap": 14.0,
        "anion_gap_classification": "high",
        "delta_ratio": 0.20,
        "delta_ratio_interpretation": "pure_nagma",
        "expected_paco2": 29.0,
        "expected_hco3": None,
        "compensation_status": "additional_respiratory_acidosis",
        "corrected_sodium": 138.14,
        "corrected_potassium": 3.78,
        "calculated_osmolarity": 287.0,
        "osmolar_gap": 1.0,
        "osmolar_gap_elevated": False,
        "sid_apparent": 37.90,
        "sid_effective": 24.58,
        "strong_ion_gap": 13.32,
        "pf_ratio": 419.05,
        "ards_severity": "none",
        "o2_extraction_ratio": 0.25,
        "o2er_status": "normal",
        "pco2_gap": 5.0,
        "pco2_gap_status": "normal",
    },
}

NUMERIC_FIELDS = [
    "anion_gap", "corrected_anion_gap", "delta_ratio",
    "expected_paco2", "expected_hco3",
    "corrected_sodium", "corrected_potassium",
    "calculated_osmolarity", "osmolar_gap",
    "sid_apparent", "sid_effective", "strong_ion_gap",
    "pf_ratio", "o2_extraction_ratio", "pco2_gap",
]

STRING_FIELDS = [
    "pH_status", "primary_disorder", "anion_gap_classification",
    "delta_ratio_interpretation", "compensation_status",
    "ards_severity", "o2er_status", "pco2_gap_status",
]

BOOL_FIELDS = ["osmolar_gap_elevated"]


@pytest.fixture(scope="module")
def output_data():
    """Run the ABG assessment tool and return output indexed by patient ID."""
    input_file = os.path.join(tempfile.gettempdir(), "abg_test_input.json")
    output_file = os.path.join(tempfile.gettempdir(), "abg_test_output.json")

    with open(input_file, "w") as f:
        json.dump(INPUT_DATA, f)

    result = subprocess.run(
        ["python3", "/app/abg_assess.py", input_file, output_file],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Tool exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    with open(output_file) as f:
        data = json.load(f)

    assert isinstance(data, list), "Output must be a JSON array"
    assert len(data) == len(INPUT_DATA), (
        f"Expected {len(INPUT_DATA)} results, got {len(data)}"
    )

    return {r["id"]: r for r in data}


def _check_patient(output_data, patient_id):
    """Validate all output fields for a single patient."""
    result = output_data[patient_id]
    expected = EXPECTED[patient_id]

    # Check ID
    assert result["id"] == patient_id

    # Check string fields
    for field in STRING_FIELDS:
        exp = expected[field]
        act = result.get(field)
        if exp is None:
            assert act is None, f"{patient_id}.{field}: expected null, got {act!r}"
        else:
            assert act == exp, f"{patient_id}.{field}: expected '{exp}', got '{act}'"

    # Check boolean fields
    for field in BOOL_FIELDS:
        exp = expected[field]
        act = result.get(field)
        assert act == exp, f"{patient_id}.{field}: expected {exp}, got {act}"

    # Check numeric fields
    for field in NUMERIC_FIELDS:
        exp = expected[field]
        act = result.get(field)
        if exp is None:
            assert act is None, f"{patient_id}.{field}: expected null, got {act}"
        else:
            assert act is not None, f"{patient_id}.{field}: expected {exp}, got null"
            assert abs(act - exp) < 0.02, (
                f"{patient_id}.{field}: expected {exp}, got {act} "
                f"(diff={abs(act - exp):.4f})"
            )


def test_p001_classic_dka(output_data):
    """P001: Classic DKA - HAGMA with appropriate respiratory compensation."""
    _check_patient(output_data, "P001")


def test_p002_metabolic_alkalosis(output_data):
    """P002: Metabolic alkalosis from vomiting with appropriate compensation."""
    _check_patient(output_data, "P002")


def test_p003_masked_hagma(output_data):
    """P003: HAGMA masked by hypoalbuminaemia + concurrent NAGMA (mixed)."""
    _check_patient(output_data, "P003")


def test_p004_toxic_alcohol(output_data):
    """P004: Toxic alcohol ingestion - HAGMA + elevated osmolar gap + ethanol."""
    _check_patient(output_data, "P004")


def test_p005_resp_acidosis_plus_met_alkalosis(output_data):
    """P005: Acute respiratory acidosis with additional metabolic alkalosis."""
    _check_patient(output_data, "P005")


def test_p006_chronic_resp_alkalosis(output_data):
    """P006: Chronic respiratory alkalosis with appropriate compensation."""
    _check_patient(output_data, "P006")


def test_p007_hagma_plus_resp_acidosis(output_data):
    """P007: HAGMA with additional respiratory acidosis (incomplete compensation)."""
    _check_patient(output_data, "P007")


def test_p008_normal(output_data):
    """P008: Completely normal blood gas panel."""
    _check_patient(output_data, "P008")


def test_p009_chronic_resp_acidosis(output_data):
    """P009: Chronic respiratory acidosis (COPD) with appropriate compensation."""
    _check_patient(output_data, "P009")


def test_p010_hidden_mixed_disorder(output_data):
    """P010: Normal pH but elevated AG - hidden HAGMA + metabolic alkalosis."""
    _check_patient(output_data, "P010")


def test_p011_winters_tolerance(output_data):
    """P011: Metabolic acidosis with PaCO2 in tolerance boundary zone."""
    _check_patient(output_data, "P011")


def test_output_structure(output_data):
    """Verify the output contains all required fields for every patient."""
    all_fields = (
        ["id"] + STRING_FIELDS + BOOL_FIELDS + NUMERIC_FIELDS
    )
    for pid, result in output_data.items():
        for field in all_fields:
            assert field in result, f"{pid} missing field '{field}'"
