#!/usr/bin/env python3
"""Generate task environment: patient data, hierarchies, broken anonymization,
compliance docs, SQLite privacy database, and signing key."""

import random
import csv
import json
import math
import os
import hashlib
import sqlite3
from collections import Counter, defaultdict

random.seed(42)

os.makedirs('/app/data/hierarchies', exist_ok=True)
os.makedirs('/app/compliance', exist_ok=True)

qi_attrs = ['age', 'zipcode', 'marital_status', 'education']
sensitive_attr = 'diagnosis'

# ---- Patient data with skewed diagnosis distribution ----
ages = list(range(25, 56))
zipcodes = [
    '10115', '10117', '10178',
    '10243', '10247',
    '20095', '20099', '20144',
    '30159', '30163'
]
marital_statuses = ['single', 'married', 'divorced', 'widowed', 'separated']
education_levels = ['HS-grad', 'some-college', 'bachelors', 'masters', 'doctorate']

# Skewed distribution — makes EMD-based conformance non-trivial
diagnoses = ['flu', 'asthma', 'bronchitis', 'hypertension', 'diabetes']
diagnosis_weights = [0.28, 0.16, 0.12, 0.24, 0.20]

records = []
for _ in range(250):
    r_val = random.random()
    cumulative = 0.0
    chosen = diagnoses[-1]
    for d, w in zip(diagnoses, diagnosis_weights):
        cumulative += w
        if r_val < cumulative:
            chosen = d
            break
    records.append({
        'age': str(random.choice(ages)),
        'zipcode': random.choice(zipcodes),
        'marital_status': random.choice(marital_statuses),
        'education': random.choice(education_levels),
        'diagnosis': chosen
    })

