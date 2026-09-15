#!/usr/bin/env python3
"""SDTM Domain Builder — Converts raw clinical trial CRF data to SDTM-conformant
SAS Transport v5 (XPT) datasets with Define-XML 2.0 metadata.

Implements CDISC SDTM Implementation Guide v3.3 conformance rules for:
DM, AE, EX, VS, DS, TS, and SUPPAE domains.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime

import pandas as pd
import pyreadstat
from lxml import etree

INPUT_DIR = "/app/raw_data"
OUTPUT_DIR = "/app/sdtm_output"

# Unit conversion specifications
UNIT_CONVERSIONS = {
    "F": {"to": "C", "fn": lambda v: round((v - 32) * 5 / 9, 1)},
    "lbs": {"to": "kg", "fn": lambda v: round(v * 0.453592, 1)},
    "in": {"to": "cm", "fn": lambda v: round(v * 2.54, 1)},
}

TESTCD_MAP = {
    "Systolic Blood Pressure": ("SYSBP", "Systolic Blood Pressure"),
    "Diastolic Blood Pressure": ("DIABP", "Diastolic Blood Pressure"),
    "Heart Rate": ("HR", "Heart Rate"),
    "Temperature": ("TEMP", "Temperature"),
    "Weight": ("WEIGHT", "Weight"),
    "Height": ("HEIGHT", "Height"),
}

VISITNUM_MAP = {"Screening": 1, "Baseline": 2, "Week 4": 3}


# ===== Date Parsing =====


def parse_date(date_str):
    """Parse complete date formats to ISO 8601 (YYYY-MM-DD)."""
    if not date_str or date_str.strip() == "":
        return ""
    date_str = date_str.strip()
    for fmt in ["%Y-%m-%d", "%d-%b-%Y", "%d/%m/%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date: '{date_str}'")


def parse_date_flexible(date_str):
    """Parse date string, returning (iso_str, is_partial) tuple.

    Complete dates -> ("2024-01-15", False)
    Partial dates  -> ("2024-02", True)
    """
    if not date_str or date_str.strip() == "":
        return "", False
    date_str = date_str.strip()
    # Try partial (month-year) formats first
    for fmt in ["%b-%Y", "%b %Y", "%B-%Y", "%B %Y"]:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m"), True
        except ValueError:
            continue
    # Try complete formats
    return parse_date(date_str), False


def parse_date_obj(date_str):
    """Parse date string to date object, or None if empty/partial."""
    if not date_str or date_str.strip() == "":
        return None
    try:
        iso = parse_date(date_str)
        return datetime.strptime(iso, "%Y-%m-%d").date()
    except ValueError:
        return None


# ===== Calculation Helpers =====


def calc_study_day(event_date_str, ref_date_str):
    """Calculate study day with no Day 0 rule."""
    ed = parse_date_obj(event_date_str)
    rd = parse_date_obj(ref_date_str)
    if ed is None or rd is None:
        return None
    diff = (ed - rd).days
    return diff + 1 if diff >= 0 else diff


def calc_age(birth_date_str, ref_date_str):
    """Calculate age in complete years at reference date."""
    birth = parse_date_obj(birth_date_str)
    ref = parse_date_obj(ref_date_str)
    if birth is None or ref is None:
        return None
    age = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        age -= 1
    return age


def derive_epoch(event_date_str, rfstdtc, last_dose_date, is_partial=False):
    """Derive EPOCH based on event date relative to reference period."""
    if not rfstdtc:
        return "SCREENING"
    if not event_date_str:
        return ""
    if is_partial:
        event_ym = event_date_str[:7]
        start_ym = rfstdtc[:7]
        end_ym = last_dose_date[:7] if last_dose_date else start_ym
        if event_ym < start_ym:
            return "SCREENING"
        elif event_ym > end_ym:
            return "FOLLOW-UP"
        return "TREATMENT"
    event_date = parse_date_obj(event_date_str)
    ref_start = parse_date_obj(rfstdtc)
    ref_end = parse_date_obj(last_dose_date) if last_dose_date else ref_start
    if event_date is None:
        return ""
    if event_date < ref_start:
        return "SCREENING"
    elif event_date <= ref_end:
        return "TREATMENT"
    return "FOLLOW-UP"


# ===== Value Mappers =====


def map_severity(grade):
    return {"1": "MILD", "2": "MODERATE", "3": "SEVERE"}.get(str(grade).strip(), str(grade))


def map_sex(sex_str):
    s = sex_str.strip().upper()
    return "M" if s in ("MALE", "M") else "F" if s in ("FEMALE", "F") else s


def map_serious(flag):
    f = str(flag).strip().upper()
    return "Y" if f in ("YES", "Y", "TRUE", "1") else "N" if f in ("NO", "N", "FALSE", "0") else f


# ===== I/O Helpers =====


def read_csv_file(filepath):
    with open(filepath) as f:
        return list(csv.DictReader(f))


def read_json_file(filepath):
    with open(filepath) as f:
        return json.load(f)


def write_xpt(rows, columns, labels, numeric_cols, filepath, ds_name):
    """Write data as SAS Transport v5 (XPT) file with correct metadata."""
    df = pd.DataFrame(rows)
    for col in columns:
        if col not in df.columns:
            df[col] = None
    df = df[columns]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    char_cols = [c for c in columns if c not in numeric_cols]
    for col in char_cols:
        df[col] = df[col].fillna("").astype(str)

    col_labels = {k: v[:40] for k, v in labels.items() if k in columns}
    pyreadstat.write_xport(df, filepath, file_label=ds_name, column_labels=col_labels)


# ===== Domain Builders =====


def build_dm(protocol, subjects, dispositions):
    study_id = protocol["study_id"]

    death_subjects = {}
    for d in dispositions:
        if d["disposition_event"].strip().upper() == "DEATH":
            death_subjects[d["subj_id"].strip()] = parse_date(d["disposition_date"])

    rows = []
    for s in subjects:
        subj_id = s["subj_id"].strip()
        usubjid = f"{study_id}-{subj_id}"

        first_dose = parse_date(s.get("first_dose_date", ""))
        last_dose = parse_date(s.get("last_dose_date", ""))
        study_end = parse_date(s.get("study_end_date", ""))
        consent_date = parse_date(s.get("informed_consent_date", ""))
        birth_date = parse_date(s.get("dob", ""))

        rfstdtc = first_dose
        rfendtc = study_end
        rfxstdtc = first_dose
        rfxendtc = last_dose

        arm_raw = s.get("assigned_arm", "").strip()
        if not arm_raw:
            arm, armcd = "Screen Failure", "SCRNFAIL"
        elif arm_raw == "Drug A 50mg":
            arm, armcd = arm_raw, "DRUGA50"
        elif arm_raw == "Placebo":
            arm, armcd = arm_raw, "PLACEBO"
        else:
            arm, armcd = arm_raw, arm_raw.upper().replace(" ", "")[:8]

        age_ref = rfstdtc if rfstdtc else consent_date
        age = calc_age(birth_date, age_ref)

        dthdtc = death_subjects.get(subj_id, "")
        dthfl = "Y" if dthdtc else ""

        rows.append({
            "STUDYID": study_id, "DOMAIN": "DM", "USUBJID": usubjid,
            "SUBJID": subj_id, "RFSTDTC": rfstdtc, "RFENDTC": rfendtc,
            "RFXSTDTC": rfxstdtc, "RFXENDTC": rfxendtc, "RFICDTC": consent_date,
            "DTHDTC": dthdtc, "DTHFL": dthfl,
            "SITEID": s.get("site_id", "").strip(),
            "BRTHDTC": birth_date, "AGE": age, "AGEU": "YEARS",
            "SEX": map_sex(s.get("sex", "")),
            "RACE": s.get("race", "").strip(),
            "ETHNIC": s.get("ethnicity", "").strip(),
            "ARMCD": armcd, "ARM": arm, "ACTARMCD": armcd, "ACTARM": arm,
            "COUNTRY": "USA",
        })

    columns = [
        "STUDYID", "DOMAIN", "USUBJID", "SUBJID", "RFSTDTC", "RFENDTC",
        "RFXSTDTC", "RFXENDTC", "RFICDTC", "DTHDTC", "DTHFL", "SITEID",
        "BRTHDTC", "AGE", "AGEU", "SEX", "RACE", "ETHNIC",
        "ARMCD", "ARM", "ACTARMCD", "ACTARM", "COUNTRY",
    ]
    labels = {
        "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation",
        "USUBJID": "Unique Subject Identifier", "SUBJID": "Subject Identifier for the Study",
        "RFSTDTC": "Subject Reference Start Date/Time", "RFENDTC": "Subject Reference End Date/Time",
        "RFXSTDTC": "Date/Time of First Study Treatment", "RFXENDTC": "Date/Time of Last Study Treatment",
        "RFICDTC": "Date/Time of Informed Consent", "DTHDTC": "Date/Time of Death",
        "DTHFL": "Subject Death Flag", "SITEID": "Study Site Identifier",
        "BRTHDTC": "Date/Time of Birth", "AGE": "Age", "AGEU": "Age Units",
        "SEX": "Sex", "RACE": "Race", "ETHNIC": "Ethnicity",
        "ARMCD": "Planned Arm Code", "ARM": "Description of Planned Arm",
        "ACTARMCD": "Actual Arm Code", "ACTARM": "Description of Actual Arm",
        "COUNTRY": "Country",
    }
    numeric_cols = ["AGE"]
    return rows, columns, labels, numeric_cols


def build_ae(protocol, adverse_events, subj_ref):
    study_id = protocol["study_id"]
    ae_rows, suppae_rows = [], []
    seq_counters = defaultdict(int)

    for ae in adverse_events:
        subj_id = ae["subj_id"].strip()
        usubjid = f"{study_id}-{subj_id}"
        ref = subj_ref.get(subj_id, {})
        rfstdtc = ref.get("rfstdtc", "")
        last_dose = ref.get("last_dose_date", "")

        seq_counters[subj_id] += 1
        aeseq = seq_counters[subj_id]

        aestdtc, aest_partial = parse_date_flexible(ae.get("start_date", ""))
        aeendtc, aeend_partial = parse_date_flexible(ae.get("end_date", ""))

        aestdy = None if aest_partial else calc_study_day(aestdtc, rfstdtc)
        aeendy = None if aeend_partial else calc_study_day(aeendtc, rfstdtc)

        epoch = derive_epoch(aestdtc, rfstdtc, last_dose, is_partial=aest_partial)

        ae_rows.append({
            "STUDYID": study_id, "DOMAIN": "AE", "USUBJID": usubjid,
            "AESEQ": aeseq, "AETERM": ae.get("ae_verbatim", "").strip(),
            "AEDECOD": ae.get("ae_decoded", "").strip(),
            "AEBODSYS": ae.get("body_system", "").strip(),
            "AESEV": map_severity(ae.get("severity_grade", "")),
            "AESER": map_serious(ae.get("serious_flag", "")),
            "AEREL": ae.get("relationship", "").strip(),
            "AEACN": ae.get("action_taken", "").strip(),
            "AEOUT": ae.get("outcome", "").strip(),
            "AESTDTC": aestdtc, "AEENDTC": aeendtc,
            "AESTDY": aestdy, "AEENDY": aeendy,
            "EPOCH": epoch,
        })

        reaction_loc = ae.get("reaction_location", "").strip()
        if reaction_loc:
            suppae_rows.append({
                "STUDYID": study_id, "RDOMAIN": "AE", "USUBJID": usubjid,
                "IDVAR": "AESEQ", "IDVARVAL": str(aeseq),
                "QNAM": "AELOC", "QLABEL": "Location of the Reaction",
                "QVAL": reaction_loc, "QORIG": "CRF", "QEVAL": "",
            })

    ae_columns = [
        "STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM", "AEDECOD",
        "AEBODSYS", "AESEV", "AESER", "AEREL", "AEACN", "AEOUT",
        "AESTDTC", "AEENDTC", "AESTDY", "AEENDY", "EPOCH",
    ]
    ae_labels = {
        "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation",
        "USUBJID": "Unique Subject Identifier", "AESEQ": "Sequence Number",
        "AETERM": "Reported Term for the AE", "AEDECOD": "Dictionary-Derived Term",
        "AEBODSYS": "Body System or Organ Class", "AESEV": "Severity/Intensity",
        "AESER": "Serious Event", "AEREL": "Causality",
        "AEACN": "Action Taken with Study Treatment", "AEOUT": "Outcome of Adverse Event",
        "AESTDTC": "Start Date/Time of AE", "AEENDTC": "End Date/Time of AE",
        "AESTDY": "Study Day of Start of AE", "AEENDY": "Study Day of End of AE",
        "EPOCH": "Epoch",
    }
    ae_numeric = ["AESEQ", "AESTDY", "AEENDY"]

    suppae_columns = [
        "STUDYID", "RDOMAIN", "USUBJID", "IDVAR", "IDVARVAL",
        "QNAM", "QLABEL", "QVAL", "QORIG", "QEVAL",
    ]
    suppae_labels = {
        "STUDYID": "Study Identifier", "RDOMAIN": "Related Domain Abbreviation",
        "USUBJID": "Unique Subject Identifier", "IDVAR": "Identifying Variable",
        "IDVARVAL": "Identifying Variable Value", "QNAM": "Qualifier Variable Name",
        "QLABEL": "Qualifier Variable Label", "QVAL": "Data Value",
        "QORIG": "Origin", "QEVAL": "Evaluator",
    }

    return (ae_rows, ae_columns, ae_labels, ae_numeric,
            suppae_rows, suppae_columns, suppae_labels)


def build_ex(protocol, exposures, subj_ref):
    study_id = protocol["study_id"]
    rows = []
    seq_counters = defaultdict(int)

    for ex in exposures:
        subj_id = ex["subj_id"].strip()
        usubjid = f"{study_id}-{subj_id}"
        ref = subj_ref.get(subj_id, {})
        rfstdtc = ref.get("rfstdtc", "")
        last_dose = ref.get("last_dose_date", "")

        seq_counters[subj_id] += 1
        exseq = seq_counters[subj_id]

        exstdtc = parse_date(ex.get("start_date", ""))
        exendtc = parse_date(ex.get("end_date", ""))
        exstdy = calc_study_day(exstdtc, rfstdtc)
        exendy = calc_study_day(exendtc, rfstdtc) if exendtc else None

        dose_val = ex.get("dose", "").strip()
        try:
            dose_num = float(dose_val)
        except (ValueError, TypeError):
            dose_num = None

        epoch = derive_epoch(exstdtc, rfstdtc, last_dose)

        rows.append({
            "STUDYID": study_id, "DOMAIN": "EX", "USUBJID": usubjid,
            "EXSEQ": exseq, "EXTRT": ex.get("treatment", "").strip(),
            "EXDOSE": dose_num, "EXDOSU": ex.get("dose_unit", "").strip(),
            "EXDOSFRQ": ex.get("frequency", "").strip(),
            "EXROUTE": ex.get("route", "").strip(),
            "EXSTDTC": exstdtc, "EXENDTC": exendtc,
            "EXSTDY": exstdy, "EXENDY": exendy,
            "EXADJ": ex.get("dose_adjustment_reason", "").strip(),
            "EPOCH": epoch,
        })

    columns = [
        "STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT", "EXDOSE",
        "EXDOSU", "EXDOSFRQ", "EXROUTE", "EXSTDTC", "EXENDTC",
        "EXSTDY", "EXENDY", "EXADJ", "EPOCH",
    ]
    labels = {
        "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation",
        "USUBJID": "Unique Subject Identifier", "EXSEQ": "Sequence Number",
        "EXTRT": "Name of Treatment", "EXDOSE": "Dose",
        "EXDOSU": "Dose Units", "EXDOSFRQ": "Dosing Frequency per Interval",
        "EXROUTE": "Route of Administration",
        "EXSTDTC": "Start Date/Time of Treatment", "EXENDTC": "End Date/Time of Treatment",
        "EXSTDY": "Study Day of Start of Treatment", "EXENDY": "Study Day of End of Treatment",
        "EXADJ": "Reason for Dose Adjustment", "EPOCH": "Epoch",
    }
    numeric_cols = ["EXSEQ", "EXDOSE", "EXSTDY", "EXENDY"]
    return rows, columns, labels, numeric_cols


def build_vs(protocol, vitals, subj_ref):
    study_id = protocol["study_id"]
    rows = []
    seq_counters = defaultdict(int)

    for v in vitals:
        subj_id = v["subj_id"].strip()
        usubjid = f"{study_id}-{subj_id}"
        ref = subj_ref.get(subj_id, {})
        rfstdtc = ref.get("rfstdtc", "")
        last_dose = ref.get("last_dose_date", "")

        seq_counters[subj_id] += 1
        vsseq = seq_counters[subj_id]

        test_name = v.get("test_name", "").strip()
        testcd, test_label = TESTCD_MAP.get(test_name, (test_name[:8].upper(), test_name))

        visit = v.get("visit", "").strip()
        visitnum = VISITNUM_MAP.get(visit, 99)

        vsdtc = parse_date(v.get("visit_date", ""))
        vsdy = calc_study_day(vsdtc, rfstdtc)

        result_str = v.get("result", "").strip()
        unit = v.get("unit", "").strip()
        position = v.get("position", "").strip()

        try:
            result_num = float(result_str)
        except (ValueError, TypeError):
            result_num = None

        # Unit standardization
        if unit in UNIT_CONVERSIONS and result_num is not None:
            conv = UNIT_CONVERSIONS[unit]
            vsstresn = conv["fn"](result_num)
            vsstresu = conv["to"]
        else:
            vsstresn = result_num
            vsstresu = unit

        vsstresc = str(vsstresn) if vsstresn is not None else ""
        vsblfl = "Y" if visit == "Baseline" else ""

        epoch = derive_epoch(vsdtc, rfstdtc, last_dose)

        rows.append({
            "STUDYID": study_id, "DOMAIN": "VS", "USUBJID": usubjid,
            "VSSEQ": vsseq, "VSTESTCD": testcd, "VSTEST": test_label,
            "VSPOS": position, "VSORRES": result_str, "VSORRESU": unit,
            "VSSTRESC": vsstresc, "VSSTRESN": vsstresn, "VSSTRESU": vsstresu,
            "VSBLFL": vsblfl, "VISITNUM": visitnum, "VISIT": visit,
            "VSDTC": vsdtc, "VSDY": vsdy, "EPOCH": epoch,
        })

    columns = [
        "STUDYID", "DOMAIN", "USUBJID", "VSSEQ", "VSTESTCD", "VSTEST",
        "VSPOS", "VSORRES", "VSORRESU", "VSSTRESC", "VSSTRESN", "VSSTRESU",
        "VSBLFL", "VISITNUM", "VISIT", "VSDTC", "VSDY", "EPOCH",
    ]
    labels = {
        "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation",
        "USUBJID": "Unique Subject Identifier", "VSSEQ": "Sequence Number",
        "VSTESTCD": "Vital Signs Test Short Name", "VSTEST": "Vital Signs Test Name",
        "VSPOS": "Position of Subject",
        "VSORRES": "Result or Finding in Orig Units", "VSORRESU": "Original Units",
        "VSSTRESC": "Char Result/Finding in Std Format",
        "VSSTRESN": "Numeric Result/Finding in Std Units", "VSSTRESU": "Standard Units",
        "VSBLFL": "Baseline Flag", "VISITNUM": "Visit Number", "VISIT": "Visit Name",
        "VSDTC": "Date/Time of Measurements", "VSDY": "Study Day of Vital Signs",
        "EPOCH": "Epoch",
    }
    numeric_cols = ["VSSEQ", "VSSTRESN", "VISITNUM", "VSDY"]
    return rows, columns, labels, numeric_cols


def build_ds(protocol, dispositions, subj_ref):
    study_id = protocol["study_id"]
    milestone_events = {"INFORMED CONSENT OBTAINED", "RANDOMIZED"}

    rows = []
    seq_counters = defaultdict(int)

    for d in dispositions:
        subj_id = d["subj_id"].strip()
        usubjid = f"{study_id}-{subj_id}"
        ref = subj_ref.get(subj_id, {})
        rfstdtc = ref.get("rfstdtc", "")
        last_dose = ref.get("last_dose_date", "")

        seq_counters[subj_id] += 1
        dsseq = seq_counters[subj_id]

        event = d.get("disposition_event", "").strip().upper()
        dsstdtc = parse_date(d.get("disposition_date", ""))
        dsstdy = calc_study_day(dsstdtc, rfstdtc)

        dscat = "PROTOCOL MILESTONE" if event in milestone_events else "DISPOSITION EVENT"
        epoch = derive_epoch(dsstdtc, rfstdtc, last_dose)

        rows.append({
            "STUDYID": study_id, "DOMAIN": "DS", "USUBJID": usubjid,
            "DSSEQ": dsseq, "DSTERM": event, "DSDECOD": event,
            "DSCAT": dscat, "DSSTDTC": dsstdtc, "DSSTDY": dsstdy,
            "EPOCH": epoch,
        })

    columns = [
        "STUDYID", "DOMAIN", "USUBJID", "DSSEQ", "DSTERM", "DSDECOD",
        "DSCAT", "DSSTDTC", "DSSTDY", "EPOCH",
    ]
    labels = {
        "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation",
        "USUBJID": "Unique Subject Identifier", "DSSEQ": "Sequence Number",
        "DSTERM": "Reported Term for Disposition Event",
        "DSDECOD": "Standardized Disposition Term",
        "DSCAT": "Category for Disposition Event",
        "DSSTDTC": "Start Date/Time of Disposition",
        "DSSTDY": "Study Day of Start of Disposition",
        "EPOCH": "Epoch",
    }
    numeric_cols = ["DSSEQ", "DSSTDY"]
    return rows, columns, labels, numeric_cols


def build_ts(protocol):
    study_id = protocol["study_id"]
    ts_data = protocol.get("trial_summary", {})

    params = [
        ("SSTDTC", "Study Start Date", ts_data.get("SSTDTC", "")),
        ("SENDTC", "Study End Date", ts_data.get("SENDTC", "")),
        ("INDIC", "Trial Disease/Condition Indication", ts_data.get("INDIC", "")),
        ("TRT", "Investigational Therapy or Treatment", ts_data.get("TRT", "")),
        ("PLTEFM", "Planned Trial Event Flow Model", ts_data.get("PLTEFM", "")),
        ("STYPE", "Study Type", ts_data.get("STYPE", "")),
        ("TPHASE", "Trial Phase Classification", ts_data.get("TPHASE", "")),
        ("PCLAS", "Pharmacologic Class", ts_data.get("PCLAS", "")),
        ("RANDOM", "Trial is Randomized", ts_data.get("RANDOM", "")),
        ("BLIND", "Trial Blinding Schema", ts_data.get("BLIND", "")),
        ("TITLE", "Trial Title", protocol.get("study_title", "")),
        ("SPONSOR", "Clinical Study Sponsor", protocol.get("sponsor", "")),
        ("NARMS", "Planned Number of Arms", str(len(protocol.get("arms", [])))),
    ]

    rows = []
    for seq, (parmcd, parm, val) in enumerate(params, 1):
        rows.append({
            "STUDYID": study_id, "DOMAIN": "TS", "TSSEQ": seq,
            "TSPARMCD": parmcd, "TSPARM": parm, "TSVAL": val,
        })

    columns = ["STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM", "TSVAL"]
    labels = {
        "STUDYID": "Study Identifier", "DOMAIN": "Domain Abbreviation",
        "TSSEQ": "Sequence Number", "TSPARMCD": "Trial Summary Parameter Short Name",
        "TSPARM": "Trial Summary Parameter", "TSVAL": "Parameter Value",
    }
    numeric_cols = ["TSSEQ"]
    return rows, columns, labels, numeric_cols


# ===== Define-XML 2.0 Generation =====


def generate_define_xml(domains_meta, protocol, output_path):
    """Generate Define-XML 2.0 metadata document."""
    ODM_NS = "http://www.cdisc.org/ns/odm/v1.3"
    DEF_NS = "http://www.cdisc.org/ns/def/v2.0"
    XL_NS = "http://www.w3.org/1999/xlink"
    XML_NS = "http://www.w3.org/XML/1998/namespace"

    nsmap = {None: ODM_NS, "def": DEF_NS, "xlink": XL_NS}

    root = etree.Element(f"{{{ODM_NS}}}ODM", nsmap=nsmap)
    root.set("ODMVersion", "1.3.2")
    root.set("FileType", "Snapshot")
    root.set("FileOID", "DEF.XYZ-2024-001")

    study = etree.SubElement(root, f"{{{ODM_NS}}}Study")
    study.set("OID", protocol["study_id"])

    gv = etree.SubElement(study, f"{{{ODM_NS}}}GlobalVariables")
    sn = etree.SubElement(gv, f"{{{ODM_NS}}}StudyName")
    sn.text = protocol["study_id"]
    sd = etree.SubElement(gv, f"{{{ODM_NS}}}StudyDescription")
    sd.text = protocol.get("study_title", "")
    pn = etree.SubElement(gv, f"{{{ODM_NS}}}ProtocolName")
    pn.text = protocol["study_id"]

    mdv = etree.SubElement(study, f"{{{ODM_NS}}}MetaDataVersion")
    mdv.set("OID", "MDV.001")
    mdv.set("Name", "SDTM")
    mdv.set(f"{{{DEF_NS}}}DefineVersion", "2.0.0")
    mdv.set(f"{{{DEF_NS}}}StandardName", "SDTMIG")
    mdv.set(f"{{{DEF_NS}}}StandardVersion", "3.3")

    # Collect all ItemDef entries
    all_items = []

    for domain_name, info in domains_meta.items():
        igd = etree.SubElement(mdv, f"{{{ODM_NS}}}ItemGroupDef")
        igd.set("OID", f"IG.{domain_name}")
        igd.set("Name", domain_name)
        igd.set("SASDatasetName", domain_name)
        igd.set("Repeating", "No" if domain_name == "DM" else "Yes")
        igd.set("IsReferenceData", "No")
        igd.set(f"{{{DEF_NS}}}Structure", info.get("structure", ""))
        igd.set(f"{{{DEF_NS}}}Class", info.get("class", ""))

        for i, (var_name, var_label) in enumerate(info["variables"], 1):
            item_oid = f"IT.{domain_name}.{var_name}"
            iref = etree.SubElement(igd, f"{{{ODM_NS}}}ItemRef")
            iref.set("ItemOID", item_oid)
            iref.set("OrderNumber", str(i))
            iref.set("Mandatory", "Yes" if var_name in info.get("required", []) else "No")

            is_numeric = var_name in info.get("numeric", [])
            all_items.append((item_oid, var_name, var_label, is_numeric))

    # Write ItemDef elements
    for item_oid, var_name, var_label, is_numeric in all_items:
        idef = etree.SubElement(mdv, f"{{{ODM_NS}}}ItemDef")
        idef.set("OID", item_oid)
        idef.set("Name", var_name)
        idef.set("DataType", "float" if is_numeric else "text")
        idef.set("SASFieldName", var_name)
        idef.set(f"{{{DEF_NS}}}Label", var_label[:40])
        idef.set("Length", "8" if is_numeric else "200")

    # Write CodeList elements
    codelists = {
        "SEX": {"M": "Male", "F": "Female"},
        "AESEV": {"MILD": "Mild", "MODERATE": "Moderate", "SEVERE": "Severe"},
        "NY": {"Y": "Yes", "N": "No"},
        "EPOCH": {"SCREENING": "Screening", "TREATMENT": "Treatment", "FOLLOW-UP": "Follow-Up"},
    }

    for cl_name, values in codelists.items():
        cl = etree.SubElement(mdv, f"{{{ODM_NS}}}CodeList")
        cl.set("OID", f"CL.{cl_name}")
        cl.set("Name", cl_name)
        cl.set("DataType", "text")
        for code, decode in values.items():
            cli = etree.SubElement(cl, f"{{{ODM_NS}}}CodeListItem")
            cli.set("CodedValue", code)
            dec = etree.SubElement(cli, f"{{{ODM_NS}}}Decode")
            tt = etree.SubElement(dec, f"{{{ODM_NS}}}TranslatedText")
            tt.set(f"{{{XML_NS}}}lang", "en")
            tt.text = decode

    tree = etree.ElementTree(root)
    tree.write(output_path, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ===== Main =====


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    protocol = read_json_file(os.path.join(INPUT_DIR, "protocol.json"))
    subjects = read_csv_file(os.path.join(INPUT_DIR, "subjects.csv"))
    adverse_events = read_csv_file(os.path.join(INPUT_DIR, "adverse_events.csv"))
    exposures = read_csv_file(os.path.join(INPUT_DIR, "exposure.csv"))
    vitals = read_csv_file(os.path.join(INPUT_DIR, "vital_signs.csv"))
    dispositions = read_csv_file(os.path.join(INPUT_DIR, "disposition.csv"))

    # Build subject reference data for EPOCH derivation
    subj_ref = {}
    for s in subjects:
        sid = s["subj_id"].strip()
        subj_ref[sid] = {
            "rfstdtc": parse_date(s.get("first_dose_date", "")),
            "last_dose_date": parse_date(s.get("last_dose_date", "")),
        }

    # Build and write DM
    dm_rows, dm_cols, dm_labels, dm_num = build_dm(protocol, subjects, dispositions)
    write_xpt(dm_rows, dm_cols, dm_labels, dm_num,
              os.path.join(OUTPUT_DIR, "dm.xpt"), "DM")

    # Build and write AE + SUPPAE
    (ae_rows, ae_cols, ae_labels, ae_num,
     suppae_rows, suppae_cols, suppae_labels) = build_ae(protocol, adverse_events, subj_ref)
    write_xpt(ae_rows, ae_cols, ae_labels, ae_num,
              os.path.join(OUTPUT_DIR, "ae.xpt"), "AE")
    write_xpt(suppae_rows, suppae_cols, suppae_labels, [],
              os.path.join(OUTPUT_DIR, "suppae.xpt"), "SUPPAE")

    # Build and write EX
    ex_rows, ex_cols, ex_labels, ex_num = build_ex(protocol, exposures, subj_ref)
    write_xpt(ex_rows, ex_cols, ex_labels, ex_num,
              os.path.join(OUTPUT_DIR, "ex.xpt"), "EX")

    # Build and write VS
    vs_rows, vs_cols, vs_labels, vs_num = build_vs(protocol, vitals, subj_ref)
    write_xpt(vs_rows, vs_cols, vs_labels, vs_num,
              os.path.join(OUTPUT_DIR, "vs.xpt"), "VS")

    # Build and write DS
    ds_rows, ds_cols, ds_labels, ds_num = build_ds(protocol, dispositions, subj_ref)
    write_xpt(ds_rows, ds_cols, ds_labels, ds_num,
              os.path.join(OUTPUT_DIR, "ds.xpt"), "DS")

    # Build and write TS
    ts_rows, ts_cols, ts_labels, ts_num = build_ts(protocol)
    write_xpt(ts_rows, ts_cols, ts_labels, ts_num,
              os.path.join(OUTPUT_DIR, "ts.xpt"), "TS")

    # Generate Define-XML 2.0
    domains_meta = {
        "DM": {
            "structure": "One record per subject",
            "class": "SPECIAL PURPOSE",
            "variables": [(c, dm_labels.get(c, c)) for c in dm_cols],
            "required": ["STUDYID", "DOMAIN", "USUBJID", "SUBJID", "RFSTDTC", "SITEID", "AGE", "AGEU", "SEX", "RACE", "ARMCD", "ARM"],
            "numeric": dm_num,
        },
        "AE": {
            "structure": "One record per AE per subject",
            "class": "EVENTS",
            "variables": [(c, ae_labels.get(c, c)) for c in ae_cols],
            "required": ["STUDYID", "DOMAIN", "USUBJID", "AESEQ", "AETERM"],
            "numeric": ae_num,
        },
        "EX": {
            "structure": "One record per dosing interval per subject",
            "class": "INTERVENTIONS",
            "variables": [(c, ex_labels.get(c, c)) for c in ex_cols],
            "required": ["STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT"],
            "numeric": ex_num,
        },
        "VS": {
            "structure": "One record per measurement per visit per subject",
            "class": "FINDINGS",
            "variables": [(c, vs_labels.get(c, c)) for c in vs_cols],
            "required": ["STUDYID", "DOMAIN", "USUBJID", "VSSEQ", "VSTESTCD", "VSTEST"],
            "numeric": vs_num,
        },
        "DS": {
            "structure": "One record per disposition event per subject",
            "class": "EVENTS",
            "variables": [(c, ds_labels.get(c, c)) for c in ds_cols],
            "required": ["STUDYID", "DOMAIN", "USUBJID", "DSSEQ", "DSDECOD"],
            "numeric": ds_num,
        },
        "TS": {
            "structure": "One record per trial summary parameter",
            "class": "TRIAL DESIGN",
            "variables": [(c, ts_labels.get(c, c)) for c in ts_cols],
            "required": ["STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM", "TSVAL"],
            "numeric": ts_num,
        },
        "SUPPAE": {
            "structure": "One record per qualifier per AE per subject",
            "class": "RELATIONSHIP",
            "variables": [(c, suppae_labels.get(c, c)) for c in suppae_cols],
            "required": ["STUDYID", "RDOMAIN", "USUBJID", "IDVAR", "IDVARVAL", "QNAM", "QLABEL", "QVAL"],
            "numeric": [],
        },
    }
    generate_define_xml(domains_meta, protocol, os.path.join(OUTPUT_DIR, "define.xml"))

    print(f"SDTM domains written to {OUTPUT_DIR}")
    for f in sorted(os.listdir(OUTPUT_DIR)):
        print(f"  {f}")


if __name__ == "__main__":
    main()
