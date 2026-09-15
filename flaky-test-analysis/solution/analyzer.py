"""
Flaky Test Cross-Dataset Analysis Pipeline.

Processes IDoFT CSV datasets and produces a structured JSON report.

"""

import csv
import json
import os
import statistics
from collections import Counter
from pathlib import Path


DATA_DIR = "/app/data"
OUTPUT_PATH = "/app/analysis_report.json"


def load_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def compute_dataset_summary(pr_data, gr_data, py_data):
    return {
        "pr_data_rows": len(pr_data),
        "gr_data_rows": len(gr_data),
        "py_data_rows": len(py_data),
        "pr_unique_projects": len(set(r["Project URL"] for r in pr_data)),
        "gr_unique_projects": len(set(r["Project URL"] for r in gr_data)),
        "py_unique_projects": len(set(r["Project URL"] for r in py_data)),
    }


def compute_category_fix_rates(pr_data):
    cat_stats = {}
    for r in pr_data:
        raw_cat = r.get("Category") or ""
        if not raw_cat.strip():
            continue
        cats = [c.strip() for c in raw_cat.split(";")]
        status = r.get("Status") or ""
        for cat in cats:
            if not cat:
                continue
            if cat not in cat_stats:
                cat_stats[cat] = {"total": 0, "accepted": 0, "with_status": 0}
            cat_stats[cat]["total"] += 1
            if status != "":
                cat_stats[cat]["with_status"] += 1
            if status == "Accepted":
                cat_stats[cat]["accepted"] += 1

    result = {}
    for cat in sorted(cat_stats.keys()):
        d = cat_stats[cat]
        ws = d["with_status"]
        result[cat] = {
            "total": d["total"],
            "accepted": d["accepted"],
            "with_status": ws,
            "fix_rate": d["accepted"] / ws if ws > 0 else 0.0,
        }
    return result


def compute_order_dependency_graph(odr_data):
    total = len(odr_data)
    unique_od = set(r["OD-test"] for r in odr_data)
    unique_projects = set(r["Project URL"] for r in odr_data)
    victim_count = sum(1 for r in odr_data if r["OD-test-type"] == "victim")
    brittle_count = sum(1 for r in odr_data if r["OD-test-type"] == "brittle")

    # Build undirected graph
    edges = set()
    all_nodes = set()
    for r in odr_data:
        od = r["OD-test"]
        vp = r["Relevant-test(if it is VP/BSS)"]
        vpc = r.get("Relevant-test(if it is VPC)", "")
        tests_in_row = [t for t in [od, vp, vpc] if t]
        for t in tests_in_row:
            all_nodes.add(t)
        for i in range(len(tests_in_row)):
            for j in range(i + 1, len(tests_in_row)):
                a, b = tests_in_row[i], tests_in_row[j]
                edges.add((min(a, b), max(a, b)))

    # Connected components via union-find
    parent = {n: n for n in all_nodes}
    rank = {n: 0 for n in all_nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if rank[ra] < rank[rb]:
                ra, rb = rb, ra
            parent[rb] = ra
            if rank[ra] == rank[rb]:
                rank[ra] += 1

    for a, b in edges:
        union(a, b)

    comp_sizes = Counter(find(n) for n in all_nodes)

    return {
        "total_relationships": total,
        "unique_od_tests": len(unique_od),
        "unique_projects": len(unique_projects),
        "victim_count": victim_count,
        "brittle_count": brittle_count,
        "num_nodes": len(all_nodes),
        "num_edges": len(edges),
        "connected_components": len(comp_sizes),
        "largest_component_size": max(comp_sizes.values()),
    }


def compute_tic_fic_analysis(tic_fic_data):
    total = len(tic_fic_data)
    tic_true = sum(1 for r in tic_fic_data if r["TIC = FIC"] == "TRUE")
    tic_false = sum(1 for r in tic_fic_data if r["TIC = FIC"] == "FALSE")

    days = []
    for r in tic_fic_data:
        if r["TIC = FIC"] == "FALSE" and r["Days Between TIC-FIC"]:
            days.append(float(r["Days Between TIC-FIC"]))

    return {
        "total_tests": total,
        "tic_equals_fic_true": tic_true,
        "tic_equals_fic_false": tic_false,
        "mean_days_between": statistics.mean(days) if days else 0.0,
        "median_days_between": statistics.median(days) if days else 0.0,
        "max_days_between": max(days) if days else 0.0,
    }


def compute_tso_iso_analysis(tso_iso_data):
    total = len(tso_iso_data)
    sig_count = 0
    nonsig_count = 0
    suite_worse = 0
    suite_rates = []
    iso_rates = []

    for r in tso_iso_data:
        pval = float(r["P-Value"])
        total_suite = float(r["Total Runs In Test Suite"])
        passed_suite = float(r["Number of Times Test Passed In Test Suite"])
        total_iso = float(r["Total Runs In Isolation"])
        passed_iso = float(r["Number of Times Test Passed In Isolation"])

        sr = passed_suite / total_suite if total_suite > 0 else 0
        ir = passed_iso / total_iso if total_iso > 0 else 0
        suite_rates.append(sr)
        iso_rates.append(ir)

        if pval < 0.05:
            sig_count += 1
            if sr < ir:
                suite_worse += 1
        else:
            nonsig_count += 1

    return {
        "total_tests": total,
        "significant_count": sig_count,
        "nonsignificant_count": nonsig_count,
        "mean_suite_pass_rate": statistics.mean(suite_rates) if suite_rates else 0.0,
        "mean_isolation_pass_rate": statistics.mean(iso_rates) if iso_rates else 0.0,
        "suite_worse_count": suite_worse,
    }


def compute_cross_dataset_analysis(pr_data, odr_data, tso_iso_data):
    pr_projects = set(r["Project URL"] for r in pr_data)
    odr_projects = set(r["Project URL"] for r in odr_data)
    tso_projects = set(r["Project URL"] for r in tso_iso_data)
    common = sorted(pr_projects & odr_projects & tso_projects)

    # Build pr-data lookup
    pr_lookup = {}
    for r in pr_data:
        key = (
            r["Project URL"],
            r["Fully-Qualified Test Name (packageName.ClassName.methodName)"],
        )
        pr_lookup[key] = r["Status"]

    # Cross-reference OD-tests
    found_keys = set()
    accepted_keys = set()
    for r in odr_data:
        key = (r["Project URL"], r["OD-test"])
        if key in pr_lookup:
            found_keys.add(key)
            if pr_lookup[key] == "Accepted":
                accepted_keys.add(key)

    return {
        "projects_in_all_java_datasets": common,
        "unique_odr_tests_in_pr_data": len(found_keys),
        "unique_odr_tests_accepted": len(accepted_keys),
    }


def main():
    pr_data = load_csv("pr-data.csv")
    gr_data = load_csv("gr-data.csv")
    py_data = load_csv("py-data.csv")
    odr_data = load_csv("odr-tests.csv")
    tic_fic_data = load_csv("tic-fic-data.csv")
    tso_iso_data = load_csv("tso-iso-rates.csv")

    report = {
        "dataset_summary": compute_dataset_summary(pr_data, gr_data, py_data),
        "category_fix_rates": compute_category_fix_rates(pr_data),
        "order_dependency_graph": compute_order_dependency_graph(odr_data),
        "tic_fic_analysis": compute_tic_fic_analysis(tic_fic_data),
        "tso_iso_analysis": compute_tso_iso_analysis(tso_iso_data),
        "cross_dataset_analysis": compute_cross_dataset_analysis(
            pr_data, odr_data, tso_iso_data
        ),
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
