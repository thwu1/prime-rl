#!/usr/bin/env python3
"""
SDTM Dataset Builder for Study XYZ2024.

Reads raw clinical trial data and sponsor conventions, then produces
CDISC SDTM-compliant domain datasets: DM, AE, VS, EX, SUPPAE, TS.

"""

import pandas as pd
from datetime import datetime
import os

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RAW = '/app/raw_data'
OUT = '/app/sdtm'
STUDYID = 'XYZ2024'

os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(val):
    """Convert MM/DD/YYYY string to ISO 8601 YYYY-MM-DD."""
    if pd.isna(val) or str(val).strip() == '':
        return ''
    return datetime.strptime(str(val).strip(), '%m/%d/%Y').strftime('%Y-%m-%d')


def calc_age(brthdtc, rfstdtc):
    """Age in completed years at rfstdtc."""
    bd = datetime.strptime(brthdtc, '%Y-%m-%d').date()
    rd = datetime.strptime(rfstdtc, '%Y-%m-%d').date()
    age = rd.year - bd.year
    if (rd.month, rd.day) < (bd.month, bd.day):
        age -= 1
    return age


def study_day(dtc, rfstdtc):
    """SDTM study-day rule: no Day 0."""
    if not dtc or not rfstdtc:
        return ''
    d = datetime.strptime(dtc, '%Y-%m-%d').date()
    r = datetime.strptime(rfstdtc, '%Y-%m-%d').date()
    diff = (d - r).days
    return diff + 1 if diff >= 0 else diff


# ---------------------------------------------------------------------------
# Read raw data
# ---------------------------------------------------------------------------
subj = pd.read_csv(f'{RAW}/subj_info.csv', dtype=str, keep_default_na=False)
ae_raw = pd.read_csv(f'{RAW}/adverse_events.csv', dtype=str, keep_default_na=False)
vs_raw = pd.read_csv(f'{RAW}/vital_signs.csv', dtype=str, keep_default_na=False)
ex_raw = pd.read_csv(f'{RAW}/drug_dosing.csv', dtype=str, keep_default_na=False)
med_dict = pd.read_csv(f'{RAW}/medical_dictionary.csv', dtype=str, keep_default_na=False)

# Build medical-dictionary lookup (case-insensitive)
dict_lookup = {}
for _, r in med_dict.iterrows():
    key = str(r['VerbatimTerm']).strip().lower()
    dict_lookup[key] = {
        'pt': str(r['PreferredTerm']).strip(),
        'soc': str(r['BodySystemClass']).strip(),
    }

# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------
RACE_MAP = {
    'Caucasian': 'WHITE',
    'White': 'WHITE',
    'African American': 'BLACK OR AFRICAN AMERICAN',
    'Asian': 'ASIAN',
    'Mixed Race': 'MULTIPLE',
    'Native American': 'AMERICAN INDIAN OR ALASKA NATIVE',
}

ETHNIC_MAP = {
    'Not Hispanic': 'NOT HISPANIC OR LATINO',
    'Hispanic or Latino': 'HISPANIC OR LATINO',
}

ARM_MAP = {
    'Treatment': ('TRTX10', 'Antihypertensin-X 10 mg'),
    'Placebo': ('PBO', 'Placebo'),
}

AESEV_MAP = {'1': 'MILD', '2': 'MODERATE', '3': 'SEVERE'}
AESER_MAP = {'Yes': 'Y', 'No': 'N'}
AEOUT_MAP = {
    'Resolved': 'RECOVERED/RESOLVED',
    'Ongoing': 'NOT RECOVERED/NOT RESOLVED',
    'Resolved with residual effects': 'RECOVERED/RESOLVED WITH SEQUELAE',
}
AEACN_MAP = {
    'None': 'DOSE NOT CHANGED',
    'Dose reduced': 'DOSE REDUCED',
    'Drug discontinued': 'DRUG WITHDRAWN',
}
AEREL_MAP = {
    'Not related': 'NOT RELATED',
    'Unlikely': 'UNLIKELY',
    'Possibly related': 'POSSIBLE',
    'Probably related': 'PROBABLE',
    'Definitely related': 'RELATED',
}

