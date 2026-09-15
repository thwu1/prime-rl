#!/usr/bin/env python3
"""
HL7 v2.5.1 ADT_A01 to FHIR R4 Transaction Bundle Converter.

Parses pipe-delimited HL7 v2 messages and converts them to FHIR R4
Transaction Bundles following the mapping spec in /app/mapping_spec.md.
"""

import json
import sys
import os
import uuid
import argparse


# ---------------------------------------------------------------------------
# HL7 v2 Parser
# ---------------------------------------------------------------------------

class HL7Message:
    """Parses an HL7 v2.x pipe-delimited message."""

    def __init__(self, raw_text):
        self.segments = []
        self.field_sep = "|"
        self.component_sep = "^"
        self.repetition_sep = "~"
        self.escape_char = "\\"
        self.subcomponent_sep = "&"
        self._parse(raw_text)

    def _parse(self, raw_text):
        lines = raw_text.strip().replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue
            seg_type = line[:3]
            if seg_type == "MSH":
                self._parse_encoding(line)
                fields = line.split(self.field_sep)
                # MSH-1 = field separator, MSH-2 = encoding chars
                segment = {"type": "MSH", "fields": ["MSH", self.field_sep] + fields[1:]}
            else:
                fields = line.split(self.field_sep)
                segment = {"type": seg_type, "fields": fields}
            self.segments.append(segment)

    def _parse_encoding(self, msh_line):
        self.field_sep = msh_line[3]
        enc = msh_line[4:8]
        self.component_sep = enc[0]
        self.repetition_sep = enc[1]
        self.escape_char = enc[2]
        self.subcomponent_sep = enc[3]

    def get_segments(self, seg_type):
        return [s for s in self.segments if s["type"] == seg_type]

    def get_segment(self, seg_type):
        segs = self.get_segments(seg_type)
        return segs[0] if segs else None

    def get_field(self, segment, field_index):
        """Return field value.  MSH and other segments share the same
        index mapping because MSH fields include '|' at index 1."""
        if field_index < len(segment["fields"]):
            return segment["fields"][field_index]
        return ""

    def parse_components(self, field_value):
        if not field_value:
            return []
        return field_value.split(self.component_sep)

    def parse_repetitions(self, field_value):
        if not field_value:
            return []
        return field_value.split(self.repetition_sep)

    def unescape(self, value):
        if not value or self.escape_char not in value:
            return value
        e = self.escape_char
        value = value.replace(f"{e}F{e}", self.field_sep)
        value = value.replace(f"{e}S{e}", self.component_sep)
        value = value.replace(f"{e}T{e}", self.subcomponent_sep)
        value = value.replace(f"{e}R{e}", self.repetition_sep)
        value = value.replace(f"{e}E{e}", self.escape_char)
        return value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_OID, seed))


def _hl7_date(d):
    if not d or len(d) < 8:
        return d
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _hl7_datetime(dt):
    if not dt:
        return None
    if len(dt) >= 14:
        return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}T{dt[8:10]}:{dt[10:12]}:{dt[12:14]}"
    if len(dt) >= 12:
        return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}T{dt[8:10]}:{dt[10:12]}:00"
    return _hl7_date(dt)


GENDER_MAP = {"M": "male", "F": "female", "O": "other", "U": "unknown", "A": "other"}

PATIENT_CLASS_MAP = {
    "I": ("IMP", "inpatient encounter"),
    "O": ("AMB", "ambulatory"),
    "E": ("EMER", "emergency"),
    "R": ("IMP", "inpatient encounter"),
    "P": ("PRENC", "pre-admission"),
    "B": ("OBSENC", "observation encounter"),
}

ALLERGY_CAT_MAP = {"DA": "medication", "FA": "food", "EA": "environment", "LA": "environment"}
ALLERGY_CRIT_MAP = {"SV": "high", "MO": "low", "MI": "low"}

CODING_SYSTEM_MAP = {
    "ICD-10-CM": "http://hl7.org/fhir/sid/icd-10-cm",
    "ICD-10": "http://hl7.org/fhir/sid/icd-10",
    "ICD-9-CM": "http://hl7.org/fhir/sid/icd-9-cm",
    "RXNORM": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "SNOMED": "http://snomed.info/sct",
    "LOINC": "http://loinc.org",
    "L": "http://terminology.hl7.org/CodeSystem/v2-0396",
}


