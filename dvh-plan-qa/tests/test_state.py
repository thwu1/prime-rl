
import pytest
import numpy as np
import pandas as pd
import SimpleITK as sitk
from pathlib import Path

DATA_DIR = Path("/app/data")
OUTPUT_DIR = Path("/app/output")

PATIENTS = ["patient_A", "patient_B", "patient_C", "patient_D"]
STANDARD_NAMES = ["PTV70", "Brainstem", "Parotid_L", "Parotid_R", "SpinalCord"]

# Ground-truth structure name mappings (only protocol structures)
EXPECTED_MAPPING = {
    "patient_A": {
        "PTV_7000": "PTV70",
        "brainstem": "Brainstem",
        "lt_parotid": "Parotid_L",
        "rt_parotid": "Parotid_R",
        "cord": "SpinalCord",
    },
    "patient_B": {
        "PTV70": "PTV70",
        "Brain_Stem": "Brainstem",
        "L_PAROTID": "Parotid_L",
        "R_Parotid": "Parotid_R",
        "SpinalCord": "SpinalCord",
    },
    "patient_C": {
        "ptv_70gy": "PTV70",
        "BRAINSTEM": "Brainstem",
        "Parotid_Left": "Parotid_L",
        "Parotid_Right": "Parotid_R",
        "SC": "SpinalCord",
    },
    "patient_D": {
        "target_70gy": "PTV70",
        "bstem": "Brainstem",
        "par_L": "Parotid_L",
        "par_R": "Parotid_R",
        "spinal": "SpinalCord",
    },
}

# Non-protocol structures that must NOT appear in output
EXCLUDED_STRUCTURES = ["External", "BODY"]

# Dose scaling factors (patient_D dose is stored in cGy)
DOSE_SCALE = {
    "patient_A": 1.0,
    "patient_B": 1.0,
    "patient_C": 1.0,
    "patient_D": 0.01,
}

# Clinical constraints from protocol
CONSTRAINTS = [
    {"structure": "PTV70", "constraint": "D95", "op": ">=", "limit": 66.5},
    {"structure": "PTV70", "constraint": "D2", "op": "<=", "limit": 77.0},
    {"structure": "PTV70", "constraint": "HI", "op": "<=", "limit": 0.10},
    {"structure": "Brainstem", "constraint": "Dmax", "op": "<=", "limit": 54.0},
    {"structure": "SpinalCord", "constraint": "Dmax", "op": "<=", "limit": 45.0},
    {"structure": "Parotid_L", "constraint": "Dmean", "op": "<=", "limit": 26.0},
    {"structure": "Parotid_R", "constraint": "Dmean", "op": "<=", "limit": 26.0},
]

DOSE_TOL = 1.0   # Gy tolerance for dose metrics
VOL_TOL = 2.0    # % tolerance for volume metrics
HI_TOL = 0.02    # unitless tolerance for HI


def compute_reference_metrics(patient):
    """Recompute DVH metrics from raw NIfTI data as ground truth."""
    pat_dir = DATA_DIR / patient
    dose_img = sitk.ReadImage(str(pat_dir / "dose.nii.gz"))
    dose_arr = sitk.GetArrayFromImage(dose_img).astype(np.float64)
    dose_arr *= DOSE_SCALE[patient]  # normalize to Gy
    spacing = dose_img.GetSpacing()
    voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0

    mapping = EXPECTED_MAPPING[patient]
    results = {}

    for orig_name, std_name in mapping.items():
        mask_img = sitk.ReadImage(
            str(pat_dir / "structures" / f"{orig_name}.nii.gz")
        )
        mask_arr = sitk.GetArrayFromImage(mask_img)
        dose_values = dose_arr[mask_arr > 0]

        if len(dose_values) == 0:
            continue

        sorted_desc = np.sort(dose_values)[::-1]
        n = len(sorted_desc)

        # Dx metrics
        D95 = float(np.percentile(dose_values, 5))
        D50 = float(np.percentile(dose_values, 50))
        D2 = float(np.percentile(dose_values, 98))
        D98 = float(np.percentile(dose_values, 2))

        # Vx metrics
        V5 = 100.0 * float(np.sum(dose_values >= 5.0)) / n
        V20 = 100.0 * float(np.sum(dose_values >= 20.0)) / n

        # Dcc1
        n_1cc = int(np.ceil(1.0 / voxel_vol_cc))
        Dcc1 = float(sorted_desc[min(n_1cc - 1, n - 1)])

        # Dmean
        Dmean = float(np.mean(dose_values))

        # Dmax = D0.03cc (ICRU 83)
        n_003cc = int(np.ceil(0.03 / voxel_vol_cc))
        Dmax = float(sorted_desc[min(n_003cc - 1, n - 1)])

        results[std_name] = {
            "D95": D95, "D50": D50, "D2": D2, "D98": D98,
            "Dmean": Dmean, "Dmax": Dmax,
            "V5": V5, "V20": V20, "Dcc1": Dcc1,
        }

    return results


