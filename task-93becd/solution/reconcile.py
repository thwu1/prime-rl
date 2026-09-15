#!/usr/bin/env python3

"""
DICOM-FHIR Conformance Audit Pipeline

Parses DICOM Part 10 files and FHIR R4 JSON resources, cross-references
them via standard identifiers, detects all conformance violations including
PN component mapping, coded sequence validation, referrer identity matching,
and reference integrity -- then produces corrected FHIR resources and a
Transaction Bundle.
"""

import copy
import glob
import json
import os
import warnings

warnings.filterwarnings("ignore")
import pydicom

# -- Paths ---------------------------------------------------------------------

DICOM_DIR = "/app/dicom_files"
FHIR_DIR = "/app/fhir_resources"
OUTPUT_DIR = "/app/output"
CORRECTED_DIR = os.path.join(OUTPUT_DIR, "corrected")

os.makedirs(CORRECTED_DIR, exist_ok=True)


# -- Constants -----------------------------------------------------------------

DCM_CODING_SYS = "http://dicom.nema.org/resources/ontology/DCM"

# DICOM CodingSchemeDesignator -> FHIR code system URI
DICOM_SCHEME_TO_FHIR = {
    "SCT": "http://snomed.info/sct",
    "SRT": "http://snomed.info/sct",
    "LN": "http://loinc.org",
    "DCM": DCM_CODING_SYS,
}


# -- Helpers -------------------------------------------------------------------

def dicom_date_to_fhir(d):
    """Convert DICOM date YYYYMMDD to FHIR date YYYY-MM-DD."""
    d = str(d).strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


def dicom_sex_to_fhir(s):
    """Convert DICOM PatientSex (M/F/O) to FHIR gender."""
    return {"M": "male", "F": "female", "O": "other"}.get(str(s).strip(), "unknown")


def safe_str(ds, attr, default=""):
    """Safely get a string attribute from a pydicom Dataset."""
    val = getattr(ds, attr, None)
    if val is None:
        return default
    return str(val).strip()


# -- Step 1: Parse all DICOM files ---------------------------------------------

dicom_patients = {}   # patient_id -> {...}
dicom_studies = {}    # study_uid -> {...}

for dcm_path in sorted(glob.glob(os.path.join(DICOM_DIR, "*.dcm"))):
    try:
        ds = pydicom.dcmread(dcm_path, force=True)
    except Exception as e:
        print(f"Warning: could not read {dcm_path}: {e}")
        continue

    pid = safe_str(ds, "PatientID")
    study_uid = safe_str(ds, "StudyInstanceUID")
    series_uid = safe_str(ds, "SeriesInstanceUID")
    sop_uid = safe_str(ds, "SOPInstanceUID")

    if not pid or not study_uid or not series_uid:
        print(f"Warning: skipping {dcm_path} - missing required identifiers")
        continue

    # Patient record (extract all PN components)
    if pid not in dicom_patients:
        pn = getattr(ds, "PatientName", None)
        if pn is not None:
            dicom_patients[pid] = {
                "family_name": str(pn.family_name) if pn.family_name else "",
                "given_name": str(pn.given_name) if pn.given_name else "",
                "middle_name": str(pn.middle_name) if pn.middle_name else "",
                "name_prefix": str(pn.name_prefix) if pn.name_prefix else "",
                "name_suffix": str(pn.name_suffix) if pn.name_suffix else "",
                "birth_date": safe_str(ds, "PatientBirthDate"),
                "sex": safe_str(ds, "PatientSex"),
            }
        else:
            dicom_patients[pid] = {
                "family_name": "", "given_name": "", "middle_name": "",
                "name_prefix": "", "name_suffix": "",
                "birth_date": safe_str(ds, "PatientBirthDate"),
                "sex": safe_str(ds, "PatientSex"),
            }

    # Study record
    if study_uid not in dicom_studies:
        dicom_studies[study_uid] = {
            "patient_id": pid,
            "date": safe_str(ds, "StudyDate"),
            "description": safe_str(ds, "StudyDescription"),
            "accession": safe_str(ds, "AccessionNumber"),
            "series": {},
        }

        # ProcedureCodeSequence (study-level)
        pcs = getattr(ds, "ProcedureCodeSequence", None)
        if pcs and len(pcs) > 0:
            proc = pcs[0]
            dicom_studies[study_uid]["procedure_code"] = {
                "code": safe_str(proc, "CodeValue"),
                "scheme": safe_str(proc, "CodingSchemeDesignator"),
                "meaning": safe_str(proc, "CodeMeaning"),
            }

        # ReferringPhysicianName (study-level)
        rpn = getattr(ds, "ReferringPhysicianName", None)
        if rpn:
            dicom_studies[study_uid]["referring_physician"] = {
                "family": str(rpn.family_name) if rpn.family_name else "",
                "given": str(rpn.given_name) if rpn.given_name else "",
            }

    # Series / instance record
    study = dicom_studies[study_uid]
    if series_uid not in study["series"]:
        series_info = {
            "modality": safe_str(ds, "Modality"),
            "description": safe_str(ds, "SeriesDescription"),
            "instances": [],
        }
        # AnatomicRegionSequence (series-level)
        ars = getattr(ds, "AnatomicRegionSequence", None)
        if ars and len(ars) > 0:
            anat = ars[0]
            series_info["anatomic_region"] = {
                "code": safe_str(anat, "CodeValue"),
                "scheme": safe_str(anat, "CodingSchemeDesignator"),
                "meaning": safe_str(anat, "CodeMeaning"),
            }
        study["series"][series_uid] = series_info
    study["series"][series_uid]["instances"].append(sop_uid)

