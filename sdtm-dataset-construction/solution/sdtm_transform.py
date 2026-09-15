
"""
SDTM Dataset Construction for ECD-2023-0847.
Transforms raw clinical trial CSV/JSON into SDTMIG v3.3 conformant domains.
Handles cross-year dates, leap year birthdays, dose modifications,
lab SI conversions, and multi-domain consistency.
"""

import os
import json
import pandas as pd
from datetime import datetime


# ==================== HELPERS ====================

def parse_date_iso(date_str):
    """Convert MM/DD/YYYY to YYYY-MM-DD (ISO 8601)."""
    if pd.isna(date_str) or str(date_str).strip() == "":
        return ""
    return datetime.strptime(str(date_str).strip(), "%m/%d/%Y").strftime("%Y-%m-%d")


def compute_age(birth_date_str, ref_date_str):
    """Compute completed age in years at reference date."""
    bd = datetime.strptime(birth_date_str.strip(), "%m/%d/%Y").date()
    rd = datetime.strptime(ref_date_str.strip(), "%m/%d/%Y").date()
    age = rd.year - bd.year
    if (rd.month, rd.day) < (bd.month, bd.day):
        age -= 1
    return age


def study_day(event_date_str, ref_date_str):
    """
    Compute Study Day with no day 0 convention.
    Dates on/after RFSTDTC: (diff_days) + 1
    Dates before RFSTDTC: diff_days (negative)
    """
    if pd.isna(event_date_str) or str(event_date_str).strip() == "":
        return ""
    ed = datetime.strptime(str(event_date_str).strip(), "%m/%d/%Y").date()
    rd = datetime.strptime(str(ref_date_str).strip(), "%m/%d/%Y").date()
    diff = (ed - rd).days
    if diff >= 0:
        return diff + 1
    else:
        return diff


def map_sex(sex_str):
    mapping = {"Male": "M", "Female": "F", "M": "M", "F": "F"}
    return mapping.get(str(sex_str).strip(), str(sex_str).strip())


def map_severity(grade):
    mapping = {"1": "MILD", "2": "MODERATE", "3": "SEVERE",
               1: "MILD", 2: "MODERATE", 3: "SEVERE"}
    return mapping.get(grade, str(grade))


def map_seriousness(flag):
    mapping = {"Yes": "Y", "No": "N", "Y": "Y", "N": "N"}
    return mapping.get(str(flag).strip(), str(flag).strip())


def map_outcome(outcome):
    mapping = {
        "Recovered": "RECOVERED/RESOLVED",
        "Not Yet Resolved": "NOT RECOVERED/NOT RESOLVED",
        "Not Recovered": "NOT RECOVERED/NOT RESOLVED",
        "Recovering": "RECOVERING/RESOLVING",
        "Fatal": "FATAL",
    }
    return mapping.get(str(outcome).strip(), str(outcome).strip())


VS_TESTCD_MAP = {
    "Systolic Blood Pressure": "SYSBP",
    "Diastolic Blood Pressure": "DIABP",
    "Heart Rate": "HR",
    "Weight": "WEIGHT",
    "Height": "HEIGHT",
}

LB_TESTCD_MAP = {
    "Glucose": "GLUC",
    "Creatinine": "CREAT",
    "ALT": "ALT",
    "Hemoglobin": "HGB",
}


# ==================== MAIN ====================

