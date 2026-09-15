#!/usr/bin/env python3
"""
Compute Charlson Comorbidity Index and clinical risk stratification
from MIMIC-III demo data in SQLite.

Adapts the MIMIC-IV BigQuery reference SQL to MIMIC-III SQLite:
- BigQuery GREATEST() -> SQLite MAX()
- MIMIC-IV icd_version + icd_code -> MIMIC-III icd9_code only
- MIMIC-IV derived age table -> compute from DOB + admittime
- Handle MIMIC-III age deidentification (>89 -> DOB shifted ~300 years)
"""

import sqlite3
import json
import os

DB_PATH = "/app/mimic3_demo.db"
OUTPUT_DIR = "/app/output"
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "results.json")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# ============================================================
# Part 1: Charlson Comorbidity Index
# Adapted from MIMIC-IV BigQuery -> MIMIC-III SQLite
# Using Quan (2005) ICD-9-CM coding algorithms
# with Charlson (1987) original weights
# ============================================================

CHARLSON_SQL = """
WITH com AS (
    SELECT
        ad.hadm_id,
        -- Myocardial infarction
        MAX(CASE WHEN SUBSTR(d.icd9_code, 1, 3) IN ('410', '412')
            THEN 1 ELSE 0 END) AS myocardial_infarct,
        -- Congestive heart failure
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) = '428'
            OR SUBSTR(d.icd9_code, 1, 5) IN (
                '39891','40201','40211','40291','40401','40403',
                '40411','40413','40491','40493')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '4254'
                AND SUBSTR(d.icd9_code, 1, 4) <= '4259')
            THEN 1 ELSE 0 END) AS congestive_heart_failure,
        -- Peripheral vascular disease
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('440', '441')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '0930','4373','4471','5571','5579','V434')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '4431'
                AND SUBSTR(d.icd9_code, 1, 4) <= '4439')
            THEN 1 ELSE 0 END) AS peripheral_vascular_disease,
        -- Cerebrovascular disease
        MAX(CASE WHEN
            (SUBSTR(d.icd9_code, 1, 3) >= '430'
             AND SUBSTR(d.icd9_code, 1, 3) <= '438')
            OR SUBSTR(d.icd9_code, 1, 5) = '36234'
            THEN 1 ELSE 0 END) AS cerebrovascular_disease,
        -- Dementia
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) = '290'
            OR SUBSTR(d.icd9_code, 1, 4) IN ('2941', '3312')
            THEN 1 ELSE 0 END) AS dementia,
        -- Chronic pulmonary disease
        MAX(CASE WHEN
            (SUBSTR(d.icd9_code, 1, 3) >= '490'
             AND SUBSTR(d.icd9_code, 1, 3) <= '505')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '4168','4169','5064','5081','5088')
            THEN 1 ELSE 0 END) AS chronic_pulmonary_disease,
        -- Rheumatic disease
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) = '725'
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '4465','7100','7101','7102','7103','7104',
                '7140','7141','7142','7148')
            THEN 1 ELSE 0 END) AS rheumatic_disease,
        -- Peptic ulcer disease
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('531', '532', '533', '534')
            THEN 1 ELSE 0 END) AS peptic_ulcer_disease,
        -- Mild liver disease
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('570', '571')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '0706','0709','5733','5734','5738','5739','V427')
            OR SUBSTR(d.icd9_code, 1, 5) IN (
                '07022','07023','07032','07033','07044','07054')
            THEN 1 ELSE 0 END) AS mild_liver_disease,
        -- Diabetes without chronic complication
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 4) IN (
                '2500','2501','2502','2503','2508','2509')
            THEN 1 ELSE 0 END) AS diabetes_without_cc,
        -- Diabetes with chronic complication
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 4) IN ('2504','2505','2506','2507')
            THEN 1 ELSE 0 END) AS diabetes_with_cc,
        -- Hemiplegia or paraplegia
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('342', '343')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '3341','3440','3441','3442','3443',
                '3444','3445','3446','3449')
            THEN 1 ELSE 0 END) AS paraplegia,
        -- Renal disease
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('582', '585', '586', 'V56')
            OR SUBSTR(d.icd9_code, 1, 4) IN ('5880','V420','V451')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '5830'
                AND SUBSTR(d.icd9_code, 1, 4) <= '5837')
            OR SUBSTR(d.icd9_code, 1, 5) IN (
                '40301','40311','40391','40402','40403',
                '40412','40413','40492','40493')
            THEN 1 ELSE 0 END) AS renal_disease,
        -- Any malignancy (excluding skin)
        MAX(CASE WHEN
            (SUBSTR(d.icd9_code, 1, 3) >= '140'
             AND SUBSTR(d.icd9_code, 1, 3) <= '172')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '1740'
                AND SUBSTR(d.icd9_code, 1, 4) <= '1958')
            OR (SUBSTR(d.icd9_code, 1, 3) >= '200'
                AND SUBSTR(d.icd9_code, 1, 3) <= '208')
            OR SUBSTR(d.icd9_code, 1, 4) = '2386'
            THEN 1 ELSE 0 END) AS malignant_cancer,
        -- Severe liver disease
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 4) IN ('4560','4561','4562')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '5722'
                AND SUBSTR(d.icd9_code, 1, 4) <= '5728')
            THEN 1 ELSE 0 END) AS severe_liver_disease,
        -- Metastatic solid tumor
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('196', '197', '198', '199')
            THEN 1 ELSE 0 END) AS metastatic_solid_tumor,
        -- AIDS/HIV
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('042', '043', '044')
            THEN 1 ELSE 0 END) AS aids
    FROM admissions ad
    LEFT JOIN diagnoses_icd d ON ad.hadm_id = d.hadm_id
    GROUP BY ad.hadm_id
),
ag AS (
    SELECT
        ad.hadm_id,
        CASE
            WHEN CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER) > 89 THEN 91
            ELSE CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER)
        END AS age,
        CASE
            WHEN CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER) > 89 THEN 4
            WHEN CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER) <= 50 THEN 0
            WHEN CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER) <= 60 THEN 1
            WHEN CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER) <= 70 THEN 2
            WHEN CAST((julianday(ad.admittime) - julianday(p.dob)) / 365.25 AS INTEGER) <= 80 THEN 3
            ELSE 4
        END AS age_score
    FROM admissions ad
    JOIN patients p ON ad.subject_id = p.subject_id
)
SELECT
    ad.subject_id,
    ad.hadm_id,
    ag.age,
    ag.age_score,
    ad.hospital_expire_flag,
    -- CCI without age (Charlson 1987 weights with override rules)
    com.myocardial_infarct + com.congestive_heart_failure
    + com.peripheral_vascular_disease + com.cerebrovascular_disease
    + com.dementia + com.chronic_pulmonary_disease
    + com.rheumatic_disease + com.peptic_ulcer_disease
    + MAX(com.mild_liver_disease, 3 * com.severe_liver_disease)
    + MAX(2 * com.diabetes_with_cc, com.diabetes_without_cc)
    + MAX(2 * com.malignant_cancer, 6 * com.metastatic_solid_tumor)
    + 2 * com.paraplegia + 2 * com.renal_disease
    + 6 * com.aids AS cci,
    -- CCI with age score
    ag.age_score
    + com.myocardial_infarct + com.congestive_heart_failure
    + com.peripheral_vascular_disease + com.cerebrovascular_disease
    + com.dementia + com.chronic_pulmonary_disease
    + com.rheumatic_disease + com.peptic_ulcer_disease
    + MAX(com.mild_liver_disease, 3 * com.severe_liver_disease)
    + MAX(2 * com.diabetes_with_cc, com.diabetes_without_cc)
    + MAX(2 * com.malignant_cancer, 6 * com.metastatic_solid_tumor)
    + 2 * com.paraplegia + 2 * com.renal_disease
    + 6 * com.aids AS cci_age_adjusted
FROM admissions ad
LEFT JOIN com ON ad.hadm_id = com.hadm_id
LEFT JOIN ag ON ad.hadm_id = ag.hadm_id
ORDER BY ad.hadm_id
"""