print(f"Parsed {sum(len(s['series']) for s in dicom_studies.values())} DICOM series "
      f"across {len(dicom_studies)} studies for {len(dicom_patients)} patients")


# -- Step 2: Parse all FHIR resources ------------------------------------------

fhir_resources = {}   # "ResourceType-id" -> resource dict

for json_path in sorted(glob.glob(os.path.join(FHIR_DIR, "*.json"))):
    with open(json_path) as f:
        r = json.load(f)
    key = f"{r['resourceType']}-{r['id']}"
    fhir_resources[key] = r

print(f"Loaded {len(fhir_resources)} FHIR resources")


# -- Step 3: Cross-reference and find discrepancies ----------------------------

discrepancies = []
corrected = {}   # key -> corrected resource dict


def add_disc(resource_type, resource_id, field, fhir_value, dicom_value):
    discrepancies.append({
        "resource_type": resource_type,
        "resource_id": resource_id,
        "field": field,
        "fhir_value": fhir_value,
        "dicom_value": dicom_value,
    })


# -- 3a. Check Patients -------------------------------------------------------

for key, res in fhir_resources.items():
    if res["resourceType"] != "Patient":
        continue
    rid = res["id"]
    cr = copy.deepcopy(res)
    changed = False

    # Match FHIR Patient to DICOM patient via identifier
    pid = None
    for ident in res.get("identifier", []):
        if ident.get("value") in dicom_patients:
            pid = ident["value"]
            break
    if pid is None:
        continue
    dp = dicom_patients[pid]

    # Given name (first)
    fhir_given = res["name"][0]["given"][0]
    dicom_given = dp["given_name"]
    if fhir_given != dicom_given:
        add_disc("Patient", rid, "name[0].given[0]", fhir_given, dicom_given)
        cr["name"][0]["given"][0] = dicom_given
        changed = True

    # Middle name (maps to given[1] in FHIR)
    if dp["middle_name"]:
        fhir_given_list = res["name"][0].get("given", [])
        if len(fhir_given_list) < 2 or fhir_given_list[1] != dp["middle_name"]:
            fhir_middle = fhir_given_list[1] if len(fhir_given_list) > 1 else "missing"
            add_disc("Patient", rid, "name[0].given[1]", fhir_middle, dp["middle_name"])
            if len(cr["name"][0].get("given", [])) < 2:
                cr["name"][0]["given"].append(dp["middle_name"])
            else:
                cr["name"][0]["given"][1] = dp["middle_name"]
            changed = True

    # Family name
    fhir_family = res["name"][0]["family"]
    dicom_family = dp["family_name"]
    if fhir_family != dicom_family:
        add_disc("Patient", rid, "name[0].family", fhir_family, dicom_family)
        cr["name"][0]["family"] = dicom_family
        changed = True

    # Name prefix
    if dp["name_prefix"]:
        fhir_prefix = res["name"][0].get("prefix", [])
        dicom_prefix = [dp["name_prefix"]]
        if fhir_prefix != dicom_prefix:
            add_disc("Patient", rid, "name[0].prefix", fhir_prefix, dicom_prefix)
            cr["name"][0]["prefix"] = dicom_prefix
            changed = True

    # Name suffix
    if dp["name_suffix"]:
        fhir_suffix = res["name"][0].get("suffix", [])
        dicom_suffix = [dp["name_suffix"]]
        if fhir_suffix != dicom_suffix:
            add_disc("Patient", rid, "name[0].suffix", fhir_suffix, dicom_suffix)
            cr["name"][0]["suffix"] = dicom_suffix
            changed = True

    # Birth date
    fhir_dob = res.get("birthDate", "")
    dicom_dob = dicom_date_to_fhir(dp["birth_date"])
    if fhir_dob != dicom_dob:
        add_disc("Patient", rid, "birthDate", fhir_dob, dicom_dob)
        cr["birthDate"] = dicom_dob
        changed = True

    # Gender / sex
    fhir_gender = res.get("gender", "")
    dicom_gender = dicom_sex_to_fhir(dp["sex"])
    if fhir_gender != dicom_gender:
        add_disc("Patient", rid, "gender", fhir_gender, dicom_gender)
        cr["gender"] = dicom_gender
        changed = True

    if changed:
        corrected[f"Patient-{rid}"] = cr