VSTESTCD_MAP = {
    'Systolic Blood Pressure': ('SYSBP', 'Systolic Blood Pressure'),
    'Diastolic Blood Pressure': ('DIABP', 'Diastolic Blood Pressure'),
    'Pulse Rate': ('PULSE', 'Pulse Rate'),
    'Body Weight': ('WEIGHT', 'Weight'),
}

VISIT_MAP = {
    'Screening': (1, 'SCREENING'),
    'Baseline': (2, 'BASELINE'),
}

# ---------------------------------------------------------------------------
# DM – Demographics
# ---------------------------------------------------------------------------
rfstdtc_map = {}
dm_rows = []

for _, row in subj.iterrows():
    subjid = row['SubjectID'].strip()
    brthdtc = parse_date(row['BirthDate'])
    rfstdtc = parse_date(row['RandomizationDate'])
    rfendtc = parse_date(row['EndDate'])
    rfstdtc_map[subjid] = rfstdtc

    usubjid = f'{STUDYID}-{subjid}'
    age = calc_age(brthdtc, rfstdtc)
    sex = 'M' if row['Gender'].strip() == 'Male' else 'F'
    race = RACE_MAP.get(row['Race'].strip(), row['Race'].strip().upper())
    ethnic = ETHNIC_MAP.get(row['Ethnicity'].strip(),
                            row['Ethnicity'].strip().upper())
    armcd, arm = ARM_MAP.get(row['ArmAssignment'].strip(), ('UNK', 'Unknown'))

    # Cross-reference EX for RFXSTDTC / RFXENDTC
    ex_subj = ex_raw[ex_raw['SubjectID'].str.strip() == subjid]
    rfxstdtc = parse_date(ex_subj['FirstDoseDate'].iloc[0]) \
        if len(ex_subj) > 0 else ''
    rfxendtc = parse_date(ex_subj['LastDoseDate'].iloc[0]) \
        if len(ex_subj) > 0 else ''

    dm_rows.append({
        'STUDYID': STUDYID, 'DOMAIN': 'DM',
        'USUBJID': usubjid, 'SUBJID': subjid,
        'RFSTDTC': rfstdtc, 'RFENDTC': rfendtc,
        'RFXSTDTC': rfxstdtc, 'RFXENDTC': rfxendtc,
        'SITEID': row['Site'].strip(),
        'BRTHDTC': brthdtc,
        'AGE': age, 'AGEU': 'YEARS',
        'SEX': sex, 'RACE': race, 'ETHNIC': ethnic,
        'ARMCD': armcd, 'ARM': arm,
        'ACTARMCD': armcd, 'ACTARM': arm,
        'COUNTRY': 'USA',
    })

pd.DataFrame(dm_rows).to_csv(f'{OUT}/dm.csv', index=False)

# ---------------------------------------------------------------------------
# AE – Adverse Events  &  SUPPAE
# ---------------------------------------------------------------------------
ae_rows = []
suppae_rows = []