rows = cur.execute(CHARLSON_SQL).fetchall()
col_names = [d[0] for d in cur.description]

cci_per_admission = {}
cci_age_adj = {}
admission_data = []

for row in rows:
    d = dict(zip(col_names, row))
    hadm_id = str(d["hadm_id"])
    cci_per_admission[hadm_id] = d["cci"]
    cci_age_adj[hadm_id] = d["cci_age_adjusted"]
    admission_data.append(d)

# ============================================================
# Part 2: 30-day readmission
# ============================================================

READMISSION_SQL = """
SELECT
    a1.hadm_id,
    a1.subject_id,
    a1.dischtime,
    MIN(a2.admittime) AS next_admittime,
    CAST((julianday(MIN(a2.admittime)) - julianday(a1.dischtime)) AS REAL) AS days_to_readmit
FROM admissions a1
LEFT JOIN admissions a2
    ON a1.subject_id = a2.subject_id
    AND a2.admittime > a1.dischtime
    AND a1.hadm_id != a2.hadm_id
GROUP BY a1.hadm_id
ORDER BY a1.hadm_id
"""

readmit_rows = cur.execute(READMISSION_SQL).fetchall()
readmission_30day = {}
for row in readmit_rows:
    hadm_id = str(row[0])
    days = row[4]
    readmission_30day[hadm_id] = days is not None and days <= 30.0

# ============================================================
# Part 3: Mortality by age-adjusted CCI bracket
# ============================================================

brackets = {"0": [], "1-2": [], "3-4": [], "5+": []}
for d in admission_data:
    cci_val = d["cci_age_adjusted"]
    if cci_val == 0:
        brackets["0"].append(d)
    elif cci_val <= 2:
        brackets["1-2"].append(d)
    elif cci_val <= 4:
        brackets["3-4"].append(d)
    else:
        brackets["5+"].append(d)

mortality_by_bracket = {}
for bracket, admissions in brackets.items():
    total = len(admissions)
    deaths = sum(1 for a in admissions if a["hospital_expire_flag"] == 1)
    mortality_by_bracket[bracket] = round(deaths / total, 4) if total > 0 else 0.0

# ============================================================
# Part 4: High-risk patients
# age-adjusted CCI >= 6 AND at least one admission with death
# ============================================================

high_cci_patients = set()
for d in admission_data:
    if d["cci_age_adjusted"] >= 6:
        high_cci_patients.add(d["subject_id"])

died_patients = set()
for d in admission_data:
    if d["hospital_expire_flag"] == 1:
        died_patients.add(d["subject_id"])

high_risk_patients = sorted(list(high_cci_patients & died_patients))

# ============================================================
# Write output
# ============================================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

results = {
    "cci_per_admission": cci_per_admission,
    "cci_age_adjusted_per_admission": cci_age_adj,
    "readmission_30day": readmission_30day,
    "mortality_by_cci_bracket": mortality_by_bracket,
    "high_risk_patients": high_risk_patients,
}

with open(OUTPUT_PATH, "w") as f:
    json.dump(results, f, indent=2)

conn.close()
print(f"Results written to {OUTPUT_PATH}")
print(f"  CCI computed for {len(cci_per_admission)} admissions")
print(f"  30-day readmissions: {sum(1 for v in readmission_30day.values() if v)}")
print(f"  High-risk patients: {len(high_risk_patients)}")
