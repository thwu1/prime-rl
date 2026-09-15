#!/usr/bin/env python3

"""
Radiotherapy dosimetric audit pipeline.

Loads NIfTI dose/structure data from multiple clinical sites, standardises
structure names to TG-263, detects and corrects dose unit anomalies,
computes DVH metrics from first principles, and evaluates clinical
protocol constraints including Homogeneity Index.
"""

import numpy as np
import pandas as pd
import SimpleITK as sitk
from pathlib import Path

DATA_DIR = Path("/app/data")
OUTPUT_DIR = Path("/app/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

STANDARD_NAMES = ["PTV70", "Brainstem", "Parotid_L", "Parotid_R", "SpinalCord"]

# Non-protocol structure keywords to exclude
EXCLUDE_KEYWORDS = ["external", "body", "bolus", "couch", "ring", "support"]


def match_structure_name(orig):
    """Map a clinical structure name to TG-263 standard name, or None if excluded."""
    s = orig.lower().replace("_", "").replace("-", "").replace(" ", "")

    # Exclude non-protocol structures
    for excl in EXCLUDE_KEYWORDS:
        if s == excl:
            return None

    scores = {}
    for std in STANDARD_NAMES:
        score = 0

        if std == "PTV70":
            if "ptv" in s or "target" in s:
                score += 10

        elif std == "Brainstem":
            if "brainstem" in s or "bstem" in s:
                score += 10
            elif "brain" in s and "stem" in s:
                score += 8

        elif std == "Parotid_L":
            if "parotid" in s or "par" in s:
                score += 3
            if any(k in s for k in ["left", "lparotid", "parotidl", "parl"]):
                score += 10
            elif "lt" in s:
                score += 10
            elif "parotid" in s:
                rest = s.replace("parotid", "")
                if rest and rest[0] == "l":
                    score += 8
            if any(k in s for k in ["right", "rt", "rparotid", "parotidr", "parr"]):
                score -= 20

        elif std == "Parotid_R":
            if "parotid" in s or "par" in s:
                score += 3
            if any(k in s for k in ["right", "rparotid", "parotidr", "parr"]):
                score += 10
            elif "rt" in s and ("parotid" in s or "par" in s):
                score += 10
            elif "parotid" in s:
                rest = s.replace("parotid", "")
                if rest and rest[-1] == "r":
                    score += 8
            if any(k in s for k in ["left", "lt", "lparotid", "parotidl", "parl"]):
                score -= 20

        elif std == "SpinalCord":
            if "spinalcord" in s:
                score += 15
            elif "cord" in s:
                score += 10
            elif "spinal" in s:
                score += 10
            elif s == "sc":
                score += 10

        scores[std] = score

    best = max(scores, key=scores.get)
    if scores[best] <= 0:
        return None
    return best


def detect_dose_scale(dose_arr):
    """Detect if dose is stored in cGy and return scale factor to Gy."""
    max_dose = float(np.max(dose_arr))
    if max_dose > 200.0:
        return 0.01  # cGy -> Gy
    return 1.0


def compute_dvh_metrics(dose_arr, mask_arr, spacing):
    """Compute DVH metrics for one structure from first principles."""
    dose_values = dose_arr[mask_arr > 0].astype(np.float64)
    n = len(dose_values)
    if n == 0:
        return None

    voxel_vol_cc = spacing[0] * spacing[1] * spacing[2] / 1000.0
    sorted_desc = np.sort(dose_values)[::-1]

    # Dx: minimum dose to hottest x% = (100-x)th percentile
    D95 = float(np.percentile(dose_values, 5))
    D50 = float(np.percentile(dose_values, 50))
    D2 = float(np.percentile(dose_values, 98))
    D98 = float(np.percentile(dose_values, 2))

    # Vx: percentage of volume receiving >= x Gy
    V5 = 100.0 * float(np.sum(dose_values >= 5.0)) / n
    V20 = 100.0 * float(np.sum(dose_values >= 20.0)) / n

    # Dcc1: dose to hottest 1 cc
    n_1cc = int(np.ceil(1.0 / voxel_vol_cc))
    Dcc1 = float(sorted_desc[min(n_1cc - 1, n - 1)])

    # Dmean
    Dmean = float(np.mean(dose_values))

    # Dmax = D0.03cc (ICRU 83 near-maximum)
    n_003cc = int(np.ceil(0.03 / voxel_vol_cc))
    Dmax = float(sorted_desc[min(n_003cc - 1, n - 1)])

    return {
        "D95": round(D95, 4), "D50": round(D50, 4),
        "D2": round(D2, 4), "D98": round(D98, 4),
        "Dmean": round(Dmean, 4), "Dmax": round(Dmax, 4),
        "V5": round(V5, 4), "V20": round(V20, 4),
        "Dcc1": round(Dcc1, 4),
    }


# Protocol constraints
CONSTRAINTS = [
    {"structure": "PTV70", "constraint": "D95", "op": ">=", "limit": 66.5},
    {"structure": "PTV70", "constraint": "D2", "op": "<=", "limit": 77.0},
    {"structure": "PTV70", "constraint": "HI", "op": "<=", "limit": 0.10},
    {"structure": "Brainstem", "constraint": "Dmax", "op": "<=", "limit": 54.0},
    {"structure": "SpinalCord", "constraint": "Dmax", "op": "<=", "limit": 45.0},
    {"structure": "Parotid_L", "constraint": "Dmean", "op": "<=", "limit": 26.0},
    {"structure": "Parotid_R", "constraint": "Dmean", "op": "<=", "limit": 26.0},
]


def main():
    # Discover patients
    patients = sorted([
        d.name for d in DATA_DIR.iterdir()
        if d.is_dir() and (d / "dose.nii.gz").exists()
    ])

    # Build name mapping (exclude non-protocol structures)
    mapping_rows = []
    name_map = {}
    for patient in patients:
        struct_dir = DATA_DIR / patient / "structures"
        pm = {}
        for f in sorted(struct_dir.glob("*.nii.gz")):
            orig = f.name.replace(".nii.gz", "")
            std = match_structure_name(orig)
            if std is not None:
                mapping_rows.append({
                    "patient": patient,
                    "original_name": orig,
                    "standard_name": std,
                })
                pm[orig] = std
        name_map[patient] = pm

    mapping_df = pd.DataFrame(mapping_rows)
    mapping_df.to_csv(OUTPUT_DIR / "name_mapping.csv", index=False)
    print(f"Wrote name_mapping.csv ({len(mapping_df)} rows)")

    # Compute DVH metrics
    metrics_rows = []
    metrics_by_patient = {}

    for patient in patients:
        pat_dir = DATA_DIR / patient
        dose_img = sitk.ReadImage(str(pat_dir / "dose.nii.gz"))
        dose_arr = sitk.GetArrayFromImage(dose_img).astype(np.float64)

        # Detect and correct dose unit anomalies
        scale = detect_dose_scale(dose_arr)
        if scale != 1.0:
            print(f"  {patient}: dose appears to be in cGy, converting to Gy")
        dose_arr *= scale

        spacing = dose_img.GetSpacing()
        pat_metrics = {}

        for orig_name, std_name in name_map[patient].items():
            mask_img = sitk.ReadImage(
                str(pat_dir / "structures" / f"{orig_name}.nii.gz")
            )
            mask_arr = sitk.GetArrayFromImage(mask_img)

            m = compute_dvh_metrics(dose_arr, mask_arr, spacing)
            if m is None:
                continue

            pat_metrics[std_name] = m
            metrics_rows.append({"patient": patient, "structure": std_name, **m})

        metrics_by_patient[patient] = pat_metrics

    metrics_df = pd.DataFrame(metrics_rows)
    metrics_df.to_csv(OUTPUT_DIR / "dvh_metrics.csv", index=False)
    print(f"Wrote dvh_metrics.csv ({len(metrics_df)} rows)")

    # Evaluate constraints (including HI)
    qa_rows = []
    for patient in patients:
        for c in CONSTRAINTS:
            struct = c["structure"]
            metric = c["constraint"]
            limit = c["limit"]
            op = c["op"]

            m = metrics_by_patient[patient][struct]

            if metric == "HI":
                # Homogeneity Index per ICRU Report 83
                actual = (m["D2"] - m["D98"]) / m["D50"]
            else:
                actual = m[metric]

            if op == ">=":
                status = "PASS" if actual >= limit else "FAIL"
            else:
                status = "PASS" if actual <= limit else "FAIL"

            qa_rows.append({
                "patient": patient,
                "structure": struct,
                "constraint": metric,
                "limit": limit,
                "actual": round(actual, 4),
                "status": status,
            })

    qa_df = pd.DataFrame(qa_rows)
    qa_df.to_csv(OUTPUT_DIR / "qa_report.csv", index=False)
    print(f"Wrote qa_report.csv ({len(qa_df)} rows)")

    n_fail = (qa_df["status"] == "FAIL").sum()
    print(f"\nAudit complete: {n_fail} constraint violations across {len(patients)} patients")


if __name__ == "__main__":
    main()