def main():
    # Read raw data
    patients = pd.read_csv("/app/raw_data/patients.csv")
    ae_raw = pd.read_csv("/app/raw_data/adverse_events.csv")
    vs_raw = pd.read_csv("/app/raw_data/vital_signs.csv")
    lb_raw = pd.read_csv("/app/raw_data/lab_results.csv")
    ex_raw = pd.read_csv("/app/raw_data/drug_exposure.csv")
    ds_raw = pd.read_csv("/app/raw_data/disposition.csv")

    with open("/app/raw_data/protocol_info.json") as f:
        protocol = json.load(f)

    STUDYID = protocol["study_id"]
    si_rules = protocol["si_conversion_rules"]

    # Build arm mapping
    arm_mapping = {a["code"]: a["name"] for a in protocol["arms"]}

    # Build RFSTDTC lookup (enrollment date per subject)
    rfstdtc_lookup = {}
    for _, row in patients.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        rfstdtc_lookup[usubjid] = row["enroll_date"]

    # ===== DM =====
    dm_rows = []
    for _, row in patients.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        dm_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "DM",
            "USUBJID": usubjid,
            "SUBJID": subjid,
            "RFSTDTC": parse_date_iso(row["enroll_date"]),
            "BRTHDTC": parse_date_iso(row["birth_date"]),
            "AGE": compute_age(row["birth_date"], row["enroll_date"]),
            "AGEU": "YEARS",
            "SEX": map_sex(row["sex"]),
            "RACE": row["race"],
            "ETHNIC": row["ethnicity"],
            "ARMCD": row["arm_code"],
            "ARM": arm_mapping.get(row["arm_code"], ""),
            "COUNTRY": row["country"],
            "SITEID": siteid,
            "DMDTC": parse_date_iso(row["enroll_date"]),
            "DMDY": 1,
        })
    dm = pd.DataFrame(dm_rows)

    # ===== AE =====
    ae_rows = []
    suppae_rows = []
    for _, row in ae_raw.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        rfstdtc = rfstdtc_lookup[usubjid]

        ae_endtc = parse_date_iso(row["end_date"]) if pd.notna(row["end_date"]) else ""
        ae_endy = study_day(row["end_date"], rfstdtc) if pd.notna(row["end_date"]) and str(row["end_date"]).strip() != "" else ""

        ae_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "AE",
            "USUBJID": usubjid,
            "AESEQ": int(row["seq"]),
            "AETERM": row["ae_verbatim"],
            "AEDECOD": str(row["ae_verbatim"]).upper(),
            "AESTDTC": parse_date_iso(row["start_date"]),
            "AEENDTC": ae_endtc,
            "AESEV": map_severity(row["severity_grade"]),
            "AESER": map_seriousness(row["serious_flag"]),
            "AEREL": row["causality"],
            "AEOUT": map_outcome(row["outcome"]),
            "AESTDY": study_day(row["start_date"], rfstdtc),
            "AEENDY": ae_endy,
        })

        # SUPPAE for body_location
        body_loc = row.get("body_location", "")
        if pd.notna(body_loc) and str(body_loc).strip() != "":
            suppae_rows.append({
                "STUDYID": STUDYID,
                "RDOMAIN": "AE",
                "USUBJID": usubjid,
                "IDVAR": "AESEQ",
                "IDVARVAL": str(int(row["seq"])),
                "QNAM": "AELOC",
                "QLABEL": "Location of Adverse Event",
                "QVAL": str(body_loc).strip(),
                "QORIG": "CRF",
            })

    ae = pd.DataFrame(ae_rows)
    suppae = pd.DataFrame(suppae_rows)

    # ===== VS =====
    vs_rows = []
    vs_seq_counter = {}
    for _, row in vs_raw.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        rfstdtc = rfstdtc_lookup[usubjid]

        if usubjid not in vs_seq_counter:
            vs_seq_counter[usubjid] = 0
        vs_seq_counter[usubjid] += 1

        # Baseline flag
        vsblfl = "Y" if str(row["visit_label"]).strip() == "Baseline" else ""

        # Date/time
        vsdtc = parse_date_iso(row["collection_date"])
        ctime = str(row.get("collection_time", "")).strip()
        if ctime and ctime != "nan":
            vsdtc = f"{vsdtc}T{ctime}"

        testcd = VS_TESTCD_MAP.get(str(row["test_name"]).strip(),
                                    str(row["test_name"])[:8].upper())

        vs_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "VS",
            "USUBJID": usubjid,
            "VSSEQ": vs_seq_counter[usubjid],
            "VSTESTCD": testcd,
            "VSTEST": row["test_name"],
            "VSORRES": str(row["result_value"]),
            "VSORRESU": row["unit"],
            "VSSTRESC": str(row["result_value"]),
            "VSSTRESN": float(row["result_value"]),
            "VSSTRESU": row["unit"],
            "VSBLFL": vsblfl,
            "VISITNUM": int(row["visit_num"]),
            "VISIT": row["visit_label"],
            "VSDTC": vsdtc,
            "VSDY": study_day(row["collection_date"], rfstdtc),
        })

    vs = pd.DataFrame(vs_rows)

    # ===== LB =====
    lb_rows = []
    lb_seq_counter = {}
    for _, row in lb_raw.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        rfstdtc = rfstdtc_lookup[usubjid]

        if usubjid not in lb_seq_counter:
            lb_seq_counter[usubjid] = 0
        lb_seq_counter[usubjid] += 1

        test_name = str(row["test_name"]).strip()
        testcd = LB_TESTCD_MAP.get(test_name, test_name[:8].upper())

        # Original result
        result_val = float(row["result_value"])
        result_unit = str(row["result_unit"]).strip()

        # Format original result preserving integer appearance
        if result_val == int(result_val):
            lborres = str(int(result_val))
        else:
            lborres = str(result_val)

        # SI conversion
        if test_name in si_rules:
            rule = si_rules[test_name]
            factor = rule["factor"]
            si_unit = rule["si_unit"]
            si_val = round(result_val * factor, 2)
        else:
            si_unit = result_unit
            si_val = round(result_val, 2)

        # Reference range indicator
        normal_low = float(row["normal_low"])
        normal_high = float(row["normal_high"])
        if result_val > normal_high:
            lbnrind = "HIGH"
        elif result_val < normal_low:
            lbnrind = "LOW"
        else:
            lbnrind = "NORMAL"

        # Date/time
        lbdtc = parse_date_iso(row["collection_date"])
        ctime = str(row.get("collection_time", "")).strip()
        if ctime and ctime != "nan":
            lbdtc = f"{lbdtc}T{ctime}"

        lb_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "LB",
            "USUBJID": usubjid,
            "LBSEQ": lb_seq_counter[usubjid],
            "LBTESTCD": testcd,
            "LBTEST": test_name,
            "LBORRES": lborres,
            "LBORRESU": result_unit,
            "LBSTRESC": str(si_val),
            "LBSTRESN": si_val,
            "LBSTRESU": si_unit,
            "LBNRIND": lbnrind,
            "LBSPEC": str(row["specimen_type"]).strip(),
            "LBBLFL": "Y",
            "VISITNUM": int(row["visit_num"]),
            "VISIT": row["visit_label"],
            "LBDTC": lbdtc,
            "LBDY": study_day(row["collection_date"], rfstdtc),
        })

    lb = pd.DataFrame(lb_rows)

    # ===== EX =====
    ex_rows = []
    ex_seq_counter = {}
    for _, row in ex_raw.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        rfstdtc = rfstdtc_lookup[usubjid]

        if usubjid not in ex_seq_counter:
            ex_seq_counter[usubjid] = 0
        ex_seq_counter[usubjid] += 1

        ex_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "EX",
            "USUBJID": usubjid,
            "EXSEQ": ex_seq_counter[usubjid],
            "EXTRT": row["treatment"],
            "EXDOSE": int(row["dose"]),
            "EXDOSU": row["dose_unit"],
            "EXDOSFRQ": row["frequency"],
            "EXSTDTC": parse_date_iso(row["start_date"]),
            "EXENDTC": parse_date_iso(row["end_date"]),
            "EXSTDY": study_day(row["start_date"], rfstdtc),
            "EXENDY": study_day(row["end_date"], rfstdtc),
        })

    ex = pd.DataFrame(ex_rows)

    # ===== DS =====
    ds_rows = []
    for _, row in ds_raw.iterrows():
        subjid = str(int(row["patient_num"])).zfill(3)
        siteid = str(row["site_id"])
        usubjid = f"{STUDYID}-{siteid}-{subjid}"
        rfstdtc = rfstdtc_lookup[usubjid]

        ds_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "DS",
            "USUBJID": usubjid,
            "DSSEQ": 1,
            "DSTERM": row["disposition_event"],
            "DSDECOD": str(row["disposition_event"]).upper(),
            "DSCAT": "DISPOSITION EVENT",
            "DSSTDTC": parse_date_iso(row["disposition_date"]),
            "DSDY": study_day(row["disposition_date"], rfstdtc),
        })

    ds = pd.DataFrame(ds_rows)

    # ===== TS =====
    ts_params = [
        ("SSTDTC", "Study Start Date", parse_date_iso(protocol["study_start_date"])),
        ("SENDTC", "Study End Date", parse_date_iso(protocol["study_end_date"])),
        ("TITLE", "Study Title", protocol["study_title"]),
        ("SPONSOR", "Study Sponsor", protocol["sponsor"]),
        ("INDIC", "Trial Disease/Condition Indication", protocol["indication"]),
        ("PHASE", "Trial Phase", protocol["study_phase"]),
        ("TRT", "Investigational Therapy or Treatment", protocol["arms"][0]["name"]),
        ("RANDOM", "Trial is Randomized", "N"),
        ("TBLIND", "Trial Blinding Schema", "OPEN"),
        ("TAREA", "Therapeutic Area", protocol["therapeutic_area"]),
    ]
    ts_rows = []
    for seq, (parmcd, parm, val) in enumerate(ts_params, start=1):
        ts_rows.append({
            "STUDYID": STUDYID,
            "DOMAIN": "TS",
            "TSSEQ": seq,
            "TSPARMCD": parmcd,
            "TSPARM": parm,
            "TSVAL": str(val),
        })
    ts = pd.DataFrame(ts_rows)

    # ===== WRITE OUTPUT =====
    os.makedirs("/app/sdtm_output", exist_ok=True)

    dm.to_csv("/app/sdtm_output/dm.csv", index=False)
    ae.to_csv("/app/sdtm_output/ae.csv", index=False)
    vs.to_csv("/app/sdtm_output/vs.csv", index=False)
    lb.to_csv("/app/sdtm_output/lb.csv", index=False)
    ex.to_csv("/app/sdtm_output/ex.csv", index=False)
    ds.to_csv("/app/sdtm_output/ds.csv", index=False)
    ts.to_csv("/app/sdtm_output/ts.csv", index=False)
    suppae.to_csv("/app/sdtm_output/suppae.csv", index=False)

    print("SDTM transformation complete. Output written to /app/sdtm_output/")


if __name__ == "__main__":
    main()
