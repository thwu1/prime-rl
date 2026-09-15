#!/usr/bin/env python3

"""
FHIR R4 Anonymization Engine — Reference Implementation
Compatible with Microsoft FHIR Anonymizer configuration format.
Supports: keep, redact, cryptoHash, dateShift.
Handles: NDJSON, contained resources, multiple resource types, backbone elements.
"""

import json
import hmac
import hashlib
import os
import copy
import re
from datetime import datetime, timedelta, date as date_cls


# ---------------------------------------------------------------------------
# FHIR R4 field-to-type mappings
# ---------------------------------------------------------------------------

FIELD_TYPES = {
    "Patient": {
        "id": "id", "text": "Narrative", "identifier": "Identifier",
        "name": "HumanName", "telecom": "ContactPoint", "gender": "code",
        "birthDate": "date", "deceasedDateTime": "dateTime", "deceasedBoolean": "boolean",
        "address": "Address", "managingOrganization": "Reference",
        "generalPractitioner": "Reference", "photo": "Attachment",
        "maritalStatus": "CodeableConcept", "extension": "Extension",
        "multipleBirthBoolean": "boolean", "multipleBirthInteger": "integer",
        "active": "boolean",
    },
    "Observation": {
        "id": "id", "text": "Narrative", "identifier": "Identifier",
        "status": "code", "code": "CodeableConcept", "category": "CodeableConcept",
        "subject": "Reference", "encounter": "Reference", "focus": "Reference",
        "effectiveDateTime": "dateTime", "effectivePeriod": "Period",
        "effectiveInstant": "instant", "issued": "instant",
        "performer": "Reference", "basedOn": "Reference", "partOf": "Reference",
        "valueQuantity": "Quantity", "valueCodeableConcept": "CodeableConcept",
        "valueString": "string", "valueBoolean": "boolean", "valueInteger": "integer",
        "valueDateTime": "dateTime", "valuePeriod": "Period",
        "dataAbsentReason": "CodeableConcept", "interpretation": "CodeableConcept",
        "note": "Annotation", "bodySite": "CodeableConcept", "method": "CodeableConcept",
        "specimen": "Reference", "device": "Reference",
        "hasMember": "Reference", "derivedFrom": "Reference",
        "extension": "Extension",
    },
    "Encounter": {
        "id": "id", "text": "Narrative", "identifier": "Identifier",
        "status": "code", "class": "Coding",
        "type": "CodeableConcept", "serviceType": "CodeableConcept",
        "priority": "CodeableConcept",
        "subject": "Reference", "episodeOfCare": "Reference",
        "basedOn": "Reference", "appointment": "Reference",
        "period": "Period", "length": "Duration",
        "reasonCode": "CodeableConcept", "reasonReference": "Reference",
        "serviceProvider": "Reference", "partOf": "Reference",
        "extension": "Extension",
    },
    "Condition": {
        "id": "id", "text": "Narrative", "identifier": "Identifier",
        "clinicalStatus": "CodeableConcept", "verificationStatus": "CodeableConcept",
        "category": "CodeableConcept", "severity": "CodeableConcept",
        "code": "CodeableConcept", "bodySite": "CodeableConcept",
        "subject": "Reference", "encounter": "Reference",
        "onsetDateTime": "dateTime", "onsetAge": "Age", "onsetPeriod": "Period",
        "onsetRange": "Range", "onsetString": "string",
        "abatementDateTime": "dateTime", "abatementAge": "Age",
        "abatementPeriod": "Period", "abatementRange": "Range",
        "abatementString": "string",
        "recordedDate": "dateTime",
        "recorder": "Reference", "asserter": "Reference",
        "note": "Annotation", "extension": "Extension",
    },
    "Practitioner": {
        "id": "id", "text": "Narrative", "identifier": "Identifier",
        "name": "HumanName", "telecom": "ContactPoint",
        "address": "Address", "gender": "code", "birthDate": "date",
        "photo": "Attachment", "extension": "Extension",
    },
    "Organization": {
        "id": "id", "text": "Narrative", "identifier": "Identifier",
        "name": "string", "alias": "string",
        "telecom": "ContactPoint", "address": "Address",
        "type": "CodeableConcept", "partOf": "Reference",
        "extension": "Extension",
    },
    "Bundle": {
        "id": "id", "type": "code", "timestamp": "instant",
        "total": "unsignedInt", "extension": "Extension",
    },
}

