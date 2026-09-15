#!/usr/bin/env python3

"""
Reference solution: EPA EPI Suite KOCWIN v2.01 / BCFBAF v3.02 estimation
pipeline with dual JSON + SQLite output.

Equations and fragment corrections were extracted from the EPI Suite API
(https://episuite.dev/api/) by querying representative chemicals and
parsing the KOCWIN/BCFBAF computation output text.
"""

import json
import math
import sqlite3

# ============================================================
# Fragment correction tables (discovered from EPI Suite API)
# ============================================================

MCI_CORRECTIONS = {
    "aliphatic_alcohol": -1.3179,
    "nitrile": -0.6677,
    "ketone": -1.1290,
    "organic_acid": -1.6249,
    "n_aromatic_ring": -0.5225,
    "n_aliphatic": -0.2128,
    "triazine": -0.2257,
    "pyridine": -0.3080,
    "nitro": -0.4889,
    "ether_aromatic": -0.6791,
    "ester": -1.2970,
    "polychloro_aromatic": 0.3438,
    "aromatic_hydroxy": -0.0966,
}

KOW_CORRECTIONS = {
    "aliphatic_alcohol": -0.4114,
    "nitrile": 0.3922,
    "ketone": 0.1956,
    "organic_acid": -0.7694,
    "n_aromatic_ring": -0.0216,
    "n_aliphatic": -0.0218,
    "triazine": -0.1239,
    "pyridine": 0.1764,
    "nitro": 0.2191,
    "ether_aromatic": 0.0559,
    "ester": -0.0656,
    "polychloro_aromatic": 0.1444,
    "aromatic_hydroxy": 0.1668,
}

# ============================================================
# KOCWIN v2.01 equations
# ============================================================

MCI_SLOPE = 0.5213
MCI_INTERCEPT = 0.60

KOW_NP_SLOPE = 0.8679
KOW_NP_INTERCEPT = -0.0004

KOW_PA_SLOPE = 0.55313
KOW_PA_INTERCEPT = 0.9251

# ============================================================
# BCFBAF v3.02 equations
# ============================================================

BCF_STD_SLOPE = 0.6598
BCF_STD_INTERCEPT = -0.333

BCF_HIGH_SLOPE = -0.49
BCF_HIGH_INTERCEPT = 7.554

BCF_IONIC = 0.50


def sum_corrections(functional_groups, correction_table):
    """Sum fragment corrections for a list of functional groups (per-occurrence)."""
    total = 0.0
    for fg in functional_groups:
        if fg in correction_table:
            total += correction_table[fg]
    return total


def round_koc(value):
    """Round Koc: 1 decimal for <1000, nearest integer for >=1000."""
    if value < 1000:
        return round(value, 1)
    else:
        return round(value)


def process_chemical(chem):
    """Process a single chemical and return computed results."""
    cas = chem["cas"]
    logKow = chem["logKow_experimental"]
    mci = chem["mci"]
    is_acid = chem["is_organic_acid"]
    is_ionic = chem["is_ionic"]
    fgs = chem["functional_groups"]
    logKoc_exp = chem.get("logKoc_experimental")

    # --- MCI-based Koc ---
    base_mci = MCI_SLOPE * mci + MCI_INTERCEPT
    corr_mci = sum_corrections(fgs, MCI_CORRECTIONS)
    koc_mci_log = base_mci + corr_mci
    if koc_mci_log < 0.0:
        koc_mci_log = 0.0
    koc_mci = round_koc(10 ** koc_mci_log)

    # --- Kow-based Koc ---
    has_kow_corrections = len(fgs) > 0
    if is_acid or has_kow_corrections:
        base_kow = KOW_PA_SLOPE * logKow + KOW_PA_INTERCEPT
    else:
        base_kow = KOW_NP_SLOPE * logKow + KOW_NP_INTERCEPT

    corr_kow = sum_corrections(fgs, KOW_CORRECTIONS)
    koc_kow_log = base_kow + corr_kow
    koc_kow = round_koc(10 ** koc_kow_log)

    # --- BCF ---
    if is_ionic:
        bcf_log = BCF_IONIC
    elif logKow > 7.5:
        bcf_log = BCF_HIGH_SLOPE * logKow + BCF_HIGH_INTERCEPT
    else:
        bcf_log = BCF_STD_SLOPE * logKow + BCF_STD_INTERCEPT

    bcf_log = round(bcf_log, 2)
    bcf = round(10 ** bcf_log, 2)

    # --- Residuals ---
    if logKoc_exp is not None:
        koc_mci_residual = round(koc_mci_log - logKoc_exp, 4)
        koc_kow_residual = round(koc_kow_log - logKoc_exp, 4)
        if abs(koc_mci_residual) <= abs(koc_kow_residual):
            better_method = "mci"
        else:
            better_method = "kow"
    else:
        koc_mci_residual = None
        koc_kow_residual = None
        better_method = None

    return {
        "cas": cas,
        "koc_mci_log": round(koc_mci_log, 4),
        "koc_mci": koc_mci,
        "koc_kow_log": round(koc_kow_log, 4),
        "koc_kow": koc_kow,
        "bcf_log": bcf_log,
        "bcf": bcf,
        "koc_mci_residual": koc_mci_residual,
        "koc_kow_residual": koc_kow_residual,
        "better_method": better_method,
    }


