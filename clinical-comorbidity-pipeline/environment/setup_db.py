#!/usr/bin/env python3
"""Load MIMIC-III demo CSVs into SQLite database."""
import sqlite3
import csv
import sys
import os

DB_PATH = '/app/mimic3_demo.db'
DATA_DIR = '/app/data'

def load_csv(cur, table_name, create_sql, csv_file, transform=None):
    cur.execute(create_sql)
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        cols = [c.strip() for c in reader.fieldnames]
        placeholders = ','.join(['?' for _ in cols])
        for row in reader:
            values = []
            for c in cols:
                raw = row.get(c)
                v = raw.strip() if raw else None
                v = v if v else None
                if transform and c in transform:
                    v = transform[c](v)
                values.append(v)
            cur.execute(f'INSERT INTO {table_name} VALUES ({placeholders})', values)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# PATIENTS
load_csv(cur, 'patients',
    '''CREATE TABLE patients (
        row_id INTEGER, subject_id INTEGER, gender TEXT,
        dob TEXT, dod TEXT, dod_hosp TEXT, dod_ssn TEXT, expire_flag INTEGER
    )''',
    os.path.join(DATA_DIR, 'demo_PATIENTS.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'subject_id': lambda v: int(v) if v else None,
     'expire_flag': lambda v: int(v) if v else None})

# ADMISSIONS
load_csv(cur, 'admissions',
    '''CREATE TABLE admissions (
        row_id INTEGER, subject_id INTEGER, hadm_id INTEGER,
        admittime TEXT, dischtime TEXT, deathtime TEXT,
        admission_type TEXT, admission_location TEXT, discharge_location TEXT,
        insurance TEXT, language TEXT, religion TEXT, marital_status TEXT,
        ethnicity TEXT, edregtime TEXT, edouttime TEXT, diagnosis TEXT,
        hospital_expire_flag INTEGER, has_chartevents_data INTEGER
    )''',
    os.path.join(DATA_DIR, 'demo_ADMISSIONS.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'subject_id': lambda v: int(v) if v else None,
     'hadm_id': lambda v: int(v) if v else None,
     'hospital_expire_flag': lambda v: int(v) if v else None,
     'has_chartevents_data': lambda v: int(v) if v else None})

# DIAGNOSES_ICD
load_csv(cur, 'diagnoses_icd',
    '''CREATE TABLE diagnoses_icd (
        row_id INTEGER, subject_id INTEGER, hadm_id INTEGER,
        seq_num INTEGER, icd9_code TEXT
    )''',
    os.path.join(DATA_DIR, 'demo_DIAGNOSES_ICD.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'subject_id': lambda v: int(v) if v else None,
     'hadm_id': lambda v: int(v) if v else None,
     'seq_num': lambda v: int(v) if v else None})

# LABEVENTS
load_csv(cur, 'labevents',
    '''CREATE TABLE labevents (
        row_id INTEGER, subject_id INTEGER, hadm_id INTEGER,
        itemid INTEGER, charttime TEXT, value TEXT, valuenum REAL,
        valueuom TEXT, flag TEXT
    )''',
    os.path.join(DATA_DIR, 'demo_LABEVENTS.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'subject_id': lambda v: int(v) if v else None,
     'hadm_id': lambda v: int(v) if v else None,
     'itemid': lambda v: int(v) if v else None,
     'valuenum': lambda v: float(v) if v else None})

# D_LABITEMS
load_csv(cur, 'd_labitems',
    '''CREATE TABLE d_labitems (
        row_id INTEGER, itemid INTEGER, label TEXT,
        fluid TEXT, category TEXT, loinc_code TEXT
    )''',
    os.path.join(DATA_DIR, 'demo_D_LABITEMS.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'itemid': lambda v: int(v) if v else None})

# ICUSTAYS
load_csv(cur, 'icustays',
    '''CREATE TABLE icustays (
        row_id INTEGER, subject_id INTEGER, hadm_id INTEGER,
        icustay_id INTEGER, dbsource TEXT, first_careunit TEXT,
        last_careunit TEXT, first_wardid INTEGER, last_wardid INTEGER,
        intime TEXT, outtime TEXT, los REAL
    )''',
    os.path.join(DATA_DIR, 'demo_ICUSTAYS.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'subject_id': lambda v: int(v) if v else None,
     'hadm_id': lambda v: int(v) if v else None,
     'icustay_id': lambda v: int(v) if v else None,
     'first_wardid': lambda v: int(v) if v else None,
     'last_wardid': lambda v: int(v) if v else None,
     'los': lambda v: float(v) if v else None})

# PRESCRIPTIONS
load_csv(cur, 'prescriptions',
    '''CREATE TABLE prescriptions (
        row_id INTEGER, subject_id INTEGER, hadm_id INTEGER,
        icustay_id INTEGER, startdate TEXT, enddate TEXT,
        drug_type TEXT, drug TEXT, drug_name_poe TEXT,
        drug_name_generic TEXT, formulary_drug_cd TEXT, gsn TEXT,
        ndc TEXT, prod_strength TEXT, dose_val_rx TEXT, dose_unit_rx TEXT,
        form_val_disp TEXT, form_unit_disp TEXT, route TEXT
    )''',
    os.path.join(DATA_DIR, 'demo_PRESCRIPTIONS.csv'),
    {'row_id': lambda v: int(v) if v else None,
     'subject_id': lambda v: int(v) if v else None,
     'hadm_id': lambda v: int(v) if v else None,
     'icustay_id': lambda v: int(v) if v else None})

conn.commit()

# Verify
for table in ['patients','admissions','diagnoses_icd','labevents','d_labitems','icustays','prescriptions']:
    cur.execute(f'SELECT COUNT(*) FROM {table}')
    print(f'{table}: {cur.fetchone()[0]} rows')

conn.close()
print('Database created successfully at', DB_PATH)
