#!/usr/bin/env python3
"""
Privacy compliance remediation solver for MDPS v2.1.
Queries utility weights from SQLite, implements Earth Mover's Distance (not TVD),
dominance disclosure resistance, and weighted normalized certainty penalty.
Generates signed certification and populates the SQLite remediated table.
"""

import csv
import json
import math
import os
import sqlite3
import subprocess
import sys
import yaml
from collections import Counter, defaultdict
from itertools import product


def load_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


def load_hierarchy(filepath):
    """Load hierarchy CSV. Returns dict: original_value -> [level_0, level_1, ...]"""
    hierarchy = {}
    with open(filepath) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            hierarchy[row[0]] = row
    return hierarchy, len(header) - 1


# ---- Load configuration ----
with open('/app/compliance/requirements.yaml') as f:
    config = yaml.safe_load(f)

qi_attrs = config['quasi_identifiers']
sensitive_attr = config['sensitive_attribute']
ric_k = config['controls']['RIC']['parameters']['minimum_group_size']
adr_threshold = config['controls']['ADR']['parameters']['minimum_entropy']
dcr_threshold = config['controls']['DCR']['parameters']['maximum_distance']
ddr_threshold = config['controls']['DDR']['parameters']['maximum_frequency']
src_max_rate = config['controls']['SRC']['parameters']['maximum_suppression_rate']

# ---- Load utility weights from SQLite database ----
ipr_config = config['controls']['IPR']
db_path = ipr_config['utility_weights_source']
weight_query = ipr_config['utility_weights_query']

db_conn = sqlite3.connect(db_path)
cursor = db_conn.execute(weight_query)
utility_weights = {row[0]: row[1] for row in cursor.fetchall()}
print("Loaded utility weights from {}: {}".format(db_path, utility_weights))

# ---- Load dataset_id from provenance ----
cursor = db_conn.execute("SELECT value FROM data_provenance WHERE key = 'dataset_id'")
dataset_id = cursor.fetchone()[0]
print("Dataset ID from provenance: {}".format(dataset_id))
db_conn.close()

# ---- Load diagnosis severity ordering for EMD ----
diag_hier_path = config['controls']['DCR'].get('reference', '/app/data/diagnosis_hierarchy.json')
with open(diag_hier_path) as f:
    diag_hier = json.load(f)
severity_ordering = diag_hier['severity_ordering']

# ---- Load data ----
data = load_csv('/app/data/patients.csv')

# ---- Load hierarchies ----
hierarchies = {}
max_levels = {}
for attr in qi_attrs:
    path = os.path.join('/app/data/hierarchies', attr + '.csv')
    hierarchies[attr], max_levels[attr] = load_hierarchy(path)


def apply_generalization(data, gen_levels):
    """Apply global recoding at given generalization levels."""
    result = []
    for record in data:
        new_record = dict(record)
        for attr, level in zip(qi_attrs, gen_levels):
            if level > 0:
                orig_val = record[attr]
                if orig_val in hierarchies[attr]:
                    new_record[attr] = hierarchies[attr][orig_val][level]
                else:
                    new_record[attr] = '*'
        result.append(new_record)
    return result


def get_equivalence_classes(data):
    ecs = defaultdict(list)
    for record in data:
        key = tuple(record[a] for a in qi_attrs)
        ecs[key].append(record)
    return ecs


def check_ric(ecs, k):
    for records in ecs.values():
        if len(records) < k:
            return False
    return True


def check_adr(ecs, threshold):
    for records in ecs.values():
        values = [r[sensitive_attr] for r in records]
        counter = Counter(values)
        total = len(values)
        entropy = 0.0
        for count in counter.values():
            p = count / total
            if p > 0:
                entropy -= p * math.log(p)
        if entropy < threshold - 1e-10:
            return False
    return True