with open('/app/data/patients.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['age', 'zipcode', 'marital_status', 'education', 'diagnosis'])
    w.writeheader()
    w.writerows(records)

# ---- Diagnosis semantic hierarchy (ordinal severity ordering for EMD) ----
diag_hier = {
    "severity_ordering": diagnoses,
    "categories": {
        "respiratory": ["flu", "asthma", "bronchitis"],
        "cardiovascular": ["hypertension"],
        "metabolic": ["diabetes"]
    },
    "severity_levels": {
        "flu": 1,
        "asthma": 2,
        "bronchitis": 3,
        "hypertension": 4,
        "diabetes": 5
    },
    "description": "Ordinal severity ordering for Earth Movers Distance computation per MDPS v2.1 DCR"
}
with open('/app/data/diagnosis_hierarchy.json', 'w') as f:
    json.dump(diag_hier, f, indent=2)

# ---- QI Hierarchies ----
age_hier = {}
with open('/app/data/hierarchies/age.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['level_0', 'level_1', 'level_2', 'level_3', 'level_4'])
    for a in range(18, 80):
        b5 = (a // 5) * 5
        b10 = (a // 10) * 10
        b20 = (a // 20) * 20
        row = [str(a), '{}-{}'.format(b5, b5 + 4), '{}-{}'.format(b10, b10 + 9),
               '{}-{}'.format(b20, b20 + 19), '*']
        w.writerow(row)
        age_hier[str(a)] = row

zip_hier = {}
with open('/app/data/hierarchies/zipcode.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['level_0', 'level_1', 'level_2', 'level_3', 'level_4'])
    for zc in zipcodes:
        row = [zc, zc[:4] + '*', zc[:3] + '**', zc[:2] + '***', '*']
        w.writerow(row)
        zip_hier[zc] = row

ms_map = {
    'single': 'never-married', 'separated': 'never-married',
    'married': 'ever-married', 'divorced': 'ever-married', 'widowed': 'ever-married'
}
ms_hier = {}
with open('/app/data/hierarchies/marital_status.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['level_0', 'level_1', 'level_2'])
    for ms, cat in ms_map.items():
        row = [ms, cat, '*']
        w.writerow(row)
        ms_hier[ms] = row

edu_map = {
    'HS-grad': 'secondary', 'some-college': 'secondary',
    'bachelors': 'higher', 'masters': 'higher', 'doctorate': 'higher'
}
edu_hier = {}
with open('/app/data/hierarchies/education.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['level_0', 'level_1', 'level_2'])
    for edu, cat in edu_map.items():
        row = [edu, cat, '*']
        w.writerow(row)
        edu_hier[edu] = row

# ---- SQLite Privacy Database ----
db_path = '/app/data/privacy.db'
conn = sqlite3.connect(db_path)

conn.execute('''CREATE TABLE patients (
    record_id INTEGER PRIMARY KEY,
    age TEXT NOT NULL,
    zipcode TEXT NOT NULL,
    marital_status TEXT NOT NULL,
    education TEXT NOT NULL,
    diagnosis TEXT NOT NULL
)''')
for i, r in enumerate(records):
    conn.execute('INSERT INTO patients VALUES (?,?,?,?,?,?)',
        (i, r['age'], r['zipcode'], r['marital_status'], r['education'], r['diagnosis']))

# Utility weights — only available here, not in the YAML config
conn.execute('''CREATE TABLE utility_weights (
    attribute TEXT PRIMARY KEY,
    weight REAL NOT NULL,
    justification TEXT
)''')
weights_data = [
    ('age', 0.35, 'High re-identification risk due to narrow age ranges in clinical populations'),
    ('zipcode', 0.30, 'Geographic quasi-identifier with direct linkage potential'),
    ('marital_status', 0.20, 'Moderate linkage risk when combined with other demographics'),
    ('education', 0.15, 'Lower direct re-identification risk but contextually sensitive')
]
for wd in weights_data:
    conn.execute('INSERT INTO utility_weights VALUES (?,?,?)', wd)

# Data provenance — needed for compliance certification
conn.execute('''CREATE TABLE data_provenance (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)''')
provenance_entries = [
    ('dataset_id', 'MDPS-DS-2024-0847'),
    ('source_system', 'EHR-v4.2'),
    ('extraction_date', '2024-10-01'),
    ('classification', 'PHI-Level-3'),
    ('custodian', 'Privacy Office')
]
for pe in provenance_entries:
    conn.execute('INSERT INTO data_provenance VALUES (?,?)', pe)

# Empty remediated table — must be populated after anonymization
conn.execute('''CREATE TABLE remediated (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    age TEXT NOT NULL,
    zipcode TEXT NOT NULL,
    marital_status TEXT NOT NULL,
    education TEXT NOT NULL,
    diagnosis TEXT NOT NULL
)''')

conn.commit()
conn.close()

# ---- Signing key for compliance certification ----
signing_key = hashlib.sha256(b"MDPS-DS-2024-0847-compliance-key").hexdigest()
with open('/app/compliance/signing.key', 'w') as f:
    f.write(signing_key)

# ---- Broken released.csv (partially generalized, fails compliance) ----
hierarchies_all = {
    'age': age_hier, 'zipcode': zip_hier,
    'marital_status': ms_hier, 'education': edu_hier
}
gen_levels_broken = [1, 1, 0, 0]

released = []
for r in records:
    new_r = dict(r)
    for attr, level in zip(qi_attrs, gen_levels_broken):
        if level > 0:
            new_r[attr] = hierarchies_all[attr][r[attr]][level]
    released.append(new_r)

with open('/app/data/released.csv', 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['age', 'zipcode', 'marital_status', 'education', 'diagnosis'])
    w.writeheader()
    w.writerows(released)

# ---- Compliance requirements (YAML) ----
requirements_yaml = """\
# Medical Data Privacy Standard (MDPS) v2.1
# Compliance Requirements for Protected Health Information

compliance_framework: "MDPS v2.1"
classification: "PHI-Level-3"

quasi_identifiers:
  - age
  - zipcode
  - marital_status
  - education
sensitive_attribute: diagnosis

controls:
  RIC:
    name: "Re-identification Control"
    description: >
      No individual shall be uniquely distinguishable within any equivalence
      class formed by the quasi-identifier attributes. Each equivalence class
      must contain a minimum number of records to prevent singling-out attacks.
    parameters:
      minimum_group_size: 5
    severity: critical

  ADR:
    name: "Attribute Diversity Requirement"
    description: >
      The sensitive attribute values within each equivalence class must exhibit
      sufficient diversity to prevent attribute disclosure attacks. Diversity
      is measured using Shannon entropy (natural logarithm base) of the
      sensitive attribute distribution within each equivalence class.
    parameters:
      minimum_entropy: 1.0986
    severity: critical

  DCR:
    name: "Distribution Conformance Requirement"
    description: >
      The distribution of sensitive attribute values within each equivalence
      class must not deviate excessively from the overall population distribution.
      Deviation is measured using the Earth Mover's Distance (Wasserstein-1
      metric) computed over the ordinal severity ordering defined in the
      diagnosis semantic hierarchy at the path given in the reference field.
      The EMD for ordinal attributes is calculated as the normalized L1 distance
      between the cumulative distribution functions of the local
      (per-equivalence-class) and global sensitive attribute distributions,
      normalized by (n-1) where n is the number of ordered categories.
    parameters:
      maximum_distance: 0.15
    severity: critical
    reference: "/app/data/diagnosis_hierarchy.json"

  DDR:
    name: "Dominance Disclosure Resistance"
    description: >
      No single sensitive attribute value shall have a relative frequency
      exceeding the specified threshold within any equivalence class. This
      control prevents attribute disclosure attacks where an adversary can
      infer the sensitive value with high probability by observing that a
      dominant proportion of records in the equivalence class share the same
      sensitive value.
    parameters:
      maximum_frequency: 0.55
    severity: critical

  SRC:
    name: "Suppression Rate Control"
    description: >
      Record suppression is a permitted privacy-preserving transformation
      when individual records cannot be safely included in any equivalence
      class. The fraction of original records suppressed must not exceed the
      specified maximum rate.
    parameters:
      maximum_suppression_rate: 0.03
    severity: critical

  IPR:
    name: "Information Preservation Requirement"
    description: >
      Anonymization transformations should preserve maximum data utility.
      Information loss is measured as a weighted normalized certainty penalty
      across all quasi-identifier attributes, where each attribute's
      contribution is scaled by its information sensitivity weight.
      Attribute weights are maintained in the privacy database and must be
      queried at runtime.
    parameters:
      maximum_acceptable_loss: 0.85
    severity: advisory
    utility_weights_source: "/app/data/privacy.db"
    utility_weights_query: "SELECT attribute, weight FROM utility_weights"

transformation_constraints:
  method: "global_recoding"
  consistency: >
    All records sharing the same original quasi-identifier value must be
    transformed to the same generalized value (global consistency).
  hierarchies_directory: "/app/data/hierarchies/"
  sensitive_preservation: >
    The sensitive attribute must not be modified during anonymization.

certification:
  required: true
  tool: "/app/tools/certify.py"
  signing_key: "/app/compliance/signing.key"
  provenance_source: "/app/data/privacy.db"
  description: >
    A signed compliance certification must be generated using the certification
    tool after all privacy controls are verified. The certification provides
    cryptographic assurance that the compliance report has not been tampered with.
"""

with open('/app/compliance/requirements.yaml', 'w') as f:
    f.write(requirements_yaml)

# ---- Compute violations for audit findings ----
ecs = defaultdict(list)
for r in released:
    key = tuple(r[a] for a in qi_attrs)
    ecs[key].append(r)

small_ecs = sum(1 for recs in ecs.values() if len(recs) < 5)
low_div_ecs = 0
high_tvd_ecs = 0
high_dom_ecs = 0

all_diags = [r['diagnosis'] for r in released]
total_n = len(all_diags)
overall = Counter(all_diags)
cats = sorted(overall.keys())
overall_dist = {c: n / total_n for c, n in overall.items()}

for recs in ecs.values():
    diags = [r['diagnosis'] for r in recs]
    c = Counter(diags)
    n = len(diags)
    entropy = -sum((cnt / n) * math.log(cnt / n) for cnt in c.values() if cnt > 0)
    if entropy < 1.0986:
        low_div_ecs += 1
    ec_dist = {cat: c.get(cat, 0) / n for cat in cats}
    tvd = sum(abs(ec_dist.get(cat, 0) - overall_dist.get(cat, 0)) for cat in cats) / 2
    if tvd > 0.2:
        high_tvd_ecs += 1
    max_freq = max(c.values()) / n
    if max_freq > 0.55:
        high_dom_ecs += 1

audit_findings = {
    "audit_id": "MDPS-2024-0847",
    "dataset": "/app/data/released.csv",
    "framework": "MDPS v2.1",
    "status": "FAILED",
    "timestamp": "2024-11-15T14:32:00Z",
    "methodology": "Assessment performed using risk_assessor.py v1.4.2",
    "findings": [
        {
            "code": "RIC-FAIL-003",
            "control": "RIC",
            "severity": "critical",
            "message": "{} equivalence classes fall below minimum group size threshold".format(small_ecs),
            "details": "Multiple groups contain fewer records than required, enabling potential singling-out attacks"
        },
        {
            "code": "ADR-FAIL-012",
            "control": "ADR",
            "severity": "critical",
            "message": "{} equivalence classes below entropy threshold".format(low_div_ecs),
            "details": "Groups with homogeneous sensitive attribute distributions present attribute disclosure risk"
        },
        {
            "code": "DCR-WARN-015",
            "control": "DCR",
            "severity": "critical",
            "message": "{} equivalence classes exceed distribution distance threshold (assessed via total variation distance)".format(high_tvd_ecs),
            "details": "Assessment used total variation distance; verify against current MDPS specification for required distance metric"
        },
        {
            "code": "DDR-FAIL-001",
            "control": "DDR",
            "severity": "critical",
            "message": "{} equivalence classes exceed dominance frequency threshold".format(high_dom_ecs),
            "details": "Groups where a single diagnosis value dominates present probabilistic inference risk"
        },
        {
            "code": "IPR-SKIP-001",
            "control": "IPR",
            "severity": "info",
            "message": "Utility assessment skipped due to critical control failures"
        }
    ],
    "recommendation": "Full re-anonymization required. Current release must be recalled.",
    "note": "Use the privacy risk assessment tool at /app/tools/risk_assessor.py for detailed analysis"
}

with open('/app/compliance/audit_findings.json', 'w') as f:
    json.dump(audit_findings, f, indent=2)

print("Generated {} patient records".format(len(records)))
print("Generated broken released.csv with {} ECs".format(len(ecs)))
print("Generated SQLite database at {}".format(db_path))
print("Violations: {} small ECs, {} low diversity, {} high TVD, {} high dominance".format(
    small_ecs, low_div_ecs, high_tvd_ecs, high_dom_ecs))