# -- 3b. Check ImagingStudies -------------------------------------------------

for key, res in fhir_resources.items():
    if res["resourceType"] != "ImagingStudy":
        continue
    rid = res["id"]
    cr = copy.deepcopy(res)
    changed = False

    # Map to DICOM study via urn:dicom:uid identifier
    study_uid = None
    acsn_idx = None
    for i, ident in enumerate(res.get("identifier", [])):
        if ident.get("system") == "urn:dicom:uid":
            val = ident.get("value", "")
            if val.startswith("urn:oid:"):
                study_uid = val[8:]
        codings = ident.get("type", {}).get("coding", [])
        if any(c.get("code") == "ACSN" for c in codings):
            acsn_idx = i

    if study_uid is None or study_uid not in dicom_studies:
        continue
    dstu = dicom_studies[study_uid]

    # Accession number
    if acsn_idx is not None:
        fhir_acsn = res["identifier"][acsn_idx].get("value", "")
        dicom_acsn = dstu["accession"]
        if fhir_acsn != dicom_acsn:
            add_disc("ImagingStudy", rid, "identifier[ACSN].value",
                     fhir_acsn, dicom_acsn)
            cr["identifier"][acsn_idx]["value"] = dicom_acsn
            changed = True

    # Started date
    fhir_started = res.get("started", "")
    dicom_date = dicom_date_to_fhir(dstu["date"])
    if fhir_started != dicom_date:
        add_disc("ImagingStudy", rid, "started", fhir_started, dicom_date)
        cr["started"] = dicom_date
        changed = True

    # Study-level modality list
    dicom_mods = sorted({s["modality"] for s in dstu["series"].values()})
    fhir_mods = sorted({m.get("code", "") for m in res.get("modality", [])})
    if fhir_mods != dicom_mods:
        add_disc("ImagingStudy", rid, "modality", fhir_mods, dicom_mods)
        cr["modality"] = [{"system": DCM_CODING_SYS, "code": m}
                          for m in dicom_mods]
        changed = True

    # numberOfSeries
    dicom_n_series = len(dstu["series"])
    fhir_n_series = res.get("numberOfSeries", 0)
    if fhir_n_series != dicom_n_series:
        add_disc("ImagingStudy", rid, "numberOfSeries",
                 fhir_n_series, dicom_n_series)
        cr["numberOfSeries"] = dicom_n_series
        changed = True

    # numberOfInstances
    dicom_n_inst = sum(len(s["instances"]) for s in dstu["series"].values())
    fhir_n_inst = res.get("numberOfInstances", 0)
    if fhir_n_inst != dicom_n_inst:
        add_disc("ImagingStudy", rid, "numberOfInstances",
                 fhir_n_inst, dicom_n_inst)
        cr["numberOfInstances"] = dicom_n_inst
        changed = True

    # Per-series checks
    fhir_series_map = {s.get("uid"): s for s in res.get("series", [])}
    dicom_series_uids = set(dstu["series"].keys())
    fhir_series_uids = set(fhir_series_map.keys())

    # Missing series
    for m_uid in sorted(dicom_series_uids - fhir_series_uids):
        m_info = dstu["series"][m_uid]
        add_disc("ImagingStudy", rid, "series",
                 "missing",
                 f"Series {m_uid} ({m_info['description']})")
        new_series = {
            "uid": m_uid,
            "modality": {"system": DCM_CODING_SYS, "code": m_info["modality"]},
            "description": m_info["description"],
            "numberOfInstances": len(m_info["instances"]),
            "instance": [
                {"uid": iuid, "sopClass": {"code": "1.2.840.10008.5.1.4.1.1.7"}}
                for iuid in m_info["instances"]
            ],
        }
        cr["series"].append(new_series)
        changed = True

    # Series-level modality and bodySite
    for s_uid in sorted(fhir_series_uids & dicom_series_uids):
        dicom_s_info = dstu["series"][s_uid]
        fhir_s = fhir_series_map[s_uid]

        # Series modality
        fhir_s_mod = fhir_s.get("modality", {}).get("code", "")
        dicom_s_mod = dicom_s_info["modality"]
        if fhir_s_mod != dicom_s_mod:
            add_disc("ImagingStudy", rid,
                     f"series[{s_uid}].modality.code",
                     fhir_s_mod, dicom_s_mod)
            for i, s in enumerate(cr["series"]):
                if s.get("uid") == s_uid:
                    cr["series"][i]["modality"]["code"] = dicom_s_mod
            changed = True

        # Body site (DICOM AnatomicRegionSequence -> FHIR bodySite)
        if "anatomic_region" in dicom_s_info:
            dicom_anat = dicom_s_info["anatomic_region"]
            fhir_body_site = fhir_s.get("bodySite", {})
            fhir_bs_code = fhir_body_site.get("code", "")
            dicom_bs_code = dicom_anat["code"]

            if fhir_bs_code != dicom_bs_code:
                fhir_system = DICOM_SCHEME_TO_FHIR.get(dicom_anat["scheme"], "")
                add_disc("ImagingStudy", rid,
                         f"series[{s_uid}].bodySite.code",
                         fhir_bs_code, dicom_bs_code)
                for i, s in enumerate(cr["series"]):
                    if s.get("uid") == s_uid:
                        cr["series"][i]["bodySite"] = {
                            "system": fhir_system,
                            "code": dicom_bs_code,
                            "display": dicom_anat["meaning"],
                        }
                changed = True

    # Procedure code (DICOM ProcedureCodeSequence -> FHIR procedureCode)
    if "procedure_code" in dstu:
        dicom_proc = dstu["procedure_code"]
        fhir_proc_codes = res.get("procedureCode", [])
        dicom_sys = DICOM_SCHEME_TO_FHIR.get(dicom_proc["scheme"], "")
        dicom_code = dicom_proc["code"]

        fhir_match = False
        for pc in fhir_proc_codes:
            for coding in pc.get("coding", []):
                if coding.get("code") == dicom_code and coding.get("system") == dicom_sys:
                    fhir_match = True
                    break

        if not fhir_match and fhir_proc_codes:
            fhir_code = fhir_proc_codes[0]["coding"][0].get("code", "")
            add_disc("ImagingStudy", rid, "procedureCode[0].coding[0].code",
                     fhir_code, dicom_code)
            cr["procedureCode"] = [{
                "coding": [{
                    "system": dicom_sys,
                    "code": dicom_code,
                    "display": dicom_proc["meaning"],
                }]
            }]
            changed = True

    # Referrer (DICOM ReferringPhysicianName -> FHIR referrer Practitioner)
    if "referring_physician" in dstu:
        dicom_ref = dstu["referring_physician"]
        fhir_referrer_ref = res.get("referrer", {}).get("reference", "")

        # Find the correct Practitioner by matching DICOM name
        correct_ref = None
        for pk, pr in fhir_resources.items():
            if pr["resourceType"] != "Practitioner":
                continue
            for pname in pr.get("name", []):
                if (pname.get("family", "").lower() == dicom_ref["family"].lower() and
                    any(g.lower() == dicom_ref["given"].lower()
                        for g in pname.get("given", []))):
                    correct_ref = f"Practitioner/{pr['id']}"
                    break
            if correct_ref:
                break

        if correct_ref and fhir_referrer_ref != correct_ref:
            add_disc("ImagingStudy", rid, "referrer.reference",
                     fhir_referrer_ref, correct_ref)
            cr["referrer"] = {"reference": correct_ref}
            changed = True

    if changed:
        corrected[f"ImagingStudy-{rid}"] = cr