# ---------------------------------------------------------------------------
# Data-type converters
# ---------------------------------------------------------------------------

def _cwe_to_cc(msg, raw):
    """CWE -> CodeableConcept."""
    comps = msg.parse_components(raw)
    code = msg.unescape(comps[0]) if len(comps) > 0 and comps[0] else None
    display = msg.unescape(comps[1]) if len(comps) > 1 and comps[1] else None
    system_name = comps[2] if len(comps) > 2 and comps[2] else None
    if not code:
        return None
    coding = {"code": code}
    if display:
        coding["display"] = display
    fhir_sys = CODING_SYSTEM_MAP.get(system_name, system_name) if system_name else None
    if fhir_sys:
        coding["system"] = fhir_sys
    result = {"coding": [coding]}
    if display:
        result["text"] = display
    return result


def _xpn_to_name(msg, raw):
    """XPN -> HumanName."""
    comps = msg.parse_components(raw)
    name = {}
    family = msg.unescape(comps[0]) if len(comps) > 0 and comps[0] else None
    given1 = msg.unescape(comps[1]) if len(comps) > 1 and comps[1] else None
    given2 = msg.unescape(comps[2]) if len(comps) > 2 and comps[2] else None
    suffix = msg.unescape(comps[3]) if len(comps) > 3 and comps[3] else None
    prefix = msg.unescape(comps[4]) if len(comps) > 4 and comps[4] else None
    if family:
        name["family"] = family
    given = [g for g in (given1, given2) if g]
    if given:
        name["given"] = given
    if prefix:
        name["prefix"] = [prefix]
    if suffix:
        name["suffix"] = [suffix]
    return name or None


def _xad_to_address(msg, raw):
    """XAD -> Address."""
    comps = msg.parse_components(raw)
    addr = {}
    line1 = msg.unescape(comps[0]) if len(comps) > 0 and comps[0] else None
    line2 = msg.unescape(comps[1]) if len(comps) > 1 and comps[1] else None
    city = msg.unescape(comps[2]) if len(comps) > 2 and comps[2] else None
    state = msg.unescape(comps[3]) if len(comps) > 3 and comps[3] else None
    postal = msg.unescape(comps[4]) if len(comps) > 4 and comps[4] else None
    country = msg.unescape(comps[5]) if len(comps) > 5 and comps[5] else None
    lines = [l for l in (line1, line2) if l]
    if lines:
        addr["line"] = lines
    if city:
        addr["city"] = city
    if state:
        addr["state"] = state
    if postal:
        addr["postalCode"] = postal
    if country:
        addr["country"] = country
    return addr or None


def _xtn_to_contactpoint(msg, raw):
    """XTN -> ContactPoint."""
    comps = msg.parse_components(raw)
    old_num = msg.unescape(comps[0]) if len(comps) > 0 and comps[0] else None
    use_code = comps[1] if len(comps) > 1 and comps[1] else None
    equip = comps[2] if len(comps) > 2 and comps[2] else None
    email = msg.unescape(comps[3]) if len(comps) > 3 and comps[3] else None
    local = msg.unescape(comps[6]) if len(comps) > 6 and comps[6] else None

    if equip == "Internet" and email:
        value = email
    elif local:
        value = local
    elif old_num:
        value = old_num
    else:
        return None

    sys_map = {"PH": "phone", "CP": "phone", "FX": "fax", "Internet": "email", "BP": "pager"}
    system = sys_map.get(equip, "phone")
    use_map = {"PRN": "home", "WPN": "work", "ORN": "old", "NET": "home"}
    use = use_map.get(use_code, "home")
    cp = {"system": system, "value": value}
    if use:
        cp["use"] = use
    return cp


def _cx_to_identifier(msg, raw):
    """CX -> Identifier."""
    comps = msg.parse_components(raw)
    id_val = msg.unescape(comps[0]) if len(comps) > 0 and comps[0] else None
    if not id_val:
        return None
    authority = msg.unescape(comps[3]) if len(comps) > 3 and comps[3] else None
    type_code = comps[4] if len(comps) > 4 and comps[4] else None
    ident = {"value": id_val}
    if authority:
        ident["system"] = (
            f"urn:oid:{authority}" if "." in authority
            else f"http://hospital.example.org/{authority}"
        )
    if type_code:
        display_map = {
            "MR": "Medical Record Number",
            "SS": "Social Security Number",
            "DL": "Driver's License",
            "PPN": "Passport Number",
        }
        ident["type"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                "code": type_code,
                "display": display_map.get(type_code, type_code),
            }]
        }
    return ident