@pytest.fixture(scope="module")
def ref_all():
    return {p: compute_reference_metrics(p) for p in PATIENTS}


# ── Name Mapping Tests ──────────────────────────────────────────────

class TestNameMapping:
    def test_file_exists(self):
        assert (OUTPUT_DIR / "name_mapping.csv").exists(), \
            "name_mapping.csv not found in /app/output/"

    def test_all_mappings_correct(self):
        df = pd.read_csv(OUTPUT_DIR / "name_mapping.csv")
        df.columns = df.columns.str.strip()
        df["original_name"] = (
            df["original_name"]
            .str.strip()
            .str.replace(".nii.gz", "", regex=False)
        )
        df["standard_name"] = df["standard_name"].str.strip()
        df["patient"] = df["patient"].str.strip()

        for patient, mappings in EXPECTED_MAPPING.items():
            for orig, expected_std in mappings.items():
                rows = df[
                    (df["patient"] == patient) & (df["original_name"] == orig)
                ]
                assert len(rows) >= 1, (
                    f"Missing mapping row for {patient}/{orig}"
                )
                actual_std = rows.iloc[0]["standard_name"]
                assert actual_std == expected_std, (
                    f"{patient}/{orig}: expected '{expected_std}', "
                    f"got '{actual_std}'"
                )

    def test_excluded_structures_absent(self):
        """Body contours (External, BODY) must not appear in output."""
        df = pd.read_csv(OUTPUT_DIR / "name_mapping.csv")
        df.columns = df.columns.str.strip()
        df["original_name"] = df["original_name"].str.strip()

        for excl in EXCLUDED_STRUCTURES:
            rows = df[df["original_name"].str.lower() == excl.lower()]
            assert len(rows) == 0, (
                f"Non-protocol structure '{excl}' found in name_mapping.csv — "
                f"body contours must be excluded from the audit"
            )


# ── DVH Metrics Tests ───────────────────────────────────────────────

class TestDVHMetrics:
    def test_file_exists(self):
        assert (OUTPUT_DIR / "dvh_metrics.csv").exists(), \
            "dvh_metrics.csv not found in /app/output/"

    def test_all_structures_present(self):
        df = pd.read_csv(OUTPUT_DIR / "dvh_metrics.csv")
        df.columns = df.columns.str.strip()
        for patient in PATIENTS:
            for struct in STANDARD_NAMES:
                rows = df[
                    (df["patient"].str.strip() == patient)
                    & (df["structure"].str.strip() == struct)
                ]
                assert len(rows) >= 1, (
                    f"Missing DVH row for {patient}/{struct}"
                )

    def test_dose_metrics_accuracy(self, ref_all):
        df = pd.read_csv(OUTPUT_DIR / "dvh_metrics.csv")
        df.columns = df.columns.str.strip()
        dose_cols = ["D95", "D50", "D2", "D98", "Dmean", "Dmax", "Dcc1"]

        for patient in PATIENTS:
            for struct in STANDARD_NAMES:
                ref = ref_all[patient][struct]
                row = df[
                    (df["patient"].str.strip() == patient)
                    & (df["structure"].str.strip() == struct)
                ]
                assert len(row) >= 1, f"Missing {patient}/{struct}"
                for col in dose_cols:
                    actual = float(row.iloc[0][col])
                    expected = ref[col]
                    assert abs(actual - expected) < DOSE_TOL, (
                        f"{patient}/{struct}/{col}: "
                        f"expected {expected:.3f}, got {actual:.3f} "
                        f"(tol={DOSE_TOL})"
                    )

    def test_volume_metrics_accuracy(self, ref_all):
        df = pd.read_csv(OUTPUT_DIR / "dvh_metrics.csv")
        df.columns = df.columns.str.strip()

        for patient in PATIENTS:
            for struct in STANDARD_NAMES:
                ref = ref_all[patient][struct]
                row = df[
                    (df["patient"].str.strip() == patient)
                    & (df["structure"].str.strip() == struct)
                ]
                assert len(row) >= 1
                for col in ["V5", "V20"]:
                    actual = float(row.iloc[0][col])
                    expected = ref[col]
                    assert abs(actual - expected) < VOL_TOL, (
                        f"{patient}/{struct}/{col}: "
                        f"expected {expected:.3f}, got {actual:.3f} "
                        f"(tol={VOL_TOL})"
                    )

    def test_patient_d_doses_in_gray(self, ref_all):
        """Patient D dose was stored in cGy; all output must be in Gy."""
        df = pd.read_csv(OUTPUT_DIR / "dvh_metrics.csv")
        df.columns = df.columns.str.strip()
        row = df[
            (df["patient"].str.strip() == "patient_D")
            & (df["structure"].str.strip() == "PTV70")
        ]
        assert len(row) >= 1
        d50 = float(row.iloc[0]["D50"])
        assert d50 < 200, (
            f"patient_D PTV70 D50={d50:.1f}: appears to be in cGy, not Gy"
        )


