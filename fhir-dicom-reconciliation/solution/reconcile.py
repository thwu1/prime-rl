#!/usr/bin/env python3
"""
FHIR-DICOM cross-standard reconciliation engine.

Scans DICOM Part-10 files as ground truth, compares against a FHIR R4 Bundle,
detects inconsistencies, and produces both a report and corrected bundle.
"""
import copy
import json
import os
import sys

try:
    import pydicom
except ImportError:
    os.system("pip3 install pydicom==2.4.4 -q")
    import pydicom

DICOM_DIR = "/app/dicom_studies"
FHIR_BUNDLE_PATH = "/app/fhir_bundle.json"
OUTPUT_DIR = "/app/output"
REPORT_PATH = os.path.join(OUTPUT_DIR, "reconciliation_report.json")
CORRECTED_PATH = os.path.join(OUTPUT_DIR, "corrected_bundle.json")

CORRECT_MODALITY_SYSTEM = "http://dicom.nema.org/resources/ontology/DCM"

SCHEME_TO_SYSTEM = {
    "SCT": "http://snomed.info/sct",
    "LN": "http://loinc.org",
    "DCM": "http://dicom.nema.org/resources/ontology/DCM",
    "I10": "http://hl7.org/fhir/sid/icd-10",
}


def safe_str(ds, attr, default=""):
    """Safely extract a DICOM attribute as a plain Python str."""
    if not hasattr(ds, attr):
        return default
    val = getattr(ds, attr)
    if val is None:
        return default
    return str(val).strip()


def scan_dicom_files(dicom_dir):
    """Walk dicom_dir and build patient -> study -> series -> instance model."""
    patients = {}

    all_files = []
    for root, _dirs, files in os.walk(dicom_dir):
        for fname in files:
            if fname.lower().endswith(".dcm"):
                all_files.append(os.path.join(root, fname))

    print(f"Found {len(all_files)} DICOM files to scan", file=sys.stderr)

    for filepath in sorted(all_files):
        try:
            ds = pydicom.dcmread(filepath, force=True)
        except Exception as exc:
            print(f"WARNING: Cannot read {filepath}: {exc}", file=sys.stderr)
            continue

        pid = safe_str(ds, "PatientID")
        study_uid = safe_str(ds, "StudyInstanceUID")
        series_uid = safe_str(ds, "SeriesInstanceUID")
        sop_uid = safe_str(ds, "SOPInstanceUID")

        if not pid or not study_uid:
            print(f"WARNING: Missing PatientID or StudyInstanceUID in {filepath}", file=sys.stderr)
            continue

        # Patient record
        if pid not in patients:
            patients[pid] = {
                "name": safe_str(ds, "PatientName"),
                "id": pid,
                "dob": safe_str(ds, "PatientBirthDate"),
                "sex": safe_str(ds, "PatientSex"),
                "studies": {},
            }

        p = patients[pid]

        # Study record
        if study_uid not in p["studies"]:
            # Extract procedure codes from this first instance
            proc_codes = []
            if hasattr(ds, "ProcedureCodeSequence") and ds.ProcedureCodeSequence is not None:
                try:
                    for seq_item in ds.ProcedureCodeSequence:
                        pc = {
                            "code": safe_str(seq_item, "CodeValue"),
                            "scheme": safe_str(seq_item, "CodingSchemeDesignator"),
                            "meaning": safe_str(seq_item, "CodeMeaning"),
                        }
                        if pc["code"]:
                            proc_codes.append(pc)
                except Exception as exc:
                    print(f"WARNING: Error reading ProcedureCodeSequence: {exc}", file=sys.stderr)

            p["studies"][study_uid] = {
                "uid": study_uid,
                "date": safe_str(ds, "StudyDate"),
                "description": safe_str(ds, "StudyDescription"),
                "accession": safe_str(ds, "AccessionNumber"),
                "referrer": safe_str(ds, "ReferringPhysicianName"),
                "procedure_codes": proc_codes,
                "series": {},
                "total_instances": 0,
            }

        study = p["studies"][study_uid]

        # Try to fill in procedure codes from subsequent instances if first was empty
        if not study["procedure_codes"] and hasattr(ds, "ProcedureCodeSequence") and ds.ProcedureCodeSequence is not None:
            try:
                for seq_item in ds.ProcedureCodeSequence:
                    pc = {
                        "code": safe_str(seq_item, "CodeValue"),
                        "scheme": safe_str(seq_item, "CodingSchemeDesignator"),
                        "meaning": safe_str(seq_item, "CodeMeaning"),
                    }
                    if pc["code"]:
                        study["procedure_codes"].append(pc)
            except Exception:
                pass

        # Series record
        if series_uid not in study["series"]:
            study["series"][series_uid] = {
                "uid": series_uid,
                "modality": safe_str(ds, "Modality"),
                "number": int(getattr(ds, "SeriesNumber", 0) or 0),
                "instance_count": 0,
            }

        study["series"][series_uid]["instance_count"] += 1
        study["total_instances"] += 1

    return patients