# ---------------------------------------------------------------------------
# Resource builders
# ---------------------------------------------------------------------------

def build_patient(msg, msg_id):
    patient = {"resourceType": "Patient"}

    pid = msg.get_segment("PID")
    if not pid:
        return None, None
    pid3 = msg.get_field(pid, 3)
    if pid3:
        idents = [_cx_to_identifier(msg, r) for r in msg.parse_repetitions(pid3)]
        idents = [i for i in idents if i]
        if idents:
            patient["identifier"] = idents

    pid5 = msg.get_field(pid, 5)
    if pid5:
        names = [_xpn_to_name(msg, r) for r in msg.parse_repetitions(pid5)]
        names = [n for n in names if n]
        if names:
            patient["name"] = names

    pid7 = msg.get_field(pid, 7)
    if pid7:
        patient["birthDate"] = _hl7_date(pid7)

    pid8 = msg.get_field(pid, 8)
    if pid8:
        patient["gender"] = GENDER_MAP.get(pid8, "unknown")

    pid11 = msg.get_field(pid, 11)
    if pid11:
        addrs = [_xad_to_address(msg, r) for r in msg.parse_repetitions(pid11)]
        addrs = [a for a in addrs if a]
        if addrs:
            patient["address"] = addrs

    telecoms = []
    pid13 = msg.get_field(pid, 13)
    if pid13:
        for r in msg.parse_repetitions(pid13):
            cp = _xtn_to_contactpoint(msg, r)
            if cp:
                telecoms.append(cp)
    pid14 = msg.get_field(pid, 14)
    if pid14:
        for r in msg.parse_repetitions(pid14):
            cp = _xtn_to_contactpoint(msg, r)
            if cp:
                cp["use"] = "work"
                telecoms.append(cp)
    if telecoms:
        patient["telecom"] = telecoms

    pid15 = msg.get_field(pid, 15)
    if pid15:
        patient["communication"] = [{"language": {"text": pid15}}]

    pid16 = msg.get_field(pid, 16)
    if pid16:
        ms_map = {
            "S": ("S", "Never Married"), "M": ("M", "Married"),
            "D": ("D", "Divorced"), "W": ("W", "Widowed"), "A": ("A", "Separated"),
        }
        code, display = ms_map.get(pid16, (pid16, pid16))
        patient["maritalStatus"] = {
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-MaritalStatus",
                "code": code, "display": display,
            }]
        }

    pid_val = patient.get("identifier", [{}])[0].get("value", "unknown")
    pat_uuid = _uuid(f"Patient/{msg_id}/{pid_val}")
    return patient, pat_uuid


def build_encounter(msg, msg_id, patient_uuid):
    pv1 = msg.get_segment("PV1")
    if not pv1:
        return None, None
    enc = {
        "resourceType": "Encounter",
        "status": "in-progress",
        "subject": {"reference": f"urn:uuid:{patient_uuid}"},
    }

    pv1_2 = msg.get_field(pv1, 2)
    if pv1_2:
        code, display = PATIENT_CLASS_MAP.get(pv1_2, ("AMB", "ambulatory"))
        enc["class"] = {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": code,
            "display": display,
        }

    pv1_7 = msg.get_field(pv1, 7)
    if pv1_7:
        participants = []
        for rep in msg.parse_repetitions(pv1_7):
            comps = msg.parse_components(rep)
            doc_id = comps[0] if len(comps) > 0 else None
            doc_fam = comps[1] if len(comps) > 1 else None
            doc_giv = comps[2] if len(comps) > 2 else None
            if doc_id or doc_fam:
                part = {
                    "type": [{"coding": [{
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ParticipationType",
                        "code": "ATND", "display": "attender",
                    }]}],
                    "individual": {
                        "display": ", ".join(filter(None, [doc_fam, doc_giv])),
                    },
                }
                if doc_id:
                    part["individual"]["identifier"] = {"value": doc_id}
                participants.append(part)
        if participants:
            enc["participant"] = participants

    pv1_19 = msg.get_field(pv1, 19)
    if pv1_19:
        enc["identifier"] = [{"system": "http://hospital.example.org/visit", "value": pv1_19}]

    pv1_44 = msg.get_field(pv1, 44)
    if pv1_44:
        start = _hl7_datetime(pv1_44)
        if start:
            enc["period"] = {"start": start}

    visit_id = pv1_19 or msg_id
    enc_uuid = _uuid(f"Encounter/{msg_id}/{visit_id}")
    return enc, enc_uuid


