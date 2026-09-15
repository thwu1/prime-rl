#!/usr/bin/env python3
"""
SDTM Domain Constructor — transforms raw clinical trial CSV data into
CDISC SDTM-conformant XPT (SAS Transport v5) files.

"""

import os
import re
from datetime import datetime

import pandas as pd
import pyreadstat

STUDYID = "XYZ001"
RAW_DIR = "/app/raw_data"
OUTPUT_DIR = "/app/sdtm_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ============================================================
# Utility functions
# ============================================================

def parse_date(date_str):
    """Parse various date formats to ISO 8601 YYYY-MM-DD."""
    if pd.isna(date_str) or str(date_str).strip() == "":
        return ""
    s = str(date_str).strip()

    formats = [
        "%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%Y/%m/%d",
        "%d%b%Y", "%b %d %Y", "%b-%d-%Y", "%B %d %Y",
        "%B %d, %Y",
    ]
    for fmt in formats:
        for candidate in (s, s.title()):
            try:
                return datetime.strptime(candidate, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue

    # Fallback: let pandas try
    try:
        return pd.to_datetime(s, dayfirst=False).strftime("%Y-%m-%d")
    except Exception:
        return ""


def compute_study_day(event_date, ref_date):
    """Compute study day with no-day-zero convention."""
    if not event_date or not ref_date:
        return None
    try:
        ev = datetime.strptime(event_date[:10], "%Y-%m-%d").date()
        rf = datetime.strptime(ref_date[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    delta = (ev - rf).days
    return delta + 1 if delta >= 0 else delta


def compute_age(brthdtc, rfstdtc):
    """Compute age in completed years."""
    if not brthdtc or not rfstdtc:
        return None
    try:
        birth = datetime.strptime(brthdtc[:10], "%Y-%m-%d").date()
        ref = datetime.strptime(rfstdtc[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    age = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        age -= 1
    return age


def map_sex(raw):
    g = str(raw).strip().upper()
    return {"MALE": "M", "FEMALE": "F", "M": "M", "F": "F"}.get(g, g)


def map_race(raw):
    r = str(raw).strip().upper()
    mapping = {
        "WHITE": "WHITE",
        "BLACK": "BLACK OR AFRICAN AMERICAN",
        "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
        "AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
        "ASIAN": "ASIAN",
        "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER":
            "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER",
        "NATIVE HAWAIIAN": "NATIVE HAWAIIAN OR OTHER PACIFIC ISLANDER",
        "AMERICAN INDIAN OR ALASKA NATIVE":
            "AMERICAN INDIAN OR ALASKA NATIVE",
        "MULTIPLE": "MULTIPLE",
        "OTHER": "OTHER",
    }
    return mapping.get(r, r)


def map_ethnicity(raw):
    e = str(raw).strip().upper()
    if "NOT" in e or "NON" in e:
        return "NOT HISPANIC OR LATINO"
    if "HISPANIC" in e:
        return "HISPANIC OR LATINO"
    return e


def map_country(raw):
    c = str(raw).strip().upper()
    return {"US": "USA", "USA": "USA", "UNITED STATES": "USA"}.get(c, c)


# ============================================================
# DM domain
# ============================================================

def build_dm(subjects):
    rows = []
    for _, s in subjects.iterrows():
        sid = str(s["subject_id"]).strip().zfill(3)
        site = str(s["site_id"]).strip()
        usubjid = f"{STUDYID}-{site}-{sid}"

        is_sf = str(s.get("randomized_arm", "")).strip().upper() == "SCREEN_FAIL"

        rfstdtc = "" if is_sf else parse_date(s.get("first_dose_date", ""))
        rfendtc = "" if is_sf else parse_date(s.get("last_dose_date", ""))
        rficdtc = parse_date(s.get("consent_date", ""))
        rfpendtc = "" if is_sf else parse_date(s.get("end_participation_date", ""))
        brthdtc = parse_date(s.get("birth_date", ""))

        age = compute_age(brthdtc, rfstdtc)

        arm_raw = str(s.get("randomized_arm", "")).strip().upper()
        if arm_raw == "DRUG_A":
            armcd, arm = "A", "Drug A 100mg"
        elif arm_raw == "PLACEBO":
            armcd, arm = "P", "Placebo"
        else:
            armcd, arm = "", ""

        rows.append({
            "STUDYID": STUDYID, "DOMAIN": "DM",
            "USUBJID": usubjid, "SUBJID": sid,
            "RFSTDTC": rfstdtc, "RFENDTC": rfendtc,
            "RFXSTDTC": rfstdtc, "RFXENDTC": rfendtc,
            "RFICDTC": rficdtc, "RFPENDTC": rfpendtc,
            "SITEID": site,
            "INVNAM": str(s.get("investigator", "")).strip(),
            "BRTHDTC": brthdtc,
            "AGE": age,
            "AGEU": "YEARS" if age is not None else "",
            "SEX": map_sex(s.get("gender", "")),
            "RACE": map_race(s.get("race_text", "")),
            "ETHNIC": map_ethnicity(s.get("ethnicity_text", "")),
            "ARMCD": armcd, "ARM": arm,
            "ACTARMCD": armcd, "ACTARM": arm,
            "ARMNRS": "SCREEN FAILURE" if is_sf else "",
            "COUNTRY": map_country(s.get("country", "")),
        })
    return pd.DataFrame(rows)


# ============================================================
# AE domain + SUPPAE
# ============================================================

SEVERITY_MAP = {
    "1": "MILD", "2": "MODERATE", "3": "SEVERE",
    "mild": "MILD", "moderate": "MODERATE", "severe": "SEVERE",
}

OUTCOME_MAP = {
    "recovered": "RECOVERED/RESOLVED",
    "resolved": "RECOVERED/RESOLVED",
    "recovering": "RECOVERING/RESOLVING",
    "resolving": "RECOVERING/RESOLVING",
    "not recovered": "NOT RECOVERED/NOT RESOLVED",
    "not resolved": "NOT RECOVERED/NOT RESOLVED",
    "recovered with sequelae": "RECOVERED/RESOLVED WITH SEQUELAE",
    "fatal": "FATAL",
    "unknown": "UNKNOWN",
}

ACTION_MAP = {
    "none": "DOSE NOT CHANGED",
    "dose not changed": "DOSE NOT CHANGED",
    "dose reduced": "DOSE REDUCED",
    "drug withdrawn": "DRUG WITHDRAWN",
    "drug interrupted": "DRUG INTERRUPTED",
    "not applicable": "NOT APPLICABLE",
    "dose increased": "DOSE INCREASED",
}


def build_ae(ae_raw, dm):
    # Build lookups from DM
    rfstdtc_lu = {}
    subjid_to_usubj = {}
    for _, r in dm.iterrows():
        rfstdtc_lu[r["USUBJID"]] = r["RFSTDTC"]
        subjid_to_usubj[r["SUBJID"]] = r["USUBJID"]

    ae_rows, supp_rows = [], []
    for _, a in ae_raw.iterrows():
        sid = str(a["subject_id"]).strip().zfill(3)
        usubjid = subjid_to_usubj.get(sid, f"{STUDYID}-UNK-{sid}")
        rfstdtc = rfstdtc_lu.get(usubjid, "")

        aestdtc = parse_date(a.get("start_date", ""))
        aeendtc = parse_date(a.get("end_date", ""))
        aestdy = compute_study_day(aestdtc, rfstdtc) if aestdtc and rfstdtc else None
        aeendy = compute_study_day(aeendtc, rfstdtc) if aeendtc and rfstdtc else None

        sev_raw = str(a.get("severity", "")).strip().lower()
        aesev = SEVERITY_MAP.get(sev_raw, sev_raw.upper())

        ser_raw = str(a.get("serious", "")).strip().upper()
        aeser = "Y" if ser_raw in ("Y", "YES") else "N"

        aerel = str(a.get("causality", "")).strip().upper()

        out_raw = str(a.get("outcome", "")).strip().lower()
        aeout = OUTCOME_MAP.get(out_raw, out_raw.upper())

        acn_val = a.get("action_taken", "")
        if pd.isna(acn_val) or str(acn_val).strip().lower() == "none":
            acn_raw = "none"
        else:
            acn_raw = str(acn_val).strip().lower()
        aeacn = ACTION_MAP.get(acn_raw, acn_raw.upper())

        aeterm = str(a.get("ae_term", "")).strip()
        aeseq = int(a.get("ae_number", 0))

        ae_rows.append({
            "STUDYID": STUDYID, "DOMAIN": "AE",
            "USUBJID": usubjid, "AESEQ": aeseq,
            "AETERM": aeterm, "AEDECOD": aeterm.upper(),
            "AESEV": aesev, "AESER": aeser,
            "AEREL": aerel, "AEOUT": aeout, "AEACN": aeacn,
            "AESTDTC": aestdtc, "AEENDTC": aeendtc,
            "AESTDY": aestdy, "AEENDY": aeendy,
        })

        # SUPPAE for follow_up_needed
        fup = str(a.get("follow_up_needed", "")).strip().upper()
        if fup:
            supp_rows.append({
                "STUDYID": STUDYID, "RDOMAIN": "AE",
                "USUBJID": usubjid, "IDVAR": "AESEQ",
                "IDVARVAL": str(aeseq),
                "QNAM": "AEFUPN",
                "QLABEL": "Follow-up Needed",
                "QVAL": fup,
                "QORIG": "CRF",
            })

    return pd.DataFrame(ae_rows), pd.DataFrame(supp_rows)


# ============================================================
# VS domain
# ============================================================

TESTCD_MAP = {
    "height": ("HEIGHT", "Height"),
    "weight": ("WEIGHT", "Weight"),
    "systolic blood pressure": ("SYSBP", "Systolic Blood Pressure"),
    "diastolic blood pressure": ("DIABP", "Diastolic Blood Pressure"),
    "heart rate": ("HR", "Heart Rate"),
    "temperature": ("TEMP", "Temperature"),
}


def build_vs(vitals, dm):
    rfstdtc_lu, rfxstdtc_lu, sid_lu = {}, {}, {}
    for _, r in dm.iterrows():
        rfstdtc_lu[r["USUBJID"]] = r["RFSTDTC"]
        rfxstdtc_lu[r["USUBJID"]] = r["RFXSTDTC"]
        sid_lu[r["SUBJID"]] = r["USUBJID"]

    rows = []
    seq = 0
    for _, v in vitals.iterrows():
        sid = str(v["subject_id"]).strip().zfill(3)
        usubjid = sid_lu.get(sid, f"{STUDYID}-UNK-{sid}")
        rfstdtc = rfstdtc_lu.get(usubjid, "")

        test_key = str(v.get("test_name", "")).strip().lower()
        vstestcd, vstest = TESTCD_MAP.get(test_key, (test_key.upper()[:8], test_key))

        result = float(v.get("result", 0))
        unit = str(v.get("unit", "")).strip()
        vsorres = str(v.get("result", "")).strip()

        # Unit conversions
        if vstestcd == "HEIGHT" and unit.lower() in ("inches", "in"):
            vsstresn = round(result * 2.54, 2)
            vsorresu, vsstresu = "in", "cm"
        elif vstestcd == "WEIGHT" and unit.lower() in ("lbs", "lb"):
            vsstresn = round(result * 0.453592, 2)
            vsorresu, vsstresu = "LB", "kg"
        elif vstestcd == "TEMP" and unit.upper() in ("F",):
            vsstresn = round((result - 32) * 5 / 9, 2)
            vsorresu, vsstresu = "F", "C"
        elif vstestcd in ("SYSBP", "DIABP"):
            vsstresn = result
            vsorresu, vsstresu = "mmHg", "mmHg"
        elif vstestcd == "HR":
            vsstresn = result
            vsorresu, vsstresu = "beats/min", "beats/min"
        else:
            vsstresn = result
            vsorresu, vsstresu = unit, unit

        vsstresc = str(vsstresn)

        coll_date = parse_date(v.get("collection_date", ""))
        coll_time = str(v.get("collection_time", "")).strip()
        vsdtc = f"{coll_date}T{coll_time}" if coll_date and coll_time else coll_date

        vsdy = compute_study_day(vsdtc[:10], rfstdtc) if vsdtc and rfstdtc else None

        visit_name = str(v.get("visit_name", "")).strip().upper()
        visit_num = int(v.get("visit_number", 0))

        seq += 1
        rows.append({
            "STUDYID": STUDYID, "DOMAIN": "VS",
            "USUBJID": usubjid, "VSSEQ": seq,
            "VSTESTCD": vstestcd, "VSTEST": vstest,
            "VSORRES": vsorres, "VSORRESU": vsorresu,
            "VSSTRESC": vsstresc, "VSSTRESN": vsstresn,
            "VSSTRESU": vsstresu,
            "VSDTC": vsdtc, "VSDY": vsdy,
            "VISITNUM": visit_num, "VISIT": visit_name,
            "VSLOBXFL": "",
        })

    vs = pd.DataFrame(rows)

    # Derive VSLOBXFL: last observation per test per subject strictly before RFXSTDTC
    for usubjid in vs["USUBJID"].unique():
        rfxstdtc = rfxstdtc_lu.get(usubjid, "")
        if not rfxstdtc:
            continue
        ref_date = rfxstdtc[:10]
        subj_mask = vs["USUBJID"] == usubjid

        for testcd in vs.loc[subj_mask, "VSTESTCD"].unique():
            test_mask = subj_mask & (vs["VSTESTCD"] == testcd)
            test_data = vs[test_mask]

            # Filter pre-exposure (strictly before)
            pre = test_data[test_data["VSDTC"].str[:10] < ref_date]
            if len(pre) > 0:
                last_idx = pre.sort_values("VSDTC").iloc[-1].name
                vs.loc[last_idx, "VSLOBXFL"] = "Y"

    return vs


# ============================================================
# TS domain
# ============================================================

def build_ts(trial_summary):
    rows = []
    seq = 0
    for _, t in trial_summary.iterrows():
        parmcd = str(t.get("parameter_code", "")).strip()
        parm = str(t.get("parameter_name", "")).strip()
        val = str(t.get("parameter_value", "")).strip()

        # Convert date-type parameters to ISO 8601
        if parmcd in ("SSTDTC", "SENDTC", "DCUTDTC"):
            val = parse_date(val)

        seq += 1
        rows.append({
            "STUDYID": STUDYID, "DOMAIN": "TS",
            "TSSEQ": seq,
            "TSPARMCD": parmcd, "TSPARM": parm, "TSVAL": val,
        })
    return pd.DataFrame(rows)


# ============================================================
# XPT writing helpers
# ============================================================

def prepare_df(df, numeric_cols):
    """Ensure correct dtypes for XPT output."""
    out = df.copy()
    for col in out.columns:
        if col in numeric_cols:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        else:
            out[col] = out[col].fillna("").astype(str)
    return out


def write_xpt(df, filename, table_name, numeric_cols):
    """Write DataFrame to XPT file."""
    df_clean = prepare_df(df, numeric_cols)
    path = os.path.join(OUTPUT_DIR, filename)
    pyreadstat.write_xport(df_clean, path, table_name=table_name)
    print(f"  -> {path}  ({len(df_clean)} records, {len(df_clean.columns)} vars)")


# ============================================================
# Main
# ============================================================

def main():
    print("Reading raw data...")
    subjects = pd.read_csv(os.path.join(RAW_DIR, "subjects.csv"))
    ae_raw = pd.read_csv(os.path.join(RAW_DIR, "adverse_events.csv"))
    vitals = pd.read_csv(os.path.join(RAW_DIR, "vitals.csv"))
    trial_summary = pd.read_csv(os.path.join(RAW_DIR, "trial_summary.csv"))

    print("Building DM domain...")
    dm = build_dm(subjects)
    write_xpt(dm, "dm.xpt", "DM", ["AGE"])

    print("Building AE domain...")
    ae, suppae = build_ae(ae_raw, dm)
    write_xpt(ae, "ae.xpt", "AE", ["AESEQ", "AESTDY", "AEENDY"])

    print("Building VS domain...")
    vs = build_vs(vitals, dm)
    write_xpt(vs, "vs.xpt", "VS", ["VSSEQ", "VSSTRESN", "VSDY", "VISITNUM"])

    print("Building TS domain...")
    ts = build_ts(trial_summary)
    write_xpt(ts, "ts.xpt", "TS", ["TSSEQ"])

    print("Writing SUPPAE...")
    write_xpt(suppae, "suppae.xpt", "SUPPAE", [])

    print("SDTM domain construction complete.")


if __name__ == "__main__":
    main()