def compute_emd(ec_values, all_values, ordering):
    """Compute normalized Earth Mover's Distance (Wasserstein-1) for ordinal data.

    EMD = sum_{i=1}^{n-1} |CDF_ec(i) - CDF_all(i)| / (n - 1)
    """
    n = len(ordering)
    if n <= 1:
        return 0.0
    ec_total = len(ec_values)
    all_total = len(all_values)
    ec_counter = Counter(ec_values)
    all_counter = Counter(all_values)
    cdf_ec = 0.0
    cdf_all = 0.0
    total_diff = 0.0
    for i in range(n - 1):
        cat = ordering[i]
        cdf_ec += ec_counter.get(cat, 0) / ec_total
        cdf_all += all_counter.get(cat, 0) / all_total
        total_diff += abs(cdf_ec - cdf_all)
    return total_diff / (n - 1)


def check_dcr(ecs, data, threshold):
    all_values = [r[sensitive_attr] for r in data]
    for records in ecs.values():
        ec_values = [r[sensitive_attr] for r in records]
        emd = compute_emd(ec_values, all_values, severity_ordering)
        if emd > threshold + 1e-10:
            return False
    return True


def check_ddr(ecs, threshold):
    for records in ecs.values():
        values = [r[sensitive_attr] for r in records]
        counter = Counter(values)
        max_freq = max(counter.values()) / len(values)
        if max_freq > threshold + 1e-10:
            return False
    return True


def compute_per_attr_ncp(data_orig, data_gen, gen_levels):
    n = len(data_orig)
    per_attr = {}
    for i, attr in enumerate(qi_attrs):
        level = gen_levels[i]
        attr_ncp = 0.0
        if level > 0:
            hier = hierarchies[attr]
            all_orig_values = set(r[attr] for r in data_orig)
            n_values = len(all_orig_values)
            if n_values > 1:
                gen_groups = defaultdict(set)
                for v in all_orig_values:
                    if v in hier:
                        gen_groups[hier[v][level]].add(v)
                for record in data_gen:
                    gen_val = record[attr]
                    group_size = len(gen_groups.get(gen_val, set()))
                    attr_ncp += (group_size - 1) / (n_values - 1)
                attr_ncp /= n
        per_attr[attr] = round(attr_ncp, 6)
    return per_attr


def compute_weighted_ncp(per_attr_ncp, weights):
    return round(sum(weights[attr] * per_attr_ncp[attr] for attr in qi_attrs), 6)


def try_suppression(data, gen_levels, max_suppress):
    gen_data = apply_generalization(data, gen_levels)
    remaining_data = list(gen_data)
    remaining_orig = list(data)

    for iteration in range(max_suppress):
        ecs = get_equivalence_classes(remaining_data)
        all_values = [r[sensitive_attr] for r in remaining_data]
        violating_ec_keys = set()
        for key, records in ecs.items():
            values = [r[sensitive_attr] for r in records]
            counter = Counter(values)
            max_freq = max(counter.values()) / len(values)
            if max_freq > ddr_threshold + 1e-10:
                violating_ec_keys.add(key)
                continue
            emd = compute_emd(values, all_values, severity_ordering)
            if emd > dcr_threshold + 1e-10:
                violating_ec_keys.add(key)
                continue
            total = len(values)
            entropy = 0.0
            for count in counter.values():
                p = count / total
                if p > 0:
                    entropy -= p * math.log(p)
            if entropy < adr_threshold - 1e-10:
                violating_ec_keys.add(key)

        if not violating_ec_keys:
            break

        best_removal = None
        for key in violating_ec_keys:
            records = ecs[key]
            if len(records) <= ric_k:
                continue
            values = [r[sensitive_attr] for r in records]
            counter = Counter(values)
            most_common_val = counter.most_common(1)[0][0]
            for idx, r in enumerate(remaining_data):
                rec_key = tuple(r[a] for a in qi_attrs)
                if rec_key == key and r[sensitive_attr] == most_common_val:
                    best_removal = idx
                    break
            if best_removal is not None:
                break

        if best_removal is None:
            break

        remaining_data.pop(best_removal)
        remaining_orig.pop(best_removal)

    return remaining_data, remaining_orig