def compute_summary(results):
    """Compute summary statistics."""
    with_data = [r for r in results if r["koc_mci_residual"] is not None]
    n = len(with_data)

    mci_sq = sum(r["koc_mci_residual"] ** 2 for r in with_data)
    kow_sq = sum(r["koc_kow_residual"] ** 2 for r in with_data)

    mci_rmse = round(math.sqrt(mci_sq / n), 4) if n > 0 else 0.0
    kow_rmse = round(math.sqrt(kow_sq / n), 4) if n > 0 else 0.0

    mci_wins = sum(1 for r in with_data if r["better_method"] == "mci")
    kow_wins = sum(1 for r in with_data if r["better_method"] == "kow")

    all_bcf = [r["bcf_log"] for r in results]
    mean_bcf_log = round(sum(all_bcf) / len(all_bcf), 4) if all_bcf else 0.0

    return {
        "cas": "SUMMARY",
        "mci_rmse": mci_rmse,
        "kow_rmse": kow_rmse,
        "mci_wins": mci_wins,
        "kow_wins": kow_wins,
        "mean_bcf_log": mean_bcf_log,
    }


def create_database(results_list):
    """Create SQLite database with equations, corrections, and compound results."""
    import os
    db_path = "/app/results.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)

    # equations table
    conn.execute("""
        CREATE TABLE equations (
            method TEXT,
            equation_type TEXT,
            coefficient_a REAL,
            coefficient_b REAL
        )
    """)
    conn.executemany(
        "INSERT INTO equations VALUES (?,?,?,?)",
        [
            ("mci_koc", "koc", MCI_SLOPE, MCI_INTERCEPT),
            ("kow_koc_nonpolar", "koc", KOW_NP_SLOPE, KOW_NP_INTERCEPT),
            ("kow_koc_polar", "koc", KOW_PA_SLOPE, KOW_PA_INTERCEPT),
            ("bcf_standard", "bcf", BCF_STD_SLOPE, BCF_STD_INTERCEPT),
        ]
    )

    # fragment_corrections table
    conn.execute("""
        CREATE TABLE fragment_corrections (
            method TEXT,
            fragment_name TEXT,
            correction_value REAL
        )
    """)
    for fg, val in MCI_CORRECTIONS.items():
        conn.execute(
            "INSERT INTO fragment_corrections VALUES (?,?,?)",
            ("mci", fg, val)
        )
    for fg, val in KOW_CORRECTIONS.items():
        conn.execute(
            "INSERT INTO fragment_corrections VALUES (?,?,?)",
            ("kow", fg, val)
        )

    # compound_results table
    conn.execute("""
        CREATE TABLE compound_results (
            cas TEXT,
            koc_mci_log REAL,
            koc_mci REAL,
            koc_kow_log REAL,
            koc_kow REAL,
            bcf_log REAL,
            bcf REAL,
            koc_mci_residual REAL,
            koc_kow_residual REAL,
            better_method TEXT
        )
    """)
    for r in results_list:
        if r["cas"] != "SUMMARY":
            conn.execute(
                "INSERT INTO compound_results VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    r["cas"], r["koc_mci_log"], r["koc_mci"],
                    r["koc_kow_log"], r["koc_kow"],
                    r["bcf_log"], r["bcf"],
                    r["koc_mci_residual"], r["koc_kow_residual"],
                    r["better_method"],
                )
            )

    conn.commit()
    conn.close()


def main():
    with open("/app/compounds.json") as f:
        chemicals = json.load(f)

    results = []
    for chem in chemicals:
        results.append(process_chemical(chem))

    summary = compute_summary(results)
    results.append(summary)

    # Write JSON output
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Write SQLite database
    create_database(results)

    print(f"Processed {len(chemicals)} chemicals.")
    print(f"MCI RMSE: {summary['mci_rmse']}, Kow RMSE: {summary['kow_rmse']}")
    print(f"MCI wins: {summary['mci_wins']}, Kow wins: {summary['kow_wins']}")
    print("Outputs: /app/results.json, /app/results.db")


if __name__ == "__main__":
    main()
