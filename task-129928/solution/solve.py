#!/usr/bin/env python3
"""
Solution for the PhysioNet Challenge 2026 multi-source evaluation pipeline.

Integrates EHR + claims diagnosis data via crosswalk table, deduplicates,
stratifies cohort, computes metrics with bootstrap CIs and site sub-analyses.
"""

import csv
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    roc_auc_score,
)


def load_qualifying_codes(sql_path):
    """Parse the SQL dump file to extract qualifying ICD codes (undotted)."""
    codes = set()
    with open(sql_path) as f:
        for line in f:
            m = re.match(
                r"INSERT\s+INTO\s+qualifying_icd_codes\s+VALUES\s*\(\s*'([^']+)'",
                line, re.IGNORECASE,
            )
            if m:
                codes.add(m.group(1))
    return codes


def normalize_icd(code):
    """Strip dots from ICD codes for comparison against reference table."""
    return code.replace(".", "").strip()


def load_site_thresholds(conn):
    """Load site-specific follow-up thresholds from site_parameters table."""
    c = conn.cursor()
    c.execute(
        "SELECT site_code, parameter_value FROM site_parameters "
        "WHERE parameter_name = 'min_followup_years'"
    )
    thresholds = {}
    for row in c:
        thresholds[row[0]] = float(row[1])
    return thresholds


def load_patients(conn):
    """Load PSG session data for all patients."""
    c = conn.cursor()
    c.execute(
        "SELECT patient_id, site_code, study_date, last_followup_date "
        "FROM psg_sessions"
    )
    patients = {}
    for row in c:
        patients[row[0]] = {
            "site": row[1],
            "psg_date": datetime.strptime(row[2], "%Y-%m-%d"),
            "last_visit": datetime.strptime(row[3], "%Y-%m-%d"),
        }
    return patients


def load_all_diagnoses(conn, qualifying_codes):
    """
    Load diagnoses from BOTH EHR and claims tables, link via crosswalk,
    normalize codes, filter for qualifying, and deduplicate.

    Returns dict: patient_id -> set of (normalized_code, date_str) tuples
    """
    # Load patient linkage (member_id -> patient_id)
    c = conn.cursor()
    c.execute("SELECT patient_id, member_id FROM patient_linkage")
    member_to_patient = {}
    for row in c:
        member_to_patient[row[1]] = row[0]

    # Collect qualifying diagnosis events using set for deduplication
    all_events = {}  # patient_id -> set of (normalized_code, date_str)

    # From EHR diagnoses
    c.execute("SELECT patient_id, icd_code, diagnosis_date FROM ehr_diagnoses")
    for row in c:
        pid = row[0]
        code = normalize_icd(row[1])
        if code in qualifying_codes:
            all_events.setdefault(pid, set()).add((code, row[2]))

    # From claims diagnoses (different column names!)
    c.execute("SELECT member_id, diagnosis_code, service_date FROM claims_diagnoses")
    for row in c:
        member_id = row[0]
        if member_id in member_to_patient:
            pid = member_to_patient[member_id]
            code = normalize_icd(row[1])
            if code in qualifying_codes:
                all_events.setdefault(pid, set()).add((code, row[2]))

    return all_events


def stratify_patients(patients, all_events, thresholds, default_threshold=7.0):
    """
    Assign each patient to Group 1, 2, or 3 per the challenge protocol.

    Group 1: >=2 qualifying events, at least one date in [3yr, 7yr] window,
             >=7 day gap between unique dates.
    Group 2: 0 qualifying events, follow-up >= site threshold.
    Group 3: all others.
    """
    three_years = timedelta(days=int(3 * 365.25))
    seven_years = timedelta(days=int(7 * 365.25))

    cohort = {}
    for pid, info in patients.items():
        psg = info["psg_date"]
        last_visit = info["last_visit"]
        site = info["site"]
        events = all_events.get(pid, set())

        # Group 1 check
        if len(events) >= 2:
            # Get unique dates from qualifying events
            unique_dates = sorted(set(
                datetime.strptime(d, "%Y-%m-%d") for _, d in events
            ))
            has_window = any(
                three_years <= (d - psg) <= seven_years for d in unique_dates
            )
            has_gap = (
                len(unique_dates) >= 2
                and (unique_dates[-1] - unique_dates[0]).days >= 7
            )
            if has_window and has_gap:
                cohort[pid] = 1
                continue

        # Group 2 check
        if len(events) == 0:
            threshold_years = thresholds.get(site, default_threshold)
            threshold_days = threshold_years * 365.25
            follow_up_days = (last_visit - psg).days
            if follow_up_days >= threshold_days:
                cohort[pid] = 2
                continue

        # Group 3
        cohort[pid] = 3

    return cohort


def compute_challenge_score(labels, outputs, fraction_capacity,
                            num_permutations=10000, seed=12345):
    """Capacity-constrained TPR from the PhysioNet reference scoring code."""
    n = len(labels)
    capacity = int(fraction_capacity * n)
    labels = np.asarray(labels, dtype=np.float64)
    outputs = np.asarray(outputs, dtype=np.float64)

    tp = np.zeros(num_permutations)
    fn = np.zeros(num_permutations)

    np.random.seed(seed)
    for i in range(num_permutations):
        perm_idx = np.random.permutation(np.arange(n))
        p_labels = labels[perm_idx]
        p_outputs = outputs[perm_idx]
        order = np.argsort(p_outputs, stable=True)[::-1]
        o_labels = p_labels[order]
        tp[i] = np.sum(o_labels[:capacity] == 1)
        fn[i] = np.sum(o_labels[capacity:] == 1)

    tp_m = np.mean(tp)
    fn_m = np.mean(fn)
    return tp_m / (tp_m + fn_m) if tp_m + fn_m > 0 else float("nan")