for _, row in ae_raw.iterrows():
    subjid = row['SubjectID'].strip()
    usubjid = f'{STUDYID}-{subjid}'
    rfstdtc = rfstdtc_map.get(subjid, '')

    aeterm = row['AE_VerbatimTerm'].strip().upper()
    vt_key = row['AE_VerbatimTerm'].strip().lower()
    entry = dict_lookup.get(vt_key, {})
    aedecod = entry.get('pt', aeterm)
    aebodsys = entry.get('soc', '')

    aestdtc = parse_date(row['OnsetDate'])
    aeendtc = parse_date(row['ResolutionDate'])
    aeseq = int(row['AE_Number'])

    aesev = AESEV_MAP.get(row['SeverityGrade'].strip(),
                          row['SeverityGrade'].strip())
    aeser = AESER_MAP.get(row['Serious'].strip(), row['Serious'].strip())
    aeout = AEOUT_MAP.get(row['Outcome'].strip(), row['Outcome'].strip())
    aeacn = AEACN_MAP.get(row['ActionTaken'].strip(),
                          row['ActionTaken'].strip())
    aerel = AEREL_MAP.get(row['CausalityAssessment'].strip(),
                          row['CausalityAssessment'].strip())

    aestdy = study_day(aestdtc, rfstdtc) if aestdtc else ''
    aeendy = study_day(aeendtc, rfstdtc) if aeendtc else ''

    ae_rows.append({
        'STUDYID': STUDYID, 'DOMAIN': 'AE',
        'USUBJID': usubjid, 'AESEQ': aeseq,
        'AETERM': aeterm, 'AEDECOD': aedecod, 'AEBODSYS': aebodsys,
        'AESTDTC': aestdtc, 'AEENDTC': aeendtc if aeendtc else '',
        'AESEV': aesev, 'AESER': aeser,
        'AEACN': aeacn, 'AEOUT': aeout, 'AEREL': aerel,
        'AESTDY': aestdy, 'AEENDY': aeendy if aeendy != '' else '',
    })

    # SUPPAE: AE of Special Interest flag
    aesi_raw = str(row.get('AE_of_Special_Interest', 'No')).strip()
    aesifl = 'Y' if aesi_raw == 'Yes' else 'N'
    suppae_rows.append({
        'STUDYID': STUDYID, 'RDOMAIN': 'AE',
        'USUBJID': usubjid,
        'IDVAR': 'AESEQ', 'IDVARVAL': str(aeseq),
        'QNAM': 'AESIFL',
        'QLABEL': 'AE of Special Interest Flag',
        'QVAL': aesifl,
        'QORIG': 'CRF', 'QEVAL': '',
    })

pd.DataFrame(ae_rows).to_csv(f'{OUT}/ae.csv', index=False)
pd.DataFrame(suppae_rows).to_csv(f'{OUT}/suppae.csv', index=False)

# ---------------------------------------------------------------------------
# VS – Vital Signs
# ---------------------------------------------------------------------------
vs_rows = []
vsseq = {}

for _, row in vs_raw.iterrows():
    subjid = row['SubjectID'].strip()
    usubjid = f'{STUDYID}-{subjid}'
    rfstdtc = rfstdtc_map.get(subjid, '')

    param = row['Parameter'].strip()
    vstestcd, vstest = VSTESTCD_MAP.get(param, (param[:8].upper(), param))

    vsorres = row['Value'].strip()
    raw_unit = row['Units'].strip()

    # Unit standardisation
    if param == 'Body Weight' and raw_unit.lower() in ('lbs', 'lb'):
        vsorresu = 'LB'
        vsstresn = round(float(vsorres) * 0.453592, 1)
        vsstresc = str(vsstresn)
        vsstresu = 'kg'
    elif param == 'Pulse Rate' and raw_unit.lower() == 'bpm':
        vsorresu = 'beats/min'
        vsstresn = float(vsorres)
        vsstresc = vsorres
        vsstresu = 'beats/min'
    else:
        vsorresu = raw_unit
        vsstresn = float(vsorres)
        vsstresc = vsorres
        vsstresu = raw_unit

    visit_name = row['VisitName'].strip()
    visitnum, visit = VISIT_MAP.get(visit_name, (99, visit_name.upper()))

    vsdtc = parse_date(row['VisitDate'])
    vsdy = study_day(vsdtc, rfstdtc) if vsdtc and rfstdtc else ''

    vsseq.setdefault(subjid, 0)
    vsseq[subjid] += 1

    vs_rows.append({
        'STUDYID': STUDYID, 'DOMAIN': 'VS',
        'USUBJID': usubjid, 'VSSEQ': vsseq[subjid],
        'VSTESTCD': vstestcd, 'VSTEST': vstest,
        'VSORRES': vsorres, 'VSORRESU': vsorresu,
        'VSSTRESC': vsstresc, 'VSSTRESN': vsstresn, 'VSSTRESU': vsstresu,
        'VISITNUM': visitnum, 'VISIT': visit,
        'VSDTC': vsdtc, 'VSDY': vsdy,
    })