BACKBONE_TYPES = {
    ("Patient", "contact"): {
        "relationship": "CodeableConcept", "name": "HumanName",
        "telecom": "ContactPoint", "address": "Address",
        "organization": "Reference", "gender": "code", "period": "Period",
    },
    ("Encounter", "participant"): {
        "type": "CodeableConcept", "individual": "Reference",
        "period": "Period",
    },
    ("Encounter", "diagnosis"): {
        "condition": "Reference", "use": "CodeableConcept",
        "rank": "positiveInt",
    },
}

COMPLEX_SUBTYPES = {
    "Period": {"start": "dateTime", "end": "dateTime"},
}


# ---------------------------------------------------------------------------
# Rule parsing
# ---------------------------------------------------------------------------

def parse_rule(path):
    m = re.match(r"^Resource\.(\w+)$", path)
    if m:
        return {"kind": "resource_field", "field": m.group(1)}

    m = re.match(r"^(\w+)\.(\w+)$", path)
    if m:
        return {"kind": "direct", "resource": m.group(1), "field": m.group(2)}

    m = re.match(r"^(\w+)\.(\w+)\.(\w+)$", path)
    if m:
        return {"kind": "direct_sub", "resource": m.group(1),
                "field": m.group(2), "subfield": m.group(3)}

    m = re.match(r"^nodesByType\('(\w+)'\)$", path)
    if m:
        return {"kind": "by_type", "fhir_type": m.group(1)}

    m = re.match(r"^nodesByType\('(\w+)'\)\.(\w+)$", path)
    if m:
        return {"kind": "by_type_sub", "fhir_type": m.group(1), "subfield": m.group(2)}

    m = re.match(r"^(\w+)\.nodesByType\('(\w+)'\)\.(\w+)$", path)
    if m:
        return {"kind": "scoped_type_sub", "resource": m.group(1),
                "fhir_type": m.group(2), "subfield": m.group(3)}

    return {"kind": "unknown", "path": path}


# ---------------------------------------------------------------------------
# Anonymizer engine
# ---------------------------------------------------------------------------

