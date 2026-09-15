#!/usr/bin/env python3
"""
ICU Clinical Severity Scoring and Pharmacovigilance Pipeline.

Integrates Charlson CCI (adapted from MIMIC-IV BigQuery reference),
lab-based SOFA organ dysfunction scoring, antimicrobial-based sepsis
screening, nephrotoxic drug-AKI risk detection, and chronic-acute
risk stratification from MIMIC-III demo data.
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
# 1. Charlson Comorbidity Index
# Adapted from MIMIC-IV BigQuery -> MIMIC-III SQLite
# Quan (2005) ICD-9-CM coding with Charlson (1987) weights
# ============================================================

CHARLSON_SQL = """
WITH com AS (
    SELECT
        ad.hadm_id,
        MAX(CASE WHEN SUBSTR(d.icd9_code, 1, 3) IN ('410', '412')
            THEN 1 ELSE 0 END) AS myocardial_infarct,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) = '428'
            OR SUBSTR(d.icd9_code, 1, 5) IN (
                '39891','40201','40211','40291','40401','40403',
                '40411','40413','40491','40493')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '4254'
                AND SUBSTR(d.icd9_code, 1, 4) <= '4259')
            THEN 1 ELSE 0 END) AS congestive_heart_failure,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('440', '441')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '0930','4373','4471','5571','5579','V434')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '4431'
                AND SUBSTR(d.icd9_code, 1, 4) <= '4439')
            THEN 1 ELSE 0 END) AS peripheral_vascular_disease,
        MAX(CASE WHEN
            (SUBSTR(d.icd9_code, 1, 3) >= '430'
             AND SUBSTR(d.icd9_code, 1, 3) <= '438')
            OR SUBSTR(d.icd9_code, 1, 5) = '36234'
            THEN 1 ELSE 0 END) AS cerebrovascular_disease,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) = '290'
            OR SUBSTR(d.icd9_code, 1, 4) IN ('2941', '3312')
            THEN 1 ELSE 0 END) AS dementia,
        MAX(CASE WHEN
            (SUBSTR(d.icd9_code, 1, 3) >= '490'
             AND SUBSTR(d.icd9_code, 1, 3) <= '505')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '4168','4169','5064','5081','5088')
            THEN 1 ELSE 0 END) AS chronic_pulmonary_disease,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) = '725'
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '4465','7100','7101','7102','7103','7104',
                '7140','7141','7142','7148')
            THEN 1 ELSE 0 END) AS rheumatic_disease,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('531', '532', '533', '534')
            THEN 1 ELSE 0 END) AS peptic_ulcer_disease,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('570', '571')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '0706','0709','5733','5734','5738','5739','V427')
            OR SUBSTR(d.icd9_code, 1, 5) IN (
                '07022','07023','07032','07033','07044','07054')
            THEN 1 ELSE 0 END) AS mild_liver_disease,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 4) IN (
                '2500','2501','2502','2503','2508','2509')
            THEN 1 ELSE 0 END) AS diabetes_without_cc,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 4) IN ('2504','2505','2506','2507')
            THEN 1 ELSE 0 END) AS diabetes_with_cc,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('342', '343')
            OR SUBSTR(d.icd9_code, 1, 4) IN (
                '3341','3440','3441','3442','3443',
                '3444','3445','3446','3449')
            THEN 1 ELSE 0 END) AS paraplegia,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('582', '585', '586', 'V56')
            OR SUBSTR(d.icd9_code, 1, 4) IN ('5880','V420','V451')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '5830'
                AND SUBSTR(d.icd9_code, 1, 4) <= '5837')
            OR SUBSTR(d.icd9_code, 1, 5) IN (
                '40301','40311','40391','40402','40403',
                '40412','40413','40492','40493')
            THEN 1 ELSE 0 END) AS renal_disease,
        MAX(CASE WHEN
            (SUBSTR(d.icd9_code, 1, 3) >= '140'
             AND SUBSTR(d.icd9_code, 1, 3) <= '172')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '1740'
                AND SUBSTR(d.icd9_code, 1, 4) <= '1958')
            OR (SUBSTR(d.icd9_code, 1, 3) >= '200'
                AND SUBSTR(d.icd9_code, 1, 3) <= '208')
            OR SUBSTR(d.icd9_code, 1, 4) = '2386'
            THEN 1 ELSE 0 END) AS malignant_cancer,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 4) IN ('4560','4561','4562')
            OR (SUBSTR(d.icd9_code, 1, 4) >= '5722'
                AND SUBSTR(d.icd9_code, 1, 4) <= '5728')
            THEN 1 ELSE 0 END) AS severe_liver_disease,
        MAX(CASE WHEN
            SUBSTR(d.icd9_code, 1, 3) IN ('196', '197', '198', '199')
            THEN 1 ELSE 0 END) AS metastatic_solid_tumor,
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
    ad.hospital_expire_flag,
    com.myocardial_infarct + com.congestive_heart_failure
    + com.peripheral_vascular_disease + com.cerebrovascular_disease
    + com.dementia + com.chronic_pulmonary_disease
    + com.rheumatic_disease + com.peptic_ulcer_disease
    + MAX(com.mild_liver_disease, 3 * com.severe_liver_disease)
    + MAX(2 * com.diabetes_with_cc, com.diabetes_without_cc)
    + MAX(2 * com.malignant_cancer, 6 * com.metastatic_solid_tumor)
    + 2 * com.paraplegia + 2 * com.renal_disease
    + 6 * com.aids AS cci,
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
cci_per_admission = {}
cci_age_adjusted = {}
admission_data = {}