def build_related_person(msg, nk1, msg_id, patient_uuid, idx):
    rp = {
        "resourceType": "RelatedPerson",
        "patient": {"reference": f"urn:uuid:{patient_uuid}"},
    }
    nk1_2 = msg.get_field(nk1, 2)
    if nk1_2:
        name = _xpn_to_name(msg, nk1_2)
        if name:
            rp["name"] = [name]
    nk1_3 = msg.get_field(nk1, 3)
    if nk1_3:
        role_map = {
            "SPO": ("SPO", "spouse"), "FTH": ("FTH", "father"),
            "MTH": ("MTH", "mother"), "CHD": ("CHD", "child"),
            "SIB": ("SIB", "sibling"), "EMC": ("C", "emergency contact"),
            "GRD": ("GRD", "guardian"),
        }
        code, display = role_map.get(nk1_3, (nk1_3, nk1_3))
        rp["relationship"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/v2-0131",
            "code": code, "display": display,
        }]}]
    nk1_4 = msg.get_field(nk1, 4)
    if nk1_4:
        addr = _xad_to_address(msg, nk1_4)
        if addr:
            rp["address"] = [addr]
    nk1_5 = msg.get_field(nk1, 5)
    if nk1_5:
        tels = [_xtn_to_contactpoint(msg, r) for r in msg.parse_repetitions(nk1_5)]
        tels = [t for t in tels if t]
        if tels:
            rp["telecom"] = tels
    return rp, _uuid(f"RelatedPerson/{msg_id}/{idx}")


def build_condition(msg, dg1, msg_id, patient_uuid, idx):
    cond = {
        "resourceType": "Condition",
        "subject": {"reference": f"urn:uuid:{patient_uuid}"},
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "active",
        }]},
    }
    dg1_3 = msg.get_field(dg1, 3)
    if dg1_3:
        cc = _cwe_to_cc(msg, dg1_3)
        if cc:
            cond["code"] = cc
    dg1_6 = msg.get_field(dg1, 6)
    if dg1_6:
        cond["category"] = [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
            "code": "encounter-diagnosis",
            "display": "Encounter Diagnosis",
        }]}]
    return cond, _uuid(f"Condition/{msg_id}/{idx}")


def build_allergy(msg, al1, msg_id, patient_uuid, idx):
    ai = {
        "resourceType": "AllergyIntolerance",
        "patient": {"reference": f"urn:uuid:{patient_uuid}"},
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical",
            "code": "active",
        }]},
        "verificationStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification",
            "code": "confirmed",
        }]},
    }
    al1_2 = msg.get_field(al1, 2)
    if al1_2:
        ai["category"] = [ALLERGY_CAT_MAP.get(al1_2, "medication")]
    al1_3 = msg.get_field(al1, 3)
    if al1_3:
        cc = _cwe_to_cc(msg, al1_3)
        if cc:
            ai["code"] = cc
    al1_4 = msg.get_field(al1, 4)
    if al1_4:
        ai["criticality"] = ALLERGY_CRIT_MAP.get(al1_4, "unable-to-assess")
    al1_5 = msg.get_field(al1, 5)
    if al1_5:
        manifs = []
        for r in msg.parse_repetitions(al1_5):
            if r:
                manifs.append({"text": msg.unescape(r)})
        if manifs:
            ai["reaction"] = [{"manifestation": manifs}]
    al1_6 = msg.get_field(al1, 6)
    if al1_6:
        ai["onsetDateTime"] = _hl7_date(al1_6)
    return ai, _uuid(f"AllergyIntolerance/{msg_id}/{idx}")