class FhirAnonymizer:
    def __init__(self, config):
        self.rules = config.get("fhirPathRules", [])
        params = config.get("parameters", {})
        self.hash_key = params.get("cryptoHashKey", "").encode("utf-8")
        self.shift_key = params.get("dateShiftKey", "")
        self.partial_dates = params.get("enablePartialDatesForRedact", False)
        self.partial_ages = params.get("enablePartialAgesForRedact", False)
        self.parsed = [(parse_rule(r["path"]), r) for r in self.rules]
        self.tracking = []

    def _hmac(self, value):
        if not value:
            return value
        return hmac.new(self.hash_key, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _hash_ref(self, ref):
        if not ref:
            return ref
        if ref == "#":
            return "#"
        if ref.startswith("#"):
            return "#" + self._hmac(ref[1:])
        if ref.startswith("urn:"):
            idx = ref.index(":", 4)
            return ref[:idx + 1] + self._hmac(ref[idx + 1:])
        hist = ""
        working = ref
        hm = re.match(r"^(.+?)/_history/(.+)$", ref)
        if hm:
            working = hm.group(1)
            hist = "/_history/" + hm.group(2)
        slash = working.rfind("/")
        if slash >= 0:
            return working[:slash + 1] + self._hmac(working[slash + 1:]) + hist
        return self._hmac(ref)

    def _offset(self, resource_id):
        combined = (resource_id or "") + self.shift_key
        h = hashlib.sha256(combined.encode("utf-8")).digest()
        u = int.from_bytes(h[:4], "little", signed=False)
        return (u % 101) - 50

    def _age_over_89(self, date_str):
        if not self.partial_ages:
            return False
        try:
            year = int(date_str[:4])
            return (datetime.now().year - year) > 89
        except (ValueError, IndexError):
            return False

    def _shift_date(self, val, offset):
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            if self._age_over_89(val):
                return None
            return (date_cls.fromisoformat(val) + timedelta(days=offset)).isoformat()
        if re.match(r"^\d{4}(-\d{2})?$", val):
            if self._age_over_89(val):
                return None
            return val[:4] if self.partial_dates else None
        return val

    def _shift_dt(self, val, offset):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})T.*?([-+]\d{2}:\d{2}|Z)$", val)
        if m:
            dp, tz = m.group(1), m.group(2)
            if self._age_over_89(dp):
                return None
            shifted = (date_cls.fromisoformat(dp) + timedelta(days=offset)).isoformat()
            return shifted + "T00:00:00" + tz
        return self._shift_date(val, offset)

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------

    def process(self, resource, source_file=""):
        resource = copy.deepcopy(resource)
        rt = resource.get("resourceType", "")
        if rt == "Bundle":
            return self._process_bundle(resource, source_file)
        return self._process_resource(resource, source_file)

    def _process_bundle(self, bundle, source_file):
        for entry in bundle.get("entry", []):
            if "resource" in entry:
                entry["resource"] = self._process_resource(entry["resource"], source_file)
        for parsed, rule in self.parsed:
            if (parsed["kind"] == "direct_sub"
                    and parsed.get("resource") == "Bundle"
                    and parsed.get("field") == "entry"
                    and parsed.get("subfield") == "fullUrl"
                    and rule["method"] == "redact"):
                for entry in bundle.get("entry", []):
                    entry.pop("fullUrl", None)
        return bundle

    def _process_resource(self, resource, source_file=""):
        rt = resource.get("resourceType", "")
        rid = resource.get("id", "")
        offset = self._offset(rid)
        type_map = FIELD_TYPES.get(rt, {})

        # Process contained resources independently first
        if "contained" in resource:
            processed_contained = []
            for contained in resource["contained"]:
                processed_contained.append(
                    self._process_resource(contained, source_file))
            resource["contained"] = processed_contained

        # Build keep map
        kept_whole, kept_subs = self._build_keep_map(rt, type_map)

        # Track for manifest
        original_id = rid
        processed_fields = set()
        to_remove = []

        for parsed, rule in self.parsed:
            if rule["method"] == "keep":
                continue
            method = rule["method"]

            # Resource.field (matches any resource type)
            if parsed["kind"] == "resource_field":
                fname = parsed["field"]
                if fname in resource and fname not in processed_fields and fname not in kept_whole:
                    processed_fields.add(fname)
                    val = resource[fname]
                    if method == "cryptoHash" and isinstance(val, str):
                        resource[fname] = self._hmac(val)

            # ResourceType.field
            for fname in list(resource.keys()):
                if fname in ("resourceType", "contained") or fname in processed_fields or fname in kept_whole:
                    continue
                ftype = type_map.get(fname)
                if ftype is None:
                    continue

                if not self._matches_field(parsed, rt, fname, ftype):
                    continue

                processed_fields.add(fname)
                val = resource[fname]

                if method == "redact":
                    kept = kept_subs.get(fname, set())
                    if not kept:
                        to_remove.append(fname)
                    else:
                        resource[fname] = self._redact_with_kept(val, kept)

                elif method == "cryptoHash":
                    if isinstance(val, str):
                        resource[fname] = self._hmac(val)

                elif method == "dateShift":
                    result = self._apply_dateshift(val, ftype, offset)
                    if result is None:
                        to_remove.append(fname)
                    else:
                        resource[fname] = result

            # by_type_sub: apply to sub-field of typed nodes (e.g., Reference.reference)
            if parsed["kind"] == "by_type_sub":
                target_type = parsed["fhir_type"]
                subfield = parsed["subfield"]
                for fname in list(resource.keys()):
                    if fname in ("resourceType", "contained"):
                        continue
                    ftype = type_map.get(fname)
                    if ftype == target_type:
                        self._apply_to_subfield(resource, fname, subfield, method)

            # Handle complex types (Period containing dateTime sub-fields)
            if parsed["kind"] == "by_type":
                target_type = parsed["fhir_type"]
                for fname in list(resource.keys()):
                    if fname in ("resourceType", "contained") or fname in to_remove:
                        continue
                    ftype = type_map.get(fname)
                    if ftype in COMPLEX_SUBTYPES:
                        subtypes = COMPLEX_SUBTYPES[ftype]
                        for subfname, subftype in subtypes.items():
                            if subftype == target_type:
                                val = resource.get(fname)
                                if isinstance(val, dict) and subfname in val:
                                    if method == "dateShift":
                                        result = self._apply_dateshift(
                                            val[subfname], subftype, offset)
                                        if result is None:
                                            del val[subfname]
                                        else:
                                            val[subfname] = result

        for f in to_remove:
            resource.pop(f, None)

        # Process backbone elements
        for (bb_rt, bb_field), bb_types in BACKBONE_TYPES.items():
            if rt == bb_rt and bb_field in resource:
                items = resource[bb_field]
                if isinstance(items, list):
                    for item in items:
                        self._process_backbone(item, rt, bb_field, bb_types,
                                               offset, kept_subs)
                elif isinstance(items, dict):
                    self._process_backbone(items, rt, bb_field, bb_types,
                                           offset, kept_subs)

        # Record tracking for manifest
        hashed_id = resource.get("id", "")
        if original_id:
            self.tracking.append({
                "source_file": source_file,
                "resource_type": rt,
                "original_id": original_id,
                "hashed_id": hashed_id,
            })

        return resource

    def _build_keep_map(self, rt, type_map):
        kept_whole = set()
        kept_subs = {}

        for parsed, rule in self.parsed:
            if rule["method"] != "keep":
                continue

            if parsed["kind"] == "direct" and parsed.get("resource") == rt:
                kept_whole.add(parsed["field"])

            elif parsed["kind"] == "direct_sub" and parsed.get("resource") == rt:
                kept_subs.setdefault(parsed["field"], set()).add(parsed["subfield"])

            elif parsed["kind"] == "by_type_sub":
                ft = parsed["fhir_type"]
                sf = parsed["subfield"]
                for fname, ftype in type_map.items():
                    if ftype == ft:
                        kept_subs.setdefault(fname, set()).add(sf)
                # Also for backbone elements
                for (bb_rt, bb_field), bb_types in BACKBONE_TYPES.items():
                    if bb_rt == rt:
                        for bfname, bftype in bb_types.items():
                            if bftype == ft:
                                kept_subs.setdefault(
                                    f"_bb_{bb_field}_{bfname}", set()).add(sf)

            elif parsed["kind"] == "scoped_type_sub" and parsed.get("resource") == rt:
                ft = parsed["fhir_type"]
                sf = parsed["subfield"]
                for fname, ftype in type_map.items():
                    if ftype == ft:
                        kept_subs.setdefault(fname, set()).add(sf)
                for (bb_rt, bb_field), bb_types in BACKBONE_TYPES.items():
                    if bb_rt == rt:
                        for bfname, bftype in bb_types.items():
                            if bftype == ft:
                                kept_subs.setdefault(
                                    f"_bb_{bb_field}_{bfname}", set()).add(sf)

        return kept_whole, kept_subs

    def _matches_field(self, parsed, rt, fname, ftype):
        if parsed["kind"] == "direct":
            return parsed.get("resource") == rt and parsed.get("field") == fname
        if parsed["kind"] == "by_type":
            return parsed.get("fhir_type") == ftype
        return False

    def _redact_with_kept(self, val, kept):
        if isinstance(val, list):
            result = []
            for item in val:
                if isinstance(item, dict):
                    filtered = {k: v for k, v in item.items() if k in kept}
                    if filtered:
                        result.append(filtered)
                else:
                    result.append(item)
            return result if result else []
        if isinstance(val, dict):
            return {k: v for k, v in val.items() if k in kept}
        return val

    def _apply_dateshift(self, val, ftype, offset):
        s = str(val)
        if ftype == "date":
            return self._shift_date(s, offset)
        if ftype in ("dateTime", "instant"):
            return self._shift_dt(s, offset)
        return val

    def _apply_to_subfield(self, resource, fname, subfield, method):
        val = resource.get(fname)
        if isinstance(val, dict) and subfield in val:
            if method == "cryptoHash":
                val[subfield] = self._hash_ref(val[subfield])
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and subfield in item:
                    if method == "cryptoHash":
                        item[subfield] = self._hash_ref(item[subfield])

    def _process_backbone(self, obj, rt, bb_field, bb_types, offset, kept_subs):
        to_remove = []
        processed = set()

        for parsed, rule in self.parsed:
            if rule["method"] == "keep":
                continue
            method = rule["method"]

            for bfname in list(obj.keys()):
                if bfname in processed:
                    continue
                bftype = bb_types.get(bfname)
                if bftype is None:
                    continue

                matched = False
                if parsed["kind"] == "by_type" and parsed["fhir_type"] == bftype:
                    matched = True

                if not matched:
                    continue

                processed.add(bfname)

                if method == "redact":
                    kept_key = f"_bb_{bb_field}_{bfname}"
                    kept = kept_subs.get(kept_key, set())
                    if not kept:
                        to_remove.append(bfname)
                    else:
                        obj[bfname] = self._redact_with_kept(obj[bfname], kept)

                elif method == "cryptoHash" and isinstance(obj[bfname], str):
                    obj[bfname] = self._hmac(obj[bfname])

                elif method == "dateShift":
                    result = self._apply_dateshift(obj[bfname], bftype, offset)
                    if result is None:
                        to_remove.append(bfname)
                    else:
                        obj[bfname] = result

            # Handle by_type_sub inside backbone (e.g., Reference.reference)
            if parsed["kind"] == "by_type_sub":
                target_type = parsed["fhir_type"]
                subfield = parsed["subfield"]
                for bfname in list(obj.keys()):
                    bftype = bb_types.get(bfname)
                    if bftype == target_type:
                        self._apply_to_subfield(obj, bfname, subfield, method)

            # Handle complex types in backbone (Period.start/end)
            if parsed["kind"] == "by_type":
                target_type = parsed["fhir_type"]
                for bfname in list(obj.keys()):
                    if bfname in to_remove:
                        continue
                    bftype = bb_types.get(bfname)
                    if bftype in COMPLEX_SUBTYPES:
                        subtypes = COMPLEX_SUBTYPES[bftype]
                        for subfname, subftype in subtypes.items():
                            if subftype == target_type:
                                val = obj.get(bfname)
                                if isinstance(val, dict) and subfname in val:
                                    if method == "dateShift":
                                        result = self._apply_dateshift(
                                            val[subfname], subftype, offset)
                                        if result is None:
                                            del val[subfname]
                                        else:
                                            val[subfname] = result

        for f in to_remove:
            obj.pop(f, None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config_path = "/app/config.json"
    input_dir = "/app/input"
    output_dir = "/app/output"

    with open(config_path) as f:
        config = json.load(f)

    anon = FhirAnonymizer(config)
    os.makedirs(output_dir, exist_ok=True)

    # Process NDJSON file
    ndjson_input = os.path.join(input_dir, "export.ndjson")
    if os.path.exists(ndjson_input):
        ndjson_output = os.path.join(output_dir, "export.ndjson")
        with open(ndjson_input) as fin, open(ndjson_output, "w") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                resource = json.loads(line)
                result = anon.process(resource, "export.ndjson")
                fout.write(json.dumps(result, separators=(",", ":")) + "\n")
        print(f"Processed export.ndjson")

    # Process individual JSON files
    for fname in sorted(os.listdir(input_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(input_dir, fname)
        with open(fpath) as f:
            resource = json.load(f)
        result = anon.process(resource, fname)
        with open(os.path.join(output_dir, fname), "w") as f:
            json.dump(result, f, indent=2)
        print(f"Processed {fname}")

    # Write tracking data for manifest generation
    with open(os.path.join(output_dir, ".tracking.json"), "w") as f:
        json.dump(anon.tracking, f, indent=2)
    print(f"Tracking: {len(anon.tracking)} resources")


if __name__ == "__main__":
    main()
