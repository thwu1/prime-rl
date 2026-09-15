#!/usr/bin/env python3
"""FHIR R4 Resource Graph Query Engine.

Loads HL7 FHIR R4 NDJSON bundles, builds an in-memory resource index,
and answers structured clinical queries via CLI subcommands.
"""

import argparse
import json
import os
import sys
from collections import defaultdict

DATA_DIR = "/app/fhir_data"


class FHIRStore:
    """In-memory store for FHIR R4 resources loaded from NDJSON files."""

    def __init__(self, data_dir):
        self.resources = {}  # {resource_type: {id: resource_dict}}
        self._load(data_dir)

    def _load(self, data_dir):
        for fname in sorted(os.listdir(data_dir)):
            if not fname.endswith(".ndjson"):
                continue
            rtype = fname[:-7]  # strip .ndjson
            self.resources[rtype] = {}
            with open(os.path.join(data_dir, fname)) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    r = json.loads(line)
                    rid = r.get("id", "")
                    self.resources[rtype][rid] = r

    def get(self, ref_str):
        """Resolve a 'ResourceType/id' reference string to a resource dict."""
        if "/" not in ref_str:
            return None
        rtype, rid = ref_str.split("/", 1)
        return self.resources.get(rtype, {}).get(rid)

    def exists(self, ref_str):
        """Check whether a reference target exists in the store."""
        return self.get(ref_str) is not None

    def get_all(self, rtype):
        """Return dict of {id: resource} for a resource type."""
        return self.resources.get(rtype, {})

    def patient_id_of(self, resource):
        """Extract patient ID from a resource's subject reference."""
        ref = resource.get("subject", {}).get("reference", "")
        if ref.startswith("Patient/"):
            return ref.split("/", 1)[1]
        return None

    def iter_references(self, resource):
        """Yield (field_name, target_ref_string) for all Reference fields.

        Handles both direct Reference fields and References nested one level
        deep in arrays (e.g., Encounter.location[].location).
        """
        for key, val in resource.items():
            if key in ("resourceType", "id"):
                continue
            if isinstance(val, dict) and "reference" in val:
                yield key, val["reference"]
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        for subkey, subval in item.items():
                            if isinstance(subval, dict) and "reference" in subval:
                                yield f"{key}.{subkey}", subval["reference"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_name(patient):
    names = patient.get("name", [])
    if not names:
        return ""
    n = names[0]
    given = " ".join(n.get("given", []))
    family = n.get("family", "")
    return f"{given} {family}".strip()


def extract_code_info(resource):
    """Return (code, display) from a resource's code element."""
    coding = resource.get("code", {}).get("coding", [])
    if coding:
        return coding[0].get("code", ""), coding[0].get("display", "")
    return "", resource.get("code", {}).get("text", "")


def extract_med_name(medication):
    """Extract display name from a Medication resource."""
    if not medication:
        return None
    coding = medication.get("code", {}).get("coding", [])
    if coding:
        return coding[0].get("display", None)
    return medication.get("code", {}).get("text", None)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_patient_summary(store, patient_id):
    patient = store.get(f"Patient/{patient_id}")
    if not patient:
        return {"error": f"Patient {patient_id} not found"}

    type_key = {
        "Encounter": "encounters",
        "Observation": "observations",
        "MedicationRequest": "medication_requests",
        "Condition": "conditions",
        "Procedure": "procedures",
    }
    counts = {v: 0 for v in type_key.values()}

    for rtype, key in type_key.items():
        for rid, r in store.get_all(rtype).items():
            if store.patient_id_of(r) == patient_id:
                counts[key] += 1

    return {
        "patient_id": patient_id,
        "name": extract_name(patient),
        "gender": patient.get("gender", ""),
        "birth_date": patient.get("birthDate", ""),
        **counts,
    }


def cmd_resolve_chain(store, resource_type, resource_id):
    ref_str = f"{resource_type}/{resource_id}"
    resource = store.get(ref_str)
    if not resource:
        return {"error": f"Resource {ref_str} not found"}

    visited = set()

    def _resolve(r):
        r_ref = f"{r.get('resourceType', '')}/{r.get('id', '')}"
        node = {"resource": r_ref, "references": []}
        for field, target in store.iter_references(r):
            if target in visited:
                continue
            visited.add(target)
            ref_info = {"type": field, "target": target}
            target_r = store.get(target)
            if target_r:
                sub = _resolve(target_r)
                if sub.get("references"):
                    ref_info["references"] = sub["references"]
            node["references"].append(ref_info)
        return node

    return _resolve(resource)


def cmd_find_observations(store, patient_id, code=None, start=None, end=None):
    results = []
    for oid, obs in store.get_all("Observation").items():
        if store.patient_id_of(obs) != patient_id:
            continue

        obs_code, obs_display = extract_code_info(obs)
        if code and obs_code != code:
            continue

        eff_dt = obs.get("effectiveDateTime", "")
        eff_date = eff_dt[:10] if eff_dt else ""

        if start and eff_date < start:
            continue
        if end and eff_date > end:
            continue

        entry = {
            "id": oid,
            "code": obs_code,
            "display": obs_display,
            "date": eff_dt,
        }

        vq = obs.get("valueQuantity")
        if vq:
            entry["value"] = vq.get("value")
            entry["unit"] = vq.get("unit", "")

        components = obs.get("component", [])
        if components:
            entry["components"] = []
            for comp in components:
                cc_list = comp.get("code", {}).get("coding", [])
                cc = cc_list[0].get("code", "") if cc_list else ""
                cd = cc_list[0].get("display", "") if cc_list else ""
                cvq = comp.get("valueQuantity", {})
                entry["components"].append({
                    "code": cc,
                    "display": cd,
                    "value": cvq.get("value"),
                    "unit": cvq.get("unit", ""),
                })

        results.append(entry)

    results.sort(key=lambda x: x.get("date", ""))
    return results


def cmd_medication_timeline(store, patient_id):
    entries = []
    for mrid, mr in store.get_all("MedicationRequest").items():
        if store.patient_id_of(mr) != patient_id:
            continue

        authored = mr.get("authoredOn", "")
        med_ref = mr.get("medicationReference", {}).get("reference", "")
        med = store.get(med_ref) if med_ref else None
        med_id = med_ref.split("/")[1] if "/" in med_ref else None

        entries.append({
            "date": authored[:10] if authored else "",
            "medication_id": med_id,
            "medication_name": extract_med_name(med),
            "request_id": mrid,
        })

    entries.sort(key=lambda x: x.get("date", ""))
    return entries


def cmd_integrity_check(store):
    dangling = []
    temporal = []

    # Check all references across all resource types
    for rtype in store.resources:
        for rid, r in store.get_all(rtype).items():
            for field, target in store.iter_references(r):
                if not store.exists(target):
                    dangling.append({
                        "source": f"{rtype}/{rid}",
                        "field": field,
                        "target": target,
                    })

    # Check encounter temporal validity
    for eid, enc in store.get_all("Encounter").items():
        period = enc.get("period", {})
        p_start = period.get("start", "")
        p_end = period.get("end", "")
        if p_start and p_end and p_start > p_end:
            temporal.append({
                "resource": f"Encounter/{eid}",
                "start": p_start,
                "end": p_end,
            })

    return {
        "total_issues": len(dangling) + len(temporal),
        "dangling_references": dangling,
        "temporal_violations": temporal,
    }


def cmd_resource_coverage(store):
    coverage = {}
    resource_types = ["Encounter", "Observation", "MedicationRequest",
                      "Condition", "Procedure"]

    for pid in store.get_all("Patient"):
        counts = {}
        for rtype in resource_types:
            cnt = 0
            for rid, r in store.get_all(rtype).items():
                if store.patient_id_of(r) == pid:
                    cnt += 1
            counts[rtype] = cnt
        coverage[pid] = counts

    return coverage


def cmd_aggregate_observations(store, patient_id, code):
    values = []
    display = ""

    for oid, obs in store.get_all("Observation").items():
        if store.patient_id_of(obs) != patient_id:
            continue
        obs_code, obs_display = extract_code_info(obs)
        if obs_code != code:
            continue

        vq = obs.get("valueQuantity", {})
        val = vq.get("value")
        if val is not None:
            values.append({
                "value": val,
                "date": obs.get("effectiveDateTime", ""),
            })
            if not display:
                display = obs_display

    values.sort(key=lambda x: x.get("date", ""))

    if not values:
        return {
            "patient_id": patient_id,
            "code": code,
            "display": display or "",
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "values": [],
        }

    nums = [v["value"] for v in values]
    return {
        "patient_id": patient_id,
        "code": code,
        "display": display,
        "count": len(nums),
        "min": min(nums),
        "max": max(nums),
        "mean": sum(nums) / len(nums),
        "values": values,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="FHIR R4 Resource Graph Query Engine"
    )
    sub = parser.add_subparsers(dest="command")

    p_ps = sub.add_parser("patient-summary")
    p_ps.add_argument("patient_id")

    p_rc = sub.add_parser("resolve-chain")
    p_rc.add_argument("resource_type")
    p_rc.add_argument("resource_id")

    p_fo = sub.add_parser("find-observations")
    p_fo.add_argument("patient_id")
    p_fo.add_argument("--code", default=None)
    p_fo.add_argument("--start", default=None)
    p_fo.add_argument("--end", default=None)

    p_mt = sub.add_parser("medication-timeline")
    p_mt.add_argument("patient_id")

    sub.add_parser("integrity-check")
    sub.add_parser("resource-coverage")

    p_ao = sub.add_parser("aggregate-observations")
    p_ao.add_argument("patient_id")
    p_ao.add_argument("--code", required=True)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    store = FHIRStore(DATA_DIR)

    dispatch = {
        "patient-summary": lambda: cmd_patient_summary(store, args.patient_id),
        "resolve-chain": lambda: cmd_resolve_chain(
            store, args.resource_type, args.resource_id
        ),
        "find-observations": lambda: cmd_find_observations(
            store, args.patient_id, args.code, args.start, args.end
        ),
        "medication-timeline": lambda: cmd_medication_timeline(
            store, args.patient_id
        ),
        "integrity-check": lambda: cmd_integrity_check(store),
        "resource-coverage": lambda: cmd_resource_coverage(store),
        "aggregate-observations": lambda: cmd_aggregate_observations(
            store, args.patient_id, args.code
        ),
    }

    result = dispatch[args.command]()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