# ---- Exhaustive lattice search ----
print("Searching generalization lattice for optimal compliant anonymization...")
ranges = [range(max_levels[attr] + 1) for attr in qi_attrs]
total_nodes = 1
for attr in qi_attrs:
    total_nodes *= (max_levels[attr] + 1)
print("  Lattice size: {} nodes".format(total_nodes))

best_wncp = float('inf')
best_levels = None
best_data = None
best_orig_data = None
checked = 0

# Phase 1: Try pure generalization
for gen_levels in product(*ranges):
    checked += 1
    gen_data = apply_generalization(data, gen_levels)
    ecs = get_equivalence_classes(gen_data)

    if not check_ric(ecs, ric_k):
        continue
    if not check_adr(ecs, adr_threshold):
        continue
    if not check_dcr(ecs, gen_data, dcr_threshold):
        continue
    if not check_ddr(ecs, ddr_threshold):
        continue

    per_attr = compute_per_attr_ncp(data, gen_data, gen_levels)
    wncp = compute_weighted_ncp(per_attr, utility_weights)
    if wncp < best_wncp:
        best_wncp = wncp
        best_levels = gen_levels
        best_data = gen_data
        best_orig_data = data

print("  Phase 1 (pure generalization): checked {}/{} nodes".format(checked, total_nodes))

# Phase 2: If no pure generalization works, try with suppression
if best_levels is None:
    print("  No pure generalization satisfies all constraints. Trying suppression...")
    max_suppress = int(len(data) * src_max_rate)
    for gen_levels in product(*ranges):
        gen_data = apply_generalization(data, gen_levels)
        ecs = get_equivalence_classes(gen_data)

        if not check_ric(ecs, ric_k):
            continue

        suppressed_gen, suppressed_orig = try_suppression(data, gen_levels, max_suppress)
        ecs_s = get_equivalence_classes(suppressed_gen)

        if not check_ric(ecs_s, ric_k):
            continue
        if not check_adr(ecs_s, adr_threshold):
            continue
        if not check_dcr(ecs_s, suppressed_gen, dcr_threshold):
            continue
        if not check_ddr(ecs_s, ddr_threshold):
            continue

        per_attr = compute_per_attr_ncp(suppressed_orig, suppressed_gen, gen_levels)
        wncp = compute_weighted_ncp(per_attr, utility_weights)
        if wncp < best_wncp:
            best_wncp = wncp
            best_levels = gen_levels
            best_data = suppressed_gen
            best_orig_data = suppressed_orig
            print("    Found valid solution at {} with {} records suppressed".format(
                gen_levels, len(data) - len(suppressed_gen)))

if best_levels is None:
    print("ERROR: No valid generalization found!")
    sys.exit(1)

# ---- Generate outputs ----
os.makedirs('/app/output', exist_ok=True)