# ── QA Report Tests ────────────────────────────────────────────────

class TestQAReport:
    def test_file_exists(self):
        assert (OUTPUT_DIR / "qa_report.csv").exists(), \
            "qa_report.csv not found in /app/output/"

    def test_all_constraints_present(self):
        df = pd.read_csv(OUTPUT_DIR / "qa_report.csv")
        df.columns = df.columns.str.strip()
        for patient in PATIENTS:
            for c in CONSTRAINTS:
                rows = df[
                    (df["patient"].str.strip() == patient)
                    & (df["structure"].str.strip() == c["structure"])
                    & (df["constraint"].str.strip().str.upper()
                       == c["constraint"].upper())
                ]
                assert len(rows) >= 1, (
                    f"Missing QA row: {patient}/{c['structure']}"
                    f"/{c['constraint']}"
                )

    def test_pass_fail_status(self, ref_all):
        df = pd.read_csv(OUTPUT_DIR / "qa_report.csv")
        df.columns = df.columns.str.strip()

        for patient in PATIENTS:
            ref = ref_all[patient]
            for c in CONSTRAINTS:
                struct = c["structure"]
                metric = c["constraint"]
                op = c["op"]
                limit = c["limit"]

                if metric == "HI":
                    ptv = ref["PTV70"]
                    ref_val = (ptv["D2"] - ptv["D98"]) / ptv["D50"]
                else:
                    ref_val = ref[struct][metric]

                if op == ">=":
                    expected_status = "PASS" if ref_val >= limit else "FAIL"
                else:
                    expected_status = "PASS" if ref_val <= limit else "FAIL"

                rows = df[
                    (df["patient"].str.strip() == patient)
                    & (df["structure"].str.strip() == struct)
                    & (df["constraint"].str.strip().str.upper()
                       == metric.upper())
                ]
                assert len(rows) >= 1, (
                    f"Missing QA row: {patient}/{struct}/{metric}"
                )
                actual_status = rows.iloc[0]["status"].strip().upper()
                assert actual_status == expected_status, (
                    f"{patient}/{struct}/{metric}: "
                    f"expected {expected_status} "
                    f"(value={ref_val:.4f}, limit={limit}), "
                    f"got {actual_status}"
                )

    def test_hi_values_reasonable(self, ref_all):
        """Check that HI actual values in qa_report are close to reference."""
        df = pd.read_csv(OUTPUT_DIR / "qa_report.csv")
        df.columns = df.columns.str.strip()

        for patient in PATIENTS:
            ptv = ref_all[patient]["PTV70"]
            expected_hi = (ptv["D2"] - ptv["D98"]) / ptv["D50"]

            rows = df[
                (df["patient"].str.strip() == patient)
                & (df["constraint"].str.strip().str.upper() == "HI")
            ]
            assert len(rows) >= 1, f"Missing HI row for {patient}"
            actual_hi = float(rows.iloc[0]["actual"])
            assert abs(actual_hi - expected_hi) < HI_TOL, (
                f"{patient} HI: expected {expected_hi:.4f}, "
                f"got {actual_hi:.4f} (tol={HI_TOL})"
            )
