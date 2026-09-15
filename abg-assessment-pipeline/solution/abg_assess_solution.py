#!/usr/bin/env python3
"""
Comprehensive critical care acid-base assessment pipeline.
Loads clinical parameters from a SQLite database.

"""

import json
import os
import sqlite3
import subprocess
import sys


DB_PATH = "/app/clinical_params.db"


def ensure_db():
    """Create parameter database if it doesn't exist."""
    if not os.path.exists(DB_PATH):
        subprocess.run(["python3", "/app/init_params.py"], check=True)


def load_coefficients(conn):
    """Load formula coefficients as nested dict: {formula: {param: value}}."""
    cur = conn.execute("SELECT formula, param, value FROM formula_coefficients")
    coeffs = {}
    for formula, param, value in cur.fetchall():
        coeffs.setdefault(formula, {})[param] = value
    return coeffs


def load_thresholds(conn):
    """Load clinical thresholds as nested dict: {metric: {boundary: (value, classification)}}."""
    cur = conn.execute(
        "SELECT metric, boundary, value, classification FROM clinical_thresholds"
    )
    thresholds = {}
    for metric, boundary, value, classification in cur.fetchall():
        thresholds.setdefault(metric, {})[boundary] = (value, classification)
    return thresholds


def assess_patient(p, coeffs, thresholds):
    """Compute all assessment fields for a single patient panel."""
    result = {"id": p["id"]}

    pH = p["pH"]
    PaCO2 = p["PaCO2"]
    HCO3 = p["HCO3"]
    Na = p["Na"]
    K = p["K"]
    Cl = p["Cl"]
    albumin = p["albumin"]
    glucose = p["glucose"]
    urea = p["urea"]
    measured_osmolality = p["measured_osmolality"]
    ethanol_mg_dl = p.get("ethanol_mg_dl")
    PaO2 = p["PaO2"]
    FiO2 = p["FiO2"]
    SaO2 = p["SaO2"]
    SvO2 = p["SvO2"]
    PcvCO2 = p["PcvCO2"]
    Ca = p["Ca"]
    Mg = p["Mg"]
    lactate = p["lactate"]
    chronicity = p["chronicity"]

    # --- Step 1: pH status ---
    if pH < 7.35:
        pH_status = "acidaemia"
    elif pH > 7.45:
        pH_status = "alkalaemia"
    else:
        pH_status = "normal"
    result["pH_status"] = pH_status

    # --- Step 2: Primary disorder ---
    if pH_status == "acidaemia":
        if HCO3 < 22:
            primary = "metabolic_acidosis"
        else:
            primary = "respiratory_acidosis"
    elif pH_status == "alkalaemia":
        if HCO3 > 26:
            primary = "metabolic_alkalosis"
        else:
            primary = "respiratory_alkalosis"
    else:
        primary = "normal"
    result["primary_disorder"] = primary

    # --- Step 3: Anion gap ---
    ag = Na - (Cl + HCO3)
    result["anion_gap"] = round(ag, 2)

    # --- Step 4: Corrected anion gap (albumin correction from DB) ---
    ag_corr = coeffs["ag_correction"]
    cag = ag + ag_corr["factor"] * (ag_corr["reference_albumin"] - albumin)
    result["corrected_anion_gap"] = round(cag, 2)

    # --- Step 5: AG classification ---
    ag_thresh = thresholds["anion_gap"]
    if cag > ag_thresh["upper"][0]:
        result["anion_gap_classification"] = "high"
    elif cag < ag_thresh["lower"][0]:
        result["anion_gap_classification"] = "low"
    else:
        result["anion_gap_classification"] = "normal"

    # --- Step 6: Delta ratio ---
    dr_thresh = thresholds["delta_ratio"]
    ref_ag = dr_thresh["reference_ag"][0]
    ref_hco3 = dr_thresh["reference_hco3"][0]

    if cag > ref_ag and HCO3 < ref_hco3:
        dr = (cag - ref_ag) / (ref_hco3 - HCO3)
        result["delta_ratio"] = round(dr, 2)
        if dr < dr_thresh["nagma_upper"][0]:
            result["delta_ratio_interpretation"] = "pure_nagma"
        elif dr < dr_thresh["mixed_upper"][0]:
            result["delta_ratio_interpretation"] = "mixed_hagma_nagma"
        elif dr <= dr_thresh["hagma_upper"][0]:
            result["delta_ratio_interpretation"] = "pure_hagma"
        else:
            result["delta_ratio_interpretation"] = "hagma_plus_alkalosis"
    elif cag > ref_ag and HCO3 >= ref_hco3:
        # Edge case: elevated AG with normal/high bicarbonate indicates
        # concurrent HAGMA + metabolic alkalosis
        result["delta_ratio"] = None
        result["delta_ratio_interpretation"] = "hagma_plus_alkalosis"
    else:
        result["delta_ratio"] = None
        result["delta_ratio_interpretation"] = None

    # --- Step 7: Compensation assessment ---
    if primary == "metabolic_acidosis":
        w = coeffs["winters_formula"]
        tol = coeffs["met_acid_compensation"]["tolerance"]
        exp_paco2 = w["hco3_multiplier"] * HCO3 + w["intercept"]
        result["expected_paco2"] = round(exp_paco2, 2)
        result["expected_hco3"] = None
        if PaCO2 > exp_paco2 + tol:
            result["compensation_status"] = "additional_respiratory_acidosis"
        elif PaCO2 < exp_paco2 - tol:
            result["compensation_status"] = "additional_respiratory_alkalosis"
        else:
            result["compensation_status"] = "appropriate"

    elif primary == "metabolic_alkalosis":
        ma = coeffs["met_alk_compensation"]
        exp_paco2 = ma["coefficient"] * HCO3 + ma["intercept"]
        result["expected_paco2"] = round(exp_paco2, 2)
        result["expected_hco3"] = None
        if PaCO2 > exp_paco2 + ma["tolerance"]:
            result["compensation_status"] = "additional_respiratory_acidosis"
        elif PaCO2 < exp_paco2 - ma["tolerance"]:
            result["compensation_status"] = "additional_respiratory_alkalosis"
        else:
            result["compensation_status"] = "appropriate"

    elif primary == "respiratory_acidosis":
        result["expected_paco2"] = None
        rc = coeffs["resp_compensation"]
        if chronicity == "acute":
            factor = coeffs["resp_compensation_acute"]["acidosis_factor"]
        else:
            factor = coeffs["resp_compensation_chronic"]["acidosis_factor"]
        exp_hco3 = rc["reference_hco3"] + factor * (PaCO2 - rc["reference_pco2"]) / rc["pco2_step"]
        result["expected_hco3"] = round(exp_hco3, 2)
        tol = rc["tolerance"]
        if HCO3 < exp_hco3 - tol:
            result["compensation_status"] = "additional_metabolic_acidosis"
        elif HCO3 > exp_hco3 + tol:
            result["compensation_status"] = "additional_metabolic_alkalosis"
        else:
            result["compensation_status"] = "appropriate"

    elif primary == "respiratory_alkalosis":
        result["expected_paco2"] = None
        rc = coeffs["resp_compensation"]
        if chronicity == "acute":
            factor = coeffs["resp_compensation_acute"]["alkalosis_factor"]
        else:
            factor = coeffs["resp_compensation_chronic"]["alkalosis_factor"]
        exp_hco3 = rc["reference_hco3"] - factor * (rc["reference_pco2"] - PaCO2) / rc["pco2_step"]
        result["expected_hco3"] = round(exp_hco3, 2)
        tol = rc["tolerance"]
        if HCO3 < exp_hco3 - tol:
            result["compensation_status"] = "additional_metabolic_acidosis"
        elif HCO3 > exp_hco3 + tol:
            result["compensation_status"] = "additional_metabolic_alkalosis"
        else:
            result["compensation_status"] = "appropriate"

    else:  # normal
        result["expected_paco2"] = None
        result["expected_hco3"] = None
        result["compensation_status"] = None

    # --- Step 8: Corrected sodium (hyperglycaemia correction) ---
    na_corr = coeffs["sodium_correction"]
    corr_na = Na + na_corr["factor"] * (glucose - na_corr["reference_glucose"]) / na_corr["reference_glucose"]
    result["corrected_sodium"] = round(corr_na, 2)

    # --- Step 9: Corrected potassium (pH correction from DB) ---
    k_corr = coeffs["potassium_correction"]
    corr_k = K - k_corr["factor"] * (k_corr["reference_pH"] - pH) / k_corr["pH_step"]
    result["corrected_potassium"] = round(corr_k, 2)

    # --- Step 10: Calculated osmolarity (includes ethanol when present) ---
    osm = coeffs["osmolarity"]
    calc_osm = osm["na_factor"] * Na + glucose + urea
    if ethanol_mg_dl is not None:
        ethanol_mmol = ethanol_mg_dl / osm["ethanol_divisor"]
        calc_osm += osm["ethanol_factor"] * ethanol_mmol
    result["calculated_osmolarity"] = round(calc_osm, 2)

    # --- Step 11: Osmolar gap ---
    osm_thresh = thresholds["osmolar_gap"]
    osm_gap = measured_osmolality - calc_osm
    result["osmolar_gap"] = round(osm_gap, 2)
    result["osmolar_gap_elevated"] = osm_gap > osm_thresh["upper"][0]

    # --- Step 12: Stewart approach - SIDa ---
    sid_coeffs = coeffs["sid_apparent"]
    sida = (Na + K + sid_coeffs["divalent_factor"] * Ca + sid_coeffs["divalent_factor"] * Mg) - (Cl + lactate)
    result["sid_apparent"] = round(sida, 2)

    # --- Step 13: Stewart approach - SIDe ---
    # A- approximation using Figge-Fencl equation: albumin * f(pH)
    ff = coeffs["figge_fencl"]
    a_minus = albumin * (ff["ph_coefficient"] * pH + ff["intercept"])
    side = HCO3 + a_minus
    result["sid_effective"] = round(side, 2)

    # --- Step 14: Strong Ion Gap ---
    sig = sida - side
    result["strong_ion_gap"] = round(sig, 2)

    # --- Step 15: P/F ratio and ARDS severity ---
    pf_thresh = thresholds["pf_ratio"]
    pf = PaO2 / FiO2
    result["pf_ratio"] = round(pf, 2)
    if pf < pf_thresh["severe"][0]:
        result["ards_severity"] = "severe"
    elif pf < pf_thresh["moderate"][0]:
        result["ards_severity"] = "moderate"
    elif pf < pf_thresh["mild"][0]:
        result["ards_severity"] = "mild"
    else:
        result["ards_severity"] = "none"

    # --- Step 16: Oxygen extraction ratio ---
    o2er_thresh = thresholds["o2er"]
    o2er = (SaO2 - SvO2) / SaO2
    result["o2_extraction_ratio"] = round(o2er, 2)
    if o2er > o2er_thresh["upper"][0]:
        result["o2er_status"] = "high"
    elif o2er < o2er_thresh["lower"][0]:
        result["o2er_status"] = "low"
    else:
        result["o2er_status"] = "normal"

    # --- Step 17: pCO2 gap ---
    pco2_thresh = thresholds["pco2_gap"]
    pco2_gap = PcvCO2 - PaCO2
    result["pco2_gap"] = round(pco2_gap, 2)
    if pco2_gap > pco2_thresh["upper"][0]:
        result["pco2_gap_status"] = "elevated"
    else:
        result["pco2_gap_status"] = "normal"

    return result


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.json>", file=sys.stderr)
        sys.exit(1)

    ensure_db()
    conn = sqlite3.connect(DB_PATH)
    coeffs = load_coefficients(conn)
    thresholds = load_thresholds(conn)
    conn.close()

    with open(sys.argv[1]) as f:
        patients = json.load(f)

    results = [assess_patient(p, coeffs, thresholds) for p in patients]

    with open(sys.argv[2], "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