# -- 3c. Check DiagnosticReports ----------------------------------------------

for key, res in fhir_resources.items():
    if res["resourceType"] != "DiagnosticReport":
        continue
    rid = res["id"]
    cr = copy.deepcopy(res)
    changed = False

    subject_ref = res.get("subject", {}).get("reference", "")

    # Trace through imagingStudy references to find the correct patient
    for study_ref in res.get("imagingStudy", []):
        ref_str = study_ref.get("reference", "")
        if not ref_str.startswith("ImagingStudy/"):
            continue
        is_id = ref_str[len("ImagingStudy/"):]
        is_key = f"ImagingStudy-{is_id}"
        if is_key not in fhir_resources:
            continue
        is_res = fhir_resources[is_key]

        # Find DICOM study UID
        for ident in is_res.get("identifier", []):
            if ident.get("system") == "urn:dicom:uid":
                val = ident.get("value", "")
                if val.startswith("urn:oid:"):
                    s_uid = val[8:]
                    if s_uid in dicom_studies:
                        dicom_pid = dicom_studies[s_uid]["patient_id"]
                        # Find the FHIR patient that matches this DICOM patient ID
                        correct_ref = None
                        for pk, pr in fhir_resources.items():
                            if pr["resourceType"] != "Patient":
                                continue
                            for pi in pr.get("identifier", []):
                                if pi.get("value") == dicom_pid:
                                    correct_ref = f"Patient/{pr['id']}"
                                    break
                            if correct_ref:
                                break

                        if correct_ref and subject_ref != correct_ref:
                            add_disc("DiagnosticReport", rid,
                                     "subject.reference",
                                     subject_ref, correct_ref)
                            cr["subject"]["reference"] = correct_ref
                            changed = True

    if changed:
        corrected[f"DiagnosticReport-{rid}"] = cr