def bootstrap_ci(labels, probs, binary, sites,
                 n_boot=1000, seed=42, alpha=0.05):
    """
    Compute 95% bootstrap confidence intervals for evaluation metrics,
    using site-stratified resampling.
    """
    rng = np.random.RandomState(seed)
    unique_sites = np.unique(sites)

    metrics_boot = {"auroc": [], "auprc": [], "accuracy": [], "f1": []}

    for _ in range(n_boot):
        # Stratified bootstrap: resample within each site
        indices = []
        for s in unique_sites:
            site_idx = np.where(sites == s)[0]
            boot_idx = rng.choice(site_idx, size=len(site_idx), replace=True)
            indices.extend(boot_idx)
        indices = np.array(indices)

        b_labels = labels[indices]
        b_probs = probs[indices]
        b_binary = binary[indices]

        # Skip if only one class in bootstrap sample
        if len(np.unique(b_labels)) < 2:
            continue

        metrics_boot["auroc"].append(roc_auc_score(b_labels, b_probs))
        metrics_boot["auprc"].append(average_precision_score(b_labels, b_probs))
        metrics_boot["accuracy"].append(accuracy_score(b_labels, b_binary))
        metrics_boot["f1"].append(f1_score(b_labels, b_binary, pos_label=1))

    ci = {}
    for metric, values in metrics_boot.items():
        if values:
            ci[metric] = {
                "lower": float(np.percentile(values, 100 * alpha / 2)),
                "upper": float(np.percentile(values, 100 * (1 - alpha / 2))),
            }
        else:
            ci[metric] = {"lower": float("nan"), "upper": float("nan")}

    return ci


def main():
    data_dir = "/app/data"
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    db_path = os.path.join(data_dir, "clinical.db")
    sql_path = os.path.join(data_dir, "qualifying_codes.sql")
    jsonl_path = os.path.join(data_dir, "model_output.jsonl")

    # 1. Load qualifying ICD codes from SQL dump
    ref_codes = load_qualifying_codes(sql_path)

    # 2. Connect to database
    conn = sqlite3.connect(db_path)

    # 3. Load data from multiple tables
    patients = load_patients(conn)
    thresholds = load_site_thresholds(conn)
    all_events = load_all_diagnoses(conn, ref_codes)
    conn.close()

    # 4. Stratify patients into groups
    cohort = stratify_patients(patients, all_events, thresholds)

    # 5. Write cohort assignments
    with open(os.path.join(output_dir, "cohort.csv"), "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["PatientID", "Group"])
        for pid in sorted(cohort.keys()):
            writer.writerow([pid, cohort[pid]])

    # 6. Load model predictions from JSONL
    preds = {}
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            preds[rec["patient_id"]] = {
                "binary": int(rec["prediction"]),
                "probability": float(rec["confidence"]),
            }

    # 7. Build scored arrays (Group 1 = label 1, Group 2 = label 0)
    scored_pids = sorted([pid for pid, g in cohort.items() if g in (1, 2)])
    labels = np.array([1 if cohort[pid] == 1 else 0 for pid in scored_pids])
    probs = np.array([preds[pid]["probability"] for pid in scored_pids])
    binary = np.array([preds[pid]["binary"] for pid in scored_pids])
    sites = np.array([patients[pid]["site"] for pid in scored_pids])

    # 8. Compute overall metrics
    overall = {
        "auroc": float(roc_auc_score(labels, probs)),
        "auprc": float(average_precision_score(labels, probs)),
        "accuracy": float(accuracy_score(labels, binary)),
        "f1": float(f1_score(labels, binary, pos_label=1)),
        "challenge_score_005": float(
            compute_challenge_score(labels, probs, fraction_capacity=0.05)
        ),
        "challenge_score_020": float(
            compute_challenge_score(labels, probs, fraction_capacity=0.20)
        ),
    }

    # 9. Compute bootstrap confidence intervals (site-stratified)
    cis = bootstrap_ci(labels, probs, binary, sites, n_boot=1000, seed=42)

    # 10. Compute per-site metrics
    site_metrics = {}
    unique_sites = sorted(set(patients[pid]["site"] for pid in scored_pids))
    for s in unique_sites:
        s_mask = sites == s
        s_labels = labels[s_mask]
        s_probs = probs[s_mask]
        n_g1 = int(np.sum(s_labels == 1))
        n_g2 = int(np.sum(s_labels == 0))
        site_entry = {"n_group1": n_g1, "n_group2": n_g2}
        if n_g1 > 0 and n_g2 > 0:
            site_entry["auroc"] = float(roc_auc_score(s_labels, s_probs))
        site_metrics[s] = site_entry

    # 11. Build and write output
    output = {
        "cohort_summary": {
            "group_1": sum(1 for v in cohort.values() if v == 1),
            "group_2": sum(1 for v in cohort.values() if v == 2),
            "group_3": sum(1 for v in cohort.values() if v == 3),
        },
        "overall_metrics": overall,
        "confidence_intervals": cis,
        "site_metrics": site_metrics,
    }

    with open(os.path.join(output_dir, "scores.json"), "w") as f:
        json.dump(output, f, indent=2)

    print("Pipeline complete.")
    print(f"Cohort: {output['cohort_summary']}")
    print(f"Overall: {json.dumps(overall, indent=2)}")


if __name__ == "__main__":
    main()