def build_coverage(msg, in1, msg_id, patient_uuid, idx):
    cov = {
        "resourceType": "Coverage",
        "status": "active",
        "beneficiary": {"reference": f"urn:uuid:{patient_uuid}"},
    }
    in1_2 = msg.get_field(in1, 2)
    if in1_2:
        cov.setdefault("identifier", []).append({"type": {"text": "Plan ID"}, "value": in1_2})
    in1_4 = msg.get_field(in1, 4)
    if in1_4:
        cov["payor"] = [{"display": msg.unescape(in1_4)}]
    in1_12 = msg.get_field(in1, 12)
    in1_13 = msg.get_field(in1, 13)
    period = {}
    if in1_12:
        period["start"] = _hl7_date(in1_12)
    if in1_13:
        period["end"] = _hl7_date(in1_13)
    if period:
        cov["period"] = period
    return cov, _uuid(f"Coverage/{msg_id}/{idx}")


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

def _entry(resource, res_uuid):
    return {
        "fullUrl": f"urn:uuid:{res_uuid}",
        "resource": resource,
        "request": {"method": "POST", "url": resource["resourceType"]},
    }


def convert(msg):
    msh = msg.get_segment("MSH")
    msg_id = msg.get_field(msh, 10) if msh else "unknown"
    entries = []

    pat, pat_uuid = build_patient(msg, msg_id)
    if not pat:
        raise ValueError("PID segment required")
    entries.append(_entry(pat, pat_uuid))

    enc, enc_uuid = build_encounter(msg, msg_id, pat_uuid)
    if enc:
        entries.append(_entry(enc, enc_uuid))

    for i, nk1 in enumerate(msg.get_segments("NK1")):
        rp, rp_uuid = build_related_person(msg, nk1, msg_id, pat_uuid, i)
        entries.append(_entry(rp, rp_uuid))

    for i, dg1 in enumerate(msg.get_segments("DG1")):
        cond, cond_uuid = build_condition(msg, dg1, msg_id, pat_uuid, i)
        entries.append(_entry(cond, cond_uuid))

    for i, al1 in enumerate(msg.get_segments("AL1")):
        ai, ai_uuid = build_allergy(msg, al1, msg_id, pat_uuid, i)
        entries.append(_entry(ai, ai_uuid))

    for i, in1 in enumerate(msg.get_segments("IN1")):
        cov, cov_uuid = build_coverage(msg, in1, msg_id, pat_uuid, i)
        entries.append(_entry(cov, cov_uuid))

    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def process_file(input_path, output_path):
    with open(input_path) as f:
        raw = f.read()
    msg = HL7Message(raw)
    bundle = convert(msg)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(bundle, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="HL7 v2 -> FHIR R4 Converter")
    parser.add_argument("input", nargs="?", help="Input .hl7 file (or dir with --batch)")
    parser.add_argument("output", nargs="?", help="Output .json file (or dir with --batch)")
    parser.add_argument("--batch", action="store_true", help="Batch: input/output are dirs")
    parser.add_argument("--stats", help="Path to write conversion statistics JSON")
    args = parser.parse_args()

    stats = {"messages_processed": 0, "bundles": []}

    if args.batch:
        input_dir, output_dir = args.input, args.output
        os.makedirs(output_dir, exist_ok=True)
        for fname in sorted(os.listdir(input_dir)):
            if fname.endswith(".hl7"):
                fpath = os.path.join(input_dir, fname)
                with open(fpath) as f:
                    raw = f.read()
                msg = HL7Message(raw)
                bundle = convert(msg)

                msh = msg.get_segment("MSH")
                ctrl_id = msg.get_field(msh, 10) if msh else fname.replace(".hl7", "")
                out_path = os.path.join(output_dir, f"{ctrl_id}.json")
                with open(out_path, "w") as f:
                    json.dump(bundle, f, indent=2, ensure_ascii=False)

                rcounts = {}
                for entry in bundle.get("entry", []):
                    rt = entry["resource"]["resourceType"]
                    rcounts[rt] = rcounts.get(rt, 0) + 1
                stats["messages_processed"] += 1
                stats["bundles"].append({
                    "message_control_id": ctrl_id,
                    "resource_counts": rcounts,
                })

                print(f"Converted {fname} -> {ctrl_id}.json "
                      f"({len(bundle['entry'])} entries)")
    else:
        if not args.input or not args.output:
            parser.error("Provide input and output paths, or use --batch")
        process_file(args.input, args.output)

    if args.stats:
        os.makedirs(os.path.dirname(args.stats) or ".", exist_ok=True)
        with open(args.stats, "w") as f:
            json.dump(stats, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