# -- Step 4: Write output ------------------------------------------------------

# Reconciliation report
report = {
    "reconciliation_summary": {
        "total_discrepancies": len(discrepancies),
        "patients_analyzed": sum(
            1 for r in fhir_resources.values() if r["resourceType"] == "Patient"),
        "studies_analyzed": sum(
            1 for r in fhir_resources.values() if r["resourceType"] == "ImagingStudy"),
        "reports_analyzed": sum(
            1 for r in fhir_resources.values() if r["resourceType"] == "DiagnosticReport"),
    },
    "discrepancies": discrepancies,
}

with open(os.path.join(OUTPUT_DIR, "reconciliation_report.json"), "w") as f:
    json.dump(report, f, indent=2)

# Corrected individual resources
for name, resource in corrected.items():
    with open(os.path.join(CORRECTED_DIR, f"{name}.json"), "w") as f:
        json.dump(resource, f, indent=2)

# FHIR Transaction Bundle
bundle = {
    "resourceType": "Bundle",
    "type": "transaction",
    "entry": [],
}

for name, resource in sorted(corrected.items()):
    rt = resource["resourceType"]
    rid = resource["id"]
    bundle["entry"].append({
        "resource": resource,
        "request": {
            "method": "PUT",
            "url": f"{rt}/{rid}",
        },
    })

with open(os.path.join(OUTPUT_DIR, "transaction_bundle.json"), "w") as f:
    json.dump(bundle, f, indent=2)

print(f"\nConformance audit complete:")
print(f"  {len(discrepancies)} discrepancies found")
print(f"  {len(corrected)} corrected resources generated")
print(f"  Report: {os.path.join(OUTPUT_DIR, 'reconciliation_report.json')}")
print(f"  Corrected files: {CORRECTED_DIR}/")
print(f"  Transaction Bundle: {os.path.join(OUTPUT_DIR, 'transaction_bundle.json')}")