pd.DataFrame(vs_rows).to_csv(f'{OUT}/vs.csv', index=False)

# ---------------------------------------------------------------------------
# EX – Exposure
# ---------------------------------------------------------------------------
ex_rows = []

for idx, row in ex_raw.iterrows():
    subjid = row['SubjectID'].strip()
    usubjid = f'{STUDYID}-{subjid}'

    trt = row['Treatment'].strip()
    extrt = trt.upper() if trt.lower() != 'placebo' else 'PLACEBO'

    ex_rows.append({
        'STUDYID': STUDYID, 'DOMAIN': 'EX',
        'USUBJID': usubjid, 'EXSEQ': idx + 1,
        'EXTRT': extrt,
        'EXDOSE': int(row['DoseAmount']),
        'EXDOSU': row['DoseUnit'].strip().lower(),
        'EXDOSFRM': 'TABLET',
        'EXDOSFRQ': 'QD',
        'EXSTDTC': parse_date(row['FirstDoseDate']),
        'EXENDTC': parse_date(row['LastDoseDate']),
    })

pd.DataFrame(ex_rows).to_csv(f'{OUT}/ex.csv', index=False)

# ---------------------------------------------------------------------------
# TS – Trial Summary
# ---------------------------------------------------------------------------
ts_params = [
    ('SSTDTC', 'Study Start Date', '2024-01-15'),
    ('SENDTC', 'Study End Date', '2024-04-30'),
    ('TPHASE', 'Trial Phase Classification', 'PHASE II TRIAL'),
    ('TITLE', 'Trial Title',
     'A Phase II, Randomized, Double-Blind, Placebo-Controlled Study to '
     'Evaluate the Efficacy and Safety of Antihypertensin-X 10 mg in '
     'Patients with Essential Hypertension'),
    ('STYPE', 'Study Type', 'INTERVENTIONAL'),
    ('TBLIND', 'Trial Blinding Schema', 'DOUBLE BLIND'),
    ('RANDOM', 'Trial is Randomized', 'Y'),
    ('NARMS', 'Planned Number of Arms', '2'),
    ('INTMODEL', 'Intervention Model', 'PARALLEL'),
    ('INDIC', 'Trial Disease/Condition Indication', 'ESSENTIAL HYPERTENSION'),
    ('TRT', 'Investigational Therapy or Treatment', 'ANTIHYPERTENSIN-X'),
    ('PCNTRL', 'Placebo Control', 'Y'),
    ('LENGTH', 'Trial Length', 'P8W'),
    ('PLTEFFTM', 'Planned Time of First Efficacy Assessment', 'P2W'),
    ('SPONSOR', 'Clinical Study Sponsor', 'PharmaCorp Inc.'),
    ('REGID', 'Registry Identifier', 'IND 123456'),
    ('AGEMIN', 'Planned Minimum Age of Subjects', 'P18Y'),
    ('AGEMAX', 'Planned Maximum Age of Subjects', 'P99Y'),
]

ts_rows = []
for seq, (parmcd, parm, val) in enumerate(ts_params, start=1):
    ts_rows.append({
        'STUDYID': STUDYID, 'DOMAIN': 'TS',
        'TSSEQ': seq,
        'TSPARMCD': parmcd, 'TSPARM': parm, 'TSVAL': val,
    })

pd.DataFrame(ts_rows).to_csv(f'{OUT}/ts.csv', index=False)

print('SDTM datasets written to', OUT)
print('Domains: dm.csv, ae.csv, vs.csv, ex.csv, suppae.csv, ts.csv')