for row in rows:
    hadm_id = str(row[1])
    cci_per_admission[hadm_id] = row[3]
    cci_age_adjusted[hadm_id] = row[4]
    admission_data[hadm_id] = {
        "subject_id": row[0],
        "hospital_expire_flag": row[2],
        "cci_adj": row[4],
    }

# ============================================================
# 2. SOFA Lab Components per ICU Stay
# Discover lab item IDs from d_labitems, compute worst values,
# apply standard SOFA thresholds
# ============================================================

# Discover lab item IDs
cur.execute("SELECT itemid FROM d_labitems WHERE label = 'Creatinine' AND fluid = 'Blood'")
creat_itemid = cur.fetchone()[0]  # 50912

cur.execute("SELECT itemid FROM d_labitems WHERE label = 'Bilirubin, Total' AND fluid = 'Blood'")
bili_itemid = cur.fetchone()[0]  # 50885

cur.execute("SELECT itemid FROM d_labitems WHERE label = 'Platelet Count' AND fluid = 'Blood'")
plt_itemid = cur.fetchone()[0]  # 51265

SOFA_SQL = f"""
WITH icu_creat AS (
    SELECT i.icustay_id, MAX(l.valuenum) as peak_creatinine
    FROM icustays i
    JOIN labevents l ON i.subject_id = l.subject_id
        AND l.charttime >= i.intime AND l.charttime <= i.outtime
        AND l.itemid = {creat_itemid} AND l.valuenum IS NOT NULL
    GROUP BY i.icustay_id
),
icu_bili AS (
    SELECT i.icustay_id, MAX(l.valuenum) as peak_bilirubin
    FROM icustays i
    JOIN labevents l ON i.subject_id = l.subject_id
        AND l.charttime >= i.intime AND l.charttime <= i.outtime
        AND l.itemid = {bili_itemid} AND l.valuenum IS NOT NULL
    GROUP BY i.icustay_id
),
icu_plt AS (
    SELECT i.icustay_id, MIN(l.valuenum) as nadir_platelets
    FROM icustays i
    JOIN labevents l ON i.subject_id = l.subject_id
        AND l.charttime >= i.intime AND l.charttime <= i.outtime
        AND l.itemid = {plt_itemid} AND l.valuenum IS NOT NULL
    GROUP BY i.icustay_id
)
SELECT
    i.icustay_id, i.subject_id, i.hadm_id,
    c.peak_creatinine, b.peak_bilirubin, p.nadir_platelets,
    CASE WHEN c.peak_creatinine IS NULL THEN 0
         WHEN c.peak_creatinine >= 5.0 THEN 4
         WHEN c.peak_creatinine >= 3.5 THEN 3
         WHEN c.peak_creatinine >= 2.0 THEN 2
         WHEN c.peak_creatinine >= 1.2 THEN 1
         ELSE 0 END as renal,
    CASE WHEN b.peak_bilirubin IS NULL THEN 0
         WHEN b.peak_bilirubin >= 12.0 THEN 4
         WHEN b.peak_bilirubin >= 6.0 THEN 3
         WHEN b.peak_bilirubin >= 2.0 THEN 2
         WHEN b.peak_bilirubin >= 1.2 THEN 1
         ELSE 0 END as hepatic,
    CASE WHEN p.nadir_platelets IS NULL THEN 0
         WHEN p.nadir_platelets < 20 THEN 4
         WHEN p.nadir_platelets < 50 THEN 3
         WHEN p.nadir_platelets < 100 THEN 2
         WHEN p.nadir_platelets < 150 THEN 1
         ELSE 0 END as coagulation
FROM icustays i
LEFT JOIN icu_creat c ON i.icustay_id = c.icustay_id
LEFT JOIN icu_bili b ON i.icustay_id = b.icustay_id
LEFT JOIN icu_plt p ON i.icustay_id = p.icustay_id
ORDER BY i.icustay_id
"""