def dcm_date_to_iso(d):
    """Convert DICOM date YYYYMMDD to ISO YYYY-MM-DD."""
    d = d.strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def dcm_sex_to_fhir(s):
    """Convert DICOM PatientSex (M/F/O) to FHIR gender."""
    return {"M": "male", "F": "female", "O": "other"}.get(s.strip(), "unknown")


def get_fhir_mrn(patient):
    """Extract MRN from FHIR Patient resource."""
    for ident in patient.get("identifier", []):
        coding = ident.get("type", {}).get("coding", [])
        for c in coding:
            if c.get("code") == "MR":
                return ident.get("value")
    # Fallback: first identifier
    idents = patient.get("identifier", [])
    if idents:
        return idents[0].get("value")
    return None


def set_fhir_mrn(patient, value):
    """Set MRN in FHIR Patient resource."""
    for ident in patient.get("identifier", []):
        coding = ident.get("type", {}).get("coding", [])
        for c in coding:
            if c.get("code") == "MR":
                ident["value"] = value
                return True
    idents = patient.get("identifier", [])
    if idents:
        idents[0]["value"] = value
        return True
    return False


def get_fhir_study_uid(study):
    """Extract Study Instance UID from FHIR ImagingStudy."""
    for ident in study.get("identifier", []):
        if ident.get("system") == "urn:dicom:uid":
            raw = ident.get("value", "")
            return raw.replace("urn:oid:", "")
    return None


def set_fhir_study_uid(study, uid):
    """Set Study Instance UID in FHIR ImagingStudy."""
    for ident in study.get("identifier", []):
        if ident.get("system") == "urn:dicom:uid":
            ident["value"] = f"urn:oid:{uid}"
            return True
    return False


def get_fhir_accession(study):
    """Extract accession number from FHIR ImagingStudy."""
    for ident in study.get("identifier", []):
        coding = ident.get("type", {}).get("coding", [])
        for c in coding:
            if c.get("code") == "ACSN":
                return ident.get("value")
    return None


def set_fhir_accession(study, value):
    """Set accession number in FHIR ImagingStudy."""
    for ident in study.get("identifier", []):
        coding = ident.get("type", {}).get("coding", [])
        for c in coding:
            if c.get("code") == "ACSN":
                ident["value"] = value
                return True
    return False