# remediated.csv
fieldnames = qi_attrs + [sensitive_attr]
with open('/app/output/remediated.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for record in best_data:
        writer.writerow({k: record[k] for k in fieldnames})

# Compute report metrics
ecs = get_equivalence_classes(best_data)
ec_sizes = [len(records) for records in ecs.values()]

all_values = [r[sensitive_attr] for r in best_data]

min_entropy = float('inf')
max_emd = 0.0
max_dom_freq = 0.0
for records in ecs.values():
    vals = [r[sensitive_attr] for r in records]
    n = len(vals)
    counter = Counter(vals)
    entropy = -sum((cnt / n) * math.log(cnt / n) for cnt in counter.values())
    min_entropy = min(min_entropy, entropy)

    emd = compute_emd(vals, all_values, severity_ordering)
    max_emd = max(max_emd, emd)

    dom_freq = max(counter.values()) / n
    max_dom_freq = max(max_dom_freq, dom_freq)

per_attr_ncp = compute_per_attr_ncp(best_orig_data, best_data, best_levels)
weighted_ncp = compute_weighted_ncp(per_attr_ncp, utility_weights)

# compliance_report.json
report = {
    "dataset_id": dataset_id,
    "generalization_levels": {
        attr: int(lvl) for attr, lvl in zip(qi_attrs, best_levels)
    },
    "num_records": len(best_data),
    "num_equivalence_classes": len(ecs),
    "min_ec_size": min(ec_sizes),
    "max_ec_size": max(ec_sizes),
    "avg_ec_size": round(sum(ec_sizes) / len(ec_sizes), 6),
    "weighted_ncp": weighted_ncp,
    "privacy_checks": {
        "RIC": {
            "satisfied": True,
            "min_group_size": min(ec_sizes)
        },
        "ADR": {
            "satisfied": True,
            "min_entropy": round(min_entropy, 6),
            "effective_l": round(math.exp(min_entropy), 6)
        },
        "DCR": {
            "satisfied": True,
            "max_emd": round(max_emd, 6),
            "metric": "earth_movers_distance"
        },
        "DDR": {
            "satisfied": True,
            "max_frequency": round(max_dom_freq, 6)
        }
    }
}
with open('/app/output/compliance_report.json', 'w') as f:
    json.dump(report, f, indent=2)

# utility_analysis.json
utility = {
    "weighted_ncp": weighted_ncp,
    "per_attribute_ncp": per_attr_ncp,
    "num_equivalence_classes": len(ecs),
    "generalization_levels": {
        attr: int(lvl) for attr, lvl in zip(qi_attrs, best_levels)
    }
}
with open('/app/output/utility_analysis.json', 'w') as f:
    json.dump(utility, f, indent=2)

# ---- Populate SQLite remediated table ----
print("Loading remediated data into SQLite database...")
db_conn = sqlite3.connect(db_path)
db_conn.execute('DELETE FROM remediated')
for record in best_data:
    db_conn.execute(
        'INSERT INTO remediated (age, zipcode, marital_status, education, diagnosis) '
        'VALUES (?,?,?,?,?)',
        (record['age'], record['zipcode'], record['marital_status'],
         record['education'], record[sensitive_attr])
    )
db_conn.commit()
cursor = db_conn.execute('SELECT COUNT(*) FROM remediated')
db_count = cursor.fetchone()[0]
db_conn.close()
print("  Inserted {} records into remediated table".format(db_count))

# ---- Generate signed compliance certification ----
print("Generating signed compliance certification...")
cert_result = subprocess.run([
    'python3', '/app/tools/certify.py',
    '--report', '/app/output/compliance_report.json',
    '--dataset', '/app/output/remediated.csv',
    '--key', '/app/compliance/signing.key',
    '--output', '/app/output/certification.json',
    '--db', db_path
], capture_output=True, text=True)

if cert_result.returncode != 0:
    print("ERROR: Certification failed:")
    print(cert_result.stderr)
    sys.exit(1)

print(cert_result.stdout)

print("\nRemediation complete.")
print("  Generalization levels: {}".format(
    dict(zip(qi_attrs, best_levels))))
print("  Records: {} (suppressed: {})".format(
    len(best_data), len(data) - len(best_data)))
print("  Weighted NCP: {:.6f}".format(weighted_ncp))
print("  Per-attribute NCP: {}".format(per_attr_ncp))
print("  Equivalence classes: {}".format(len(ecs)))
print("  Min EC size: {}".format(min(ec_sizes)))
print("  Min entropy: {:.6f} (effective l={:.2f})".format(
    min_entropy, math.exp(min_entropy)))
print("  Max EMD: {:.6f}".format(max_emd))
print("  Max dominance freq: {:.6f}".format(max_dom_freq))