sofa_rows = cur.execute(SOFA_SQL).fetchall()
sofa_lab_components = {}
icu_data = {}

for row in sofa_rows:
    icustay_id = str(row[0])
    renal, hepatic, coag = row[6], row[7], row[8]
    partial = renal + hepatic + coag
    sofa_lab_components[icustay_id] = {
        "renal": renal,
        "hepatic": hepatic,
        "coagulation": coag,
        "partial_sofa": partial,
    }
    icu_data[icustay_id] = {
        "subject_id": row[1],
        "hadm_id": str(row[2]),
        "partial_sofa": partial,
        "renal": renal,
        "peak_creatinine": row[3],
    }

# ============================================================
# 3. Antimicrobial Exposure and Sepsis Screening
# Match drug names from prescriptions, exclude non-systemic routes
# ============================================================

ABX_SQL = """
SELECT DISTINCT i.icustay_id
FROM icustays i
JOIN prescriptions p ON i.hadm_id = p.hadm_id
WHERE (
    p.drug LIKE '%cillin%' OR
    p.drug LIKE '%Ampicillin%' OR p.drug LIKE '%Amoxicillin%' OR
    p.drug LIKE '%Cef%' OR
    p.drug LIKE '%Ciprofloxacin%' OR p.drug LIKE '%Levofloxacin%' OR
    p.drug LIKE '%Azithromycin%' OR p.drug LIKE '%Clarithromycin%' OR
    p.drug LIKE '%Erythromycin%' OR
    p.drug LIKE '%Clindamycin%' OR
    p.drug LIKE '%Vancomycin%' OR
    p.drug LIKE '%Linezolid%' OR
    p.drug LIKE '%Metronidazole%' OR p.drug LIKE '%MetRONIDAZOLE%' OR
    p.drug LIKE '%Sulfameth%' OR
    p.drug LIKE '%Fluconazole%' OR
    p.drug LIKE '%Nitrofurantoin%' OR
    p.drug LIKE '%Rifampin%' OR p.drug LIKE '%Rifaximin%' OR
    p.drug LIKE '%Isoniazid%' OR p.drug LIKE '%Ethambutol%' OR
    p.drug LIKE '%Pyrazinamide%' OR
    p.drug LIKE '%Penicillin%'
)
AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'TP')
AND p.startdate <= i.outtime
AND p.enddate >= i.intime
"""

cur.execute(ABX_SQL)
abx_icuids = set(str(r[0]) for r in cur.fetchall())

suspected_sepsis = {}
for icustay_id in sofa_lab_components:
    has_abx = icustay_id in abx_icuids
    high_sofa = sofa_lab_components[icustay_id]["partial_sofa"] >= 2
    suspected_sepsis[icustay_id] = has_abx and high_sofa

