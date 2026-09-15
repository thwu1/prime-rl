#!/usr/bin/env python3
"""Create the clinical SQLite database with multi-source schema."""
import sqlite3
import os

db_path = "/app/data/clinical.db"
os.makedirs("/app/data", exist_ok=True)

conn = sqlite3.connect(db_path)
c = conn.cursor()

# PSG sessions table
c.execute("""
CREATE TABLE psg_sessions (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    site_code TEXT NOT NULL,
    study_date TEXT NOT NULL,
    last_followup_date TEXT NOT NULL,
    age_at_study REAL,
    sex TEXT,
    bmi REAL
)
""")

# EHR diagnoses table
c.execute("""
CREATE TABLE ehr_diagnoses (
    diagnosis_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    icd_code TEXT NOT NULL,
    diagnosis_date TEXT NOT NULL,
    encounter_type TEXT DEFAULT 'outpatient',
    provider_id TEXT
)
""")

# Claims diagnoses table (different column names from EHR)
c.execute("""
CREATE TABLE claims_diagnoses (
    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id TEXT NOT NULL,
    diagnosis_code TEXT NOT NULL,
    service_date TEXT NOT NULL,
    claim_type TEXT DEFAULT 'professional',
    rendering_provider TEXT
)
""")

# Patient linkage table (maps EHR patient_id to claims member_id)
c.execute("""
CREATE TABLE patient_linkage (
    link_id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    member_id TEXT NOT NULL,
    site_code TEXT NOT NULL,
    linkage_date TEXT NOT NULL
)
""")

# Site parameters table (configurable evaluation thresholds)
c.execute("""
CREATE TABLE site_parameters (
    param_id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_code TEXT NOT NULL,
    parameter_name TEXT NOT NULL,
    parameter_value TEXT NOT NULL,
    effective_date TEXT NOT NULL,
    notes TEXT
)
""")

# Create indexes
c.execute("CREATE INDEX idx_ehr_patient ON ehr_diagnoses(patient_id)")
c.execute("CREATE INDEX idx_claims_member ON claims_diagnoses(member_id)")
c.execute("CREATE INDEX idx_linkage_patient ON patient_linkage(patient_id)")
c.execute("CREATE INDEX idx_linkage_member ON patient_linkage(member_id)")
c.execute("CREATE INDEX idx_session_patient ON psg_sessions(patient_id)")
c.execute("CREATE INDEX idx_site_params ON site_parameters(site_code, parameter_name)")

# --- Insert patients (30 total: 10 per group) ---
patients = [
    # Group 1 (CI positive)
    ("P001", "S0001", "2010-03-15", "2018-05-01", 68.2, "M", 27.3),
    ("P002", "S0001", "2011-01-10", "2019-06-01", 72.5, "F", 24.8),
    ("P003", "I0006", "2010-07-15", "2019-07-01", 66.8, "F", 26.4),
    ("P004", "S0001", "2010-09-20", "2019-11-01", 78.1, "F", 22.1),
    ("P005", "I0002", "2011-03-01", "2020-05-01", 70.3, "M", 29.5),
    ("P006", "S0001", "2010-01-01", "2019-01-01", 74.9, "M", 28.7),
    ("P007", "S0001", "2012-06-01", "2020-01-01", 65.0, "M", 31.2),
    ("P008", "S0001", "2009-06-01", "2018-01-01", 71.0, "F", 27.9),
    ("P009", "I0004", "2010-06-01", "2019-06-01", 60.3, "M", 25.1),
    ("P010", "S0001", "2011-01-01", "2019-06-01", 58.9, "F", 24.7),
    # Group 2 (CI negative)
    ("P011", "S0001", "2010-01-01", "2019-06-01", 55.2, "F", 23.5),
    ("P012", "S0001", "2011-03-15", "2020-01-01", 62.1, "M", 25.8),
    ("P013", "S0001", "2010-06-01", "2018-08-01", 59.7, "F", 30.1),
    ("P014", "S0001", "2012-01-01", "2021-06-01", 48.3, "M", 22.9),
    ("P015", "I0002", "2012-06-01", "2019-01-01", 71.4, "M", 24.3),
    ("P016", "S0001", "2011-07-01", "2019-12-01", 53.6, "F", 27.6),
    ("P017", "I0006", "2011-01-01", "2019-06-01", 67.9, "F", 29.2),
    ("P018", "I0004", "2013-01-01", "2021-01-01", 44.8, "M", 26.1),
    ("P019", "S0001", "2010-02-01", "2018-06-01", 63.5, "M", 28.3),
    ("P020", "I0002", "2011-01-01", "2017-06-01", 69.4, "F", 25.9),
    # Group 3 (excluded)
    ("P021", "S0001", "2010-05-01", "2019-01-01", 76.2, "F", 23.8),
    ("P022", "S0001", "2013-01-01", "2021-01-01", 69.5, "M", 31.5),
    ("P023", "S0001", "2015-01-01", "2020-06-01", 61.3, "F", 25.2),
    ("P024", "S0001", "2010-01-01", "2020-01-01", 73.7, "M", 28.4),
    ("P025", "S0001", "2011-01-01", "2019-06-01", 58.9, "F", 24.7),
    ("P026", "I0002", "2014-06-01", "2019-06-01", 80.1, "M", 22.5),
    ("P027", "S0001", "2010-03-01", "2019-01-01", 64.8, "F", 26.7),
    ("P028", "S0001", "2010-01-01", "2019-06-01", 57.3, "M", 29.1),
    ("P029", "S0001", "2012-06-01", "2018-06-01", 66.1, "F", 27.4),
    ("P030", "I0004", "2014-01-01", "2019-06-01", 72.8, "M", 23.9),
]