def main():
    print("=" * 60, file=sys.stderr)
    print("FHIR-DICOM Reconciliation Engine", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    # ---- Phase 1: Scan DICOM ground truth ----
    dicom_patients = scan_dicom_files(DICOM_DIR)

    print(f"\nDICOM Summary: {len(dicom_patients)} patients", file=sys.stderr)
    for pid, p in dicom_patients.items():
        print(f"  Patient: {p['name']} (ID={pid}, DOB={p['dob']}, Sex={p['sex']})", file=sys.stderr)
        for suid, s in p["studies"].items():
            num_series = len(s["series"])
            print(f"    Study UID={suid}", file=sys.stderr)
            print(f"      Date={s['date']}, Desc={s['description']}", file=sys.stderr)
            print(f"      Accession={s['accession']}, Referrer={s['referrer']}", file=sys.stderr)
            print(f"      Series={num_series}, Instances={s['total_instances']}", file=sys.stderr)
            print(f"      ProcCodes={s['procedure_codes']}", file=sys.stderr)

    # Build indexes for study matching
    uid_to_study = {}   # study_uid -> (patient_data, study_data)
    acc_to_study = {}   # accession -> (patient_data, study_data)
    for pid, p in dicom_patients.items():
        for suid, s in p["studies"].items():
            uid_to_study[suid] = (p, s)
            if s["accession"]:
                acc_to_study[s["accession"]] = (p, s)

    # ---- Phase 2: Load FHIR Bundle ----
    with open(FHIR_BUNDLE_PATH) as f:
        fhir_bundle = json.load(f)

    # Deep copy for corrections - work on the copy
    corrected_bundle = copy.deepcopy(fhir_bundle)

    inconsistencies = []

    def record(rtype, rid, field, fhir_val, dicom_val):
        inconsistencies.append({
            "resource_type": rtype,
            "resource_id": rid,
            "field": field,
            "fhir_value": fhir_val,
            "dicom_value": dicom_val,
        })
        print(f"  >> INCONSISTENCY [{len(inconsistencies)}] {rtype}/{rid}.{field}: "
              f"FHIR='{fhir_val}' -> DICOM='{dicom_val}'", file=sys.stderr)

    # Index original and corrected FHIR resources by type and id
    # Use index-based access to ensure we modify the correct corrected entry
    fhir_patients = {}      # id -> (resource, index_in_entries)
    fhir_studies = {}       # id -> (resource, index_in_entries)

    entries = fhir_bundle.get("entry", [])
    print(f"\nFHIR Bundle: {len(entries)} entries", file=sys.stderr)

    for idx, entry in enumerate(entries):
        res = entry.get("resource", entry)
        rtype = res.get("resourceType", "")
        rid = res.get("id", "")
        if rtype == "Patient":
            fhir_patients[rid] = (res, idx)
        elif rtype == "ImagingStudy":
            fhir_studies[rid] = (res, idx)

    print(f"  Patients: {list(fhir_patients.keys())}", file=sys.stderr)
    print(f"  Studies: {list(fhir_studies.keys())}", file=sys.stderr)

    # Build FHIR name -> patient_id map
    name_to_fhir_pid = {}
    for fhir_pid, (fp, _) in fhir_patients.items():
        names = fp.get("name", [{}])
        if names:
            n = names[0]
            family = n.get("family", "").upper()
            given_list = n.get("given", [""])
            given = given_list[0].upper() if given_list else ""
            key = f"{family}^{given}"
            name_to_fhir_pid[key] = fhir_pid

    def match_dicom_patient(family_upper, given_upper):
        """Find DICOM patient by name components."""
        for pid, p in dicom_patients.items():
            parts = p["name"].split("^")
            dfamily = parts[0].upper()
            dgiven = parts[1].upper() if len(parts) > 1 else ""
            if dfamily == family_upper and dgiven == given_upper:
                return p
        return None

    def get_corrected_resource(idx):
        """Get the resource from the corrected bundle at the given entry index."""
        entry = corrected_bundle["entry"][idx]
        if "resource" in entry:
            return entry["resource"]
        return entry

    # ---- Phase 3: Patient-level reconciliation ----
    print("\n--- Patient Reconciliation ---", file=sys.stderr)
    for fhir_pid, (fp, fp_idx) in fhir_patients.items():
        names = fp.get("name", [{}])
        n = names[0] if names else {}
        family = n.get("family", "").upper()
        given_list = n.get("given", [""])
        given = given_list[0].upper() if given_list else ""

        dp = match_dicom_patient(family, given)
        if dp is None:
            print(f"  WARNING: No DICOM match for Patient/{fhir_pid}", file=sys.stderr)
            continue

        print(f"\n  Patient/{fhir_pid} matched to DICOM {dp['name']} ({dp['id']})", file=sys.stderr)
        cp = get_corrected_resource(fp_idx)

        # MRN
        fhir_mrn = get_fhir_mrn(fp)
        if fhir_mrn != dp["id"]:
            record("Patient", fhir_pid, "identifier_mrn", fhir_mrn, dp["id"])
            set_fhir_mrn(cp, dp["id"])

        # Birth date
        fhir_dob = fp.get("birthDate", "")
        dcm_dob = dcm_date_to_iso(dp["dob"])
        if fhir_dob != dcm_dob:
            record("Patient", fhir_pid, "birthDate", fhir_dob, dcm_dob)
            cp["birthDate"] = dcm_dob

        # Gender
        fhir_gender = fp.get("gender", "")
        dcm_gender = dcm_sex_to_fhir(dp["sex"])
        if fhir_gender != dcm_gender:
            record("Patient", fhir_pid, "gender", fhir_gender, dcm_gender)
            cp["gender"] = dcm_gender

    # ---- Phase 4: ImagingStudy-level reconciliation ----
    print("\n--- ImagingStudy Reconciliation ---", file=sys.stderr)
    for fhir_sid, (fs, fs_idx) in fhir_studies.items():
        fhir_uid = get_fhir_study_uid(fs)
        fhir_acc = get_fhir_accession(fs)

        print(f"\n  ImagingStudy/{fhir_sid}: UID={fhir_uid}, ACC={fhir_acc}", file=sys.stderr)

        # Multi-strategy matching
        matched_p = None
        matched_s = None
        match_method = None

        # Strategy 1: Direct UID match
        if fhir_uid and fhir_uid in uid_to_study:
            matched_p, matched_s = uid_to_study[fhir_uid]
            match_method = "UID"

        # Strategy 2: Accession number fallback
        if matched_s is None and fhir_acc and fhir_acc in acc_to_study:
            matched_p, matched_s = acc_to_study[fhir_acc]
            match_method = "accession"

        # Strategy 3: Subject reference + description fallback
        if matched_s is None:
            subj_ref = fs.get("subject", {}).get("reference", "")
            subj_pid = subj_ref.replace("Patient/", "")
            fhir_pat_info = fhir_patients.get(subj_pid)
            if fhir_pat_info:
                fp_obj = fhir_pat_info[0]
                names = fp_obj.get("name", [{}])
                n = names[0] if names else {}
                fam = n.get("family", "").upper()
                giv_list = n.get("given", [""])
                giv = giv_list[0].upper() if giv_list else ""
                dp = match_dicom_patient(fam, giv)
                if dp:
                    # Try matching by description if patient has multiple studies
                    fhir_desc = fs.get("description", "")
                    for suid, sdata in dp["studies"].items():
                        if sdata["description"] == fhir_desc:
                            matched_p = dp
                            matched_s = sdata
                            match_method = "subject+description"
                            break
                    # If still no match and only one study, use it
                    if matched_s is None and len(dp["studies"]) == 1:
                        matched_p = dp
                        matched_s = list(dp["studies"].values())[0]
                        match_method = "subject+single_study"

        if matched_s is None:
            print(f"    WARNING: No DICOM match for ImagingStudy/{fhir_sid}", file=sys.stderr)
            continue

        print(f"    Matched via {match_method} to study {matched_s['uid']} "
              f"(patient {matched_p['name']})", file=sys.stderr)

        cs = get_corrected_resource(fs_idx)

        # ---- Cross-reference integrity ----
        subj_ref = fs.get("subject", {}).get("reference", "")
        current_pid = subj_ref.replace("Patient/", "")

        dcm_parts = matched_p["name"].split("^")
        dcm_fam = dcm_parts[0].upper()
        dcm_giv = dcm_parts[1].upper() if len(dcm_parts) > 1 else ""
        name_key = f"{dcm_fam}^{dcm_giv}"
        expected_pid = name_to_fhir_pid.get(name_key)

        if expected_pid and current_pid != expected_pid:
            record("ImagingStudy", fhir_sid, "subject.reference",
                   subj_ref, f"Patient/{expected_pid}")
            cs["subject"]["reference"] = f"Patient/{expected_pid}"

        # ---- Study Instance UID ----
        if fhir_uid and fhir_uid != matched_s["uid"]:
            record("ImagingStudy", fhir_sid, "identifier_study_uid",
                   fhir_uid, matched_s["uid"])
            set_fhir_study_uid(cs, matched_s["uid"])

        # ---- Started date ----
        fhir_started = fs.get("started", "")
        dcm_iso_date = dcm_date_to_iso(matched_s["date"])
        if dcm_iso_date not in fhir_started:
            record("ImagingStudy", fhir_sid, "started",
                   fhir_started, dcm_iso_date)
            if "T" in fhir_started:
                time_part = fhir_started.split("T", 1)[1]
                cs["started"] = f"{dcm_iso_date}T{time_part}"
            else:
                cs["started"] = dcm_iso_date

        # ---- Description ----
        fhir_desc = fs.get("description", "")
        dcm_desc = matched_s["description"]
        if fhir_desc != dcm_desc:
            record("ImagingStudy", fhir_sid, "description",
                   fhir_desc, dcm_desc)
            cs["description"] = dcm_desc

        # ---- Accession number ----
        if fhir_acc is not None and fhir_acc != matched_s["accession"]:
            record("ImagingStudy", fhir_sid, "accession_number",
                   fhir_acc, matched_s["accession"])
            set_fhir_accession(cs, matched_s["accession"])

        # ---- Referring physician ----
        fhir_ref_display = fs.get("referrer", {}).get("display", "")
        dcm_ref = matched_s["referrer"]
        if fhir_ref_display != dcm_ref:
            record("ImagingStudy", fhir_sid, "referrer",
                   fhir_ref_display, dcm_ref)
            cs["referrer"] = {"display": dcm_ref}

        # ---- numberOfSeries ----
        fhir_ns = fs.get("numberOfSeries", 0)
        dcm_ns = len(matched_s["series"])
        if fhir_ns != dcm_ns:
            record("ImagingStudy", fhir_sid, "numberOfSeries",
                   fhir_ns, dcm_ns)
            cs["numberOfSeries"] = dcm_ns

        # ---- numberOfInstances (study level) ----
        fhir_ni = fs.get("numberOfInstances", 0)
        dcm_ni = matched_s["total_instances"]
        if fhir_ni != dcm_ni:
            record("ImagingStudy", fhir_sid, "numberOfInstances",
                   fhir_ni, dcm_ni)
            cs["numberOfInstances"] = dcm_ni

        # ---- Series-level checks ----
        fhir_series_list = fs.get("series", [])
        dcm_series_list = list(matched_s["series"].values())

        for fhir_ser in fhir_series_list:
            snum = fhir_ser.get("number", 0)
            dcm_ser = None
            for ds_item in dcm_series_list:
                if ds_item["number"] == snum:
                    dcm_ser = ds_item
                    break
            if dcm_ser is None:
                continue

            # Modality code check
            fhir_mod_code = fhir_ser.get("modality", {}).get("code", "")
            dcm_mod_code = dcm_ser["modality"]
            if fhir_mod_code != dcm_mod_code:
                record("ImagingStudy", fhir_sid,
                       f"series[{snum}].modality.code",
                       fhir_mod_code, dcm_mod_code)
                for cs_ser in cs.get("series", []):
                    if cs_ser.get("number") == snum:
                        cs_ser["modality"]["code"] = dcm_mod_code

            # Modality system URI check
            fhir_mod_sys = fhir_ser.get("modality", {}).get("system", "")
            if fhir_mod_sys != CORRECT_MODALITY_SYSTEM:
                record("ImagingStudy", fhir_sid,
                       f"series[{snum}].modality.system",
                       fhir_mod_sys, CORRECT_MODALITY_SYSTEM)
                for cs_ser in cs.get("series", []):
                    if cs_ser.get("number") == snum:
                        cs_ser["modality"]["system"] = CORRECT_MODALITY_SYSTEM

            # Silently fix series-level instance count
            for cs_ser in cs.get("series", []):
                if cs_ser.get("number") == snum:
                    cs_ser["numberOfInstances"] = dcm_ser["instance_count"]

        # ---- Procedure Code reconciliation ----
        dcm_procs = matched_s.get("procedure_codes", [])
        fhir_procs = fs.get("procedureCode", [])

        if dcm_procs:
            # Build expected FHIR procedureCode from DICOM
            expected_codings = []
            for pc in dcm_procs:
                sys_uri = SCHEME_TO_SYSTEM.get(pc["scheme"], pc["scheme"])
                expected_codings.append({
                    "system": sys_uri,
                    "code": pc["code"],
                    "display": pc["meaning"],
                })

            if not fhir_procs:
                # Missing procedureCode entirely
                record("ImagingStudy", fhir_sid, "procedureCode",
                       None,
                       [{"code": c["code"], "system": c["system"]} for c in expected_codings])
                cs["procedureCode"] = [{"coding": expected_codings}]
            else:
                # Both exist: compare code values and systems
                fhir_code_pairs = set()
                for cc in fhir_procs:
                    for coding in cc.get("coding", []):
                        fhir_code_pairs.add(
                            (coding.get("code", ""), coding.get("system", ""))
                        )

                expected_pairs = set()
                for ec in expected_codings:
                    expected_pairs.add((ec["code"], ec["system"]))

                if fhir_code_pairs != expected_pairs:
                    record("ImagingStudy", fhir_sid, "procedureCode",
                           str(sorted(fhir_code_pairs)),
                           str(sorted(expected_pairs)))
                    cs["procedureCode"] = [{"coding": expected_codings}]

    # ---- Phase 5: Write outputs ----
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    report = {
        "summary": {
            "total_inconsistencies": len(inconsistencies),
            "patients_analyzed": len(dicom_patients),
            "studies_analyzed": sum(
                len(p["studies"]) for p in dicom_patients.values()
            ),
        },
        "inconsistencies": inconsistencies,
    }

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Verify corrected bundle structure before writing
    corr_entries = corrected_bundle.get("entry", [])
    print(f"\nCorrected bundle has {len(corr_entries)} entries", file=sys.stderr)

    with open(CORRECTED_PATH, "w") as f:
        json.dump(corrected_bundle, f, indent=2, default=str)

    print(f"\nReconciliation complete: {len(inconsistencies)} inconsistencies found.",
          file=sys.stderr)
    print(f"Report:    {REPORT_PATH}", file=sys.stderr)
    print(f"Corrected: {CORRECTED_PATH}", file=sys.stderr)

    # Also print to stdout for test runner visibility
    print(f"Reconciliation complete: {len(inconsistencies)} inconsistencies found.")
    print(f"Report:    {REPORT_PATH}")
    print(f"Corrected: {CORRECTED_PATH}")


if __name__ == "__main__":
    main()