# ============================================================
# 4. Nephrotoxic Drug-AKI Risk Detection
# IV vancomycin, aminoglycosides, systemic NSAIDs, CNI/mTOR inhibitors
# co-occurring with SOFA renal >= 1
# ============================================================

NEPHRO_SQL = """
SELECT DISTINCT i.icustay_id, i.subject_id
FROM icustays i
JOIN prescriptions p ON i.hadm_id = p.hadm_id
WHERE (
    (p.drug LIKE '%Vancomycin%' AND p.route IN ('IV', 'IV DRIP', 'IV BOLUS', 'PB')) OR
    (p.drug LIKE '%Gentamicin%' AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'TP')) OR
    (p.drug LIKE '%Tobramycin%' AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'TP')) OR
    (p.drug LIKE '%Amikacin%' AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'TP')) OR
    (p.drug LIKE '%Ketorolac%' AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'OPHT', 'TP')) OR
    (p.drug LIKE '%Ibuprofen%' AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'TP')) OR
    (p.drug LIKE '%Indomethacin%' AND p.route NOT IN ('OU', 'OS', 'OD', 'BOTH EYES', 'RIGHT EYE', 'TP')) OR
    (p.drug LIKE '%Naproxen%') OR
    (p.drug LIKE '%Tacrolimus%') OR
    (p.drug LIKE '%Sirolimus%')
)
AND p.startdate <= i.outtime
AND p.enddate >= i.intime
"""

cur.execute(NEPHRO_SQL)
nephro_risk_subjects = set()
for row in cur.fetchall():
    icustay_id = str(row[0])
    subject_id = row[1]
    if icustay_id in icu_data and icu_data[icustay_id]["renal"] >= 1:
        nephro_risk_subjects.add(subject_id)

nephrotoxic_aki_risk = sorted(list(nephro_risk_subjects))

# ============================================================
# 5. Risk Matrix: CCI bracket x partial SOFA bracket
# ============================================================

matrix = {}
for cb in ["0-2", "3-5", "6+"]:
    matrix[cb] = {}
    for sb in ["0", "1-2", "3+"]:
        matrix[cb][sb] = {"deaths": 0, "total": 0}

for icustay_id, idata in icu_data.items():
    hadm_id = idata["hadm_id"]
    if hadm_id not in admission_data:
        continue
    cci_val = admission_data[hadm_id]["cci_adj"]
    ps = idata["partial_sofa"]
    expire = admission_data[hadm_id]["hospital_expire_flag"]

    cb = "0-2" if cci_val <= 2 else ("3-5" if cci_val <= 5 else "6+")
    sb = "0" if ps == 0 else ("1-2" if ps <= 2 else "3+")

    matrix[cb][sb]["total"] += 1
    if expire == 1:
        matrix[cb][sb]["deaths"] += 1

risk_matrix = {}
for cb in ["0-2", "3-5", "6+"]:
    risk_matrix[cb] = {}
    for sb in ["0", "1-2", "3+"]:
        m = matrix[cb][sb]
        risk_matrix[cb][sb] = round(m["deaths"] / m["total"], 4) if m["total"] > 0 else None

# ============================================================
# Write output
# ============================================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

results = {
    "cci_per_admission": cci_per_admission,
    "cci_age_adjusted": cci_age_adjusted,
    "sofa_lab_components": sofa_lab_components,
    "suspected_sepsis": suspected_sepsis,
    "nephrotoxic_aki_risk": nephrotoxic_aki_risk,
    "risk_matrix": risk_matrix,
}

with open(OUTPUT_PATH, "w") as f:
    json.dump(results, f, indent=2)

conn.close()
print(f"Results written to {OUTPUT_PATH}")
print(f"  CCI computed for {len(cci_per_admission)} admissions")
print(f"  SOFA components for {len(sofa_lab_components)} ICU stays")
print(f"  Suspected sepsis: {sum(1 for v in suspected_sepsis.values() if v)}")
print(f"  Nephrotoxic AKI risk patients: {len(nephrotoxic_aki_risk)}")