for p in patients:
    c.execute(
        "INSERT INTO psg_sessions (patient_id, site_code, study_date, last_followup_date, age_at_study, sex, bmi) VALUES (?,?,?,?,?,?,?)",
        p,
    )

# --- EHR diagnoses (dotted ICD codes) ---
ehr_diagnoses = [
    # P001: standard Group 1, 2 qualifying EHR codes in window
    ("P001", "G31.84", "2013-06-20", "outpatient", "DR101"),
    ("P001", "G30.9", "2014-01-10", "outpatient", "DR102"),
    # P002: 1 EHR qualifying (2nd qualifying code is in claims)
    ("P002", "331.83", "2015-02-15", "outpatient", "DR201"),
    # P003: 2 EHR qualifying codes
    ("P003", "G30.0", "2016-07-15", "outpatient", "DR301"),
    ("P003", "G30.1", "2016-08-01", "outpatient", "DR302"),
    # P004: mixed ICD-9/ICD-10 dotted codes
    ("P004", "290.0", "2014-01-05", "inpatient", "DR401"),
    ("P004", "F03.90", "2014-03-10", "outpatient", "DR402"),
    # P005: 1 EHR qualifying (2nd in claims)
    ("P005", "G31.84", "2014-06-15", "outpatient", "DR501"),
    # P006: 3 qualifying, first one early (<3yr), two in window
    ("P006", "G31.84", "2011-06-01", "outpatient", "DR601"),
    ("P006", "G30.0", "2014-01-01", "inpatient", "DR602"),
    ("P006", "G30.9", "2015-06-01", "outpatient", "DR603"),
    # P007: 2 EHR qualifying codes
    ("P007", "G30.0", "2016-07-15", "outpatient", "DR701"),
    ("P007", "G30.1", "2016-08-01", "outpatient", "DR702"),
    # P008: 1 EHR qualifying (2nd in claims)
    ("P008", "G31.84", "2012-09-01", "outpatient", "DR801"),
    # P009: 2 EHR qualifying codes
    ("P009", "G31.83", "2014-02-01", "outpatient", "DR901"),
    ("P009", "G31.84", "2014-11-15", "outpatient", "DR902"),
    # P010: 1 EHR qualifying (duplicate + extra in claims)
    ("P010", "G31.84", "2014-06-01", "outpatient", "DR1001"),
    # P011: non-qualifying CAD
    ("P011", "I25.10", "2012-03-15", "outpatient", "DR1101"),
    # P012: non-qualifying hyperlipidemia
    ("P012", "E78.5", "2013-07-22", "outpatient", "DR1201"),
    # P013: multiple non-qualifying
    ("P013", "J45.9", "2013-01-15", "outpatient", "DR1301"),
    ("P013", "E11.9", "2014-06-01", "outpatient", "DR1302"),
    ("P013", "I10", "2015-03-20", "inpatient", "DR1303"),
    # P014: non-qualifying OSA
    ("P014", "G47.33", "2014-05-01", "outpatient", "DR1401"),
    # P015-P017: no EHR diagnoses
    # P018: non-qualifying back pain
    ("P018", "M54.5", "2015-08-20", "outpatient", "DR1801"),
    # P019-P020: no diagnoses
    # P021: only 1 qualifying
    ("P021", "G31.84", "2014-06-01", "outpatient", "DR2101"),
    # P022: 2 qualifying but all before 3yr window
    ("P022", "G30.0", "2014-06-01", "outpatient", "DR2201"),
    ("P022", "G30.1", "2014-09-01", "outpatient", "DR2202"),
    # P023: non-qualifying headache
    ("P023", "R51", "2016-04-10", "outpatient", "DR2301"),
    # P024: 2 qualifying but all beyond 7yr window
    ("P024", "G31.84", "2018-06-01", "outpatient", "DR2401"),
    ("P024", "G30.9", "2019-01-01", "outpatient", "DR2402"),
    # P025: 2 qualifying in window but gap < 7 days
    ("P025", "G30.0", "2015-03-01", "outpatient", "DR2501"),
    ("P025", "G30.1", "2015-03-05", "outpatient", "DR2502"),
    # P026: non-qualifying insomnia
    ("P026", "G47.00", "2015-09-01", "outpatient", "DR2601"),
    # P027: 1 qualifying (has duplicate in claims -> dedup to 1)
    ("P027", "G31.84", "2014-03-01", "outpatient", "DR2701"),
    # P028: 1 qualifying (different qualifying code in claims on SAME date)
    ("P028", "G30.0", "2016-01-01", "outpatient", "DR2801"),
    # P029: no diagnoses
    # P030: non-qualifying sleep apnea
    ("P030", "G47.30", "2016-01-15", "outpatient", "DR3001"),
]

for d in ehr_diagnoses:
    c.execute(
        "INSERT INTO ehr_diagnoses (patient_id, icd_code, diagnosis_date, encounter_type, provider_id) VALUES (?,?,?,?,?)",
        d,
    )

# --- Claims diagnoses (undotted codes, different column names) ---
claims_diagnoses = [
    # P002: qualifying code completing Group 1 (cross-source)
    ("M002", "G3184", "2016-08-20", "professional", "NPI001"),
    # P005: qualifying code completing Group 1 (cross-source)
    ("M005", "F0390", "2015-01-10", "professional", "NPI002"),
    # P008: qualifying code completing Group 1 (ICD-9 undotted)
    ("M008", "33183", "2016-03-15", "professional", "NPI003"),
    # P010: DUPLICATE of EHR entry (same code+date after normalization)
    ("M010", "G3184", "2014-06-01", "professional", "NPI004"),
    # P010: additional qualifying code (not duplicate)
    ("M010", "G309", "2015-09-01", "professional", "NPI005"),
    # P016: non-qualifying COPD (claims only, no EHR diagnoses)
    ("M016", "J441", "2013-11-15", "professional", "NPI006"),
    # P027: DUPLICATE of EHR entry (same code+date -> dedup to 1 event)
    ("M027", "G3184", "2014-03-01", "professional", "NPI007"),
    # P028: different qualifying code on SAME date as EHR code
    ("M028", "G309", "2016-01-01", "professional", "NPI008"),
]

for d in claims_diagnoses:
    c.execute(
        "INSERT INTO claims_diagnoses (member_id, diagnosis_code, service_date, claim_type, rendering_provider) VALUES (?,?,?,?,?)",
        d,
    )

# --- Patient linkage ---
linkage = [
    ("P002", "M002", "S0001", "2011-01-10"),
    ("P005", "M005", "I0002", "2011-03-01"),
    ("P008", "M008", "S0001", "2009-06-01"),
    ("P010", "M010", "S0001", "2011-01-01"),
    ("P016", "M016", "S0001", "2011-07-01"),
    ("P027", "M027", "S0001", "2010-03-01"),
    ("P028", "M028", "S0001", "2010-01-01"),
]

for lnk in linkage:
    c.execute(
        "INSERT INTO patient_linkage (patient_id, member_id, site_code, linkage_date) VALUES (?,?,?,?)",
        lnk,
    )

# --- Site parameters ---
site_params = [
    ("S0001", "min_followup_years", "7.0", "2020-01-01",
     "Standard minimum follow-up for CI-negative classification"),
    ("S0001", "data_collection_start", "2005-01-01", "2020-01-01", None),
    ("I0002", "min_followup_years", "6.0", "2020-01-01",
     "Reduced threshold due to shorter data availability at this site"),
    ("I0002", "data_collection_start", "2008-01-01", "2020-01-01", None),
    ("I0004", "min_followup_years", "7.0", "2020-01-01",
     "Standard minimum follow-up"),
    ("I0004", "data_collection_start", "2006-01-01", "2020-01-01", None),
    ("I0006", "min_followup_years", "7.0", "2020-01-01",
     "Standard minimum follow-up"),
    ("I0006", "data_collection_start", "2007-01-01", "2020-01-01", None),
]

for p in site_params:
    c.execute(
        "INSERT INTO site_parameters (site_code, parameter_name, parameter_value, effective_date, notes) VALUES (?,?,?,?,?)",
        p,
    )

conn.commit()
conn.close()
print(f"Clinical database created at {db_path}")
