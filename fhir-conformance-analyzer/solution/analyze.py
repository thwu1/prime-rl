#!/usr/bin/env python3

"""FHIR US Core Conformance Gap Analyzer

Reads FHIR Bundle files, a US Core requirements manifest, and a CapabilityStatement,
then produces a conformance report identifying Must Support coverage gaps,
CapabilityStatement gaps, and reference integrity issues.
"""

import json
import os
import re
import glob


def load_json(path):
    with open(path) as f:
        return json.load(f)


def extract_resources_from_bundles(bundle_dir):
    """Extract all resources from all Bundle JSON files."""
    resources = []
    for filepath in sorted(glob.glob(os.path.join(bundle_dir, "*.json"))):
        bundle = load_json(filepath)
        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if resource:
                resources.append(resource)
    return resources


def build_resource_index(resources):
    """Build a lookup index of ResourceType/id for all resources."""
    index = set()
    for r in resources:
        rt = r.get("resourceType", "")
        rid = r.get("id", "")
        if rt and rid:
            index.add(f"{rt}/{rid}")
    return index


def matches_discriminator(resource, discriminator):
    """Check if a resource matches a profile's discriminator criteria."""
    if discriminator is None:
        return True
    path_parts = discriminator["path"].split(".")
    target_value = discriminator["value"]
    return _path_has_value(resource, path_parts, target_value)


def _path_has_value(obj, parts, target):
    """Recursively check if a path through nested objects/arrays reaches target value."""
    if not parts:
        return obj == target
    key = parts[0]
    rest = parts[1:]
    if isinstance(obj, dict):
        if key in obj:
            return _path_has_value(obj[key], rest, target)
        return False
    elif isinstance(obj, list):
        return any(_path_has_value(item, parts, target) for item in obj)
    return False


def element_is_present(resource, element_path, extension_urls):
    """Check if a Must Support element is populated in a resource."""
    if element_path.startswith("extension:"):
        ext_name = element_path.split(":", 1)[1]
        ext_url = extension_urls.get(ext_name, "")
        if not ext_url:
            return False
        extensions = resource.get("extension", [])
        return any(e.get("url") == ext_url for e in extensions)

    parts = element_path.split(".")
    return _element_exists(resource, parts)


def _element_exists(obj, parts):
    """Recursively check if an element path exists and has a non-None value."""
    if not parts:
        return obj is not None
    key = parts[0]
    rest = parts[1:]
    if isinstance(obj, dict):
        if key not in obj:
            return False
        val = obj[key]
        if not rest:
            return val is not None
        return _element_exists(val, rest)
    elif isinstance(obj, list):
        return any(_element_exists(item, parts) for item in obj)
    return False


def analyze_must_support(resources, manifest):
    """Analyze Must Support element coverage for each profile."""
    profiles = manifest["profiles"]
    extension_urls = manifest.get("extensionUrls", {})
    results = {}

    for profile_name, profile_def in profiles.items():
        resource_type = profile_def["resourceType"]
        discriminator = profile_def.get("discriminator")
        ms_elements = profile_def["mustSupportElements"]

        matching = [
            r for r in resources
            if r.get("resourceType") == resource_type
            and matches_discriminator(r, discriminator)
        ]

        covered = []
        missing = []
        for elem in ms_elements:
            if any(element_is_present(r, elem, extension_urls) for r in matching):
                covered.append(elem)
            else:
                missing.append(elem)

        total_elements = len(ms_elements)
        coverage_pct = round(len(covered) / total_elements, 4) if total_elements > 0 else 0.0

        results[profile_name] = {
            "total_resources": len(matching),
            "covered_elements": sorted(covered),
            "missing_elements": sorted(missing),
            "coverage_pct": coverage_pct,
        }

    return results


def analyze_capability_gaps(capability_statement, manifest):
    """Check CapabilityStatement for missing search parameters and interactions."""
    profiles = manifest["profiles"]

    # Aggregate required items by resource type (union across all profiles)
    required_by_type = {}
    for profile_def in profiles.values():
        rt = profile_def["resourceType"]
        if rt not in required_by_type:
            required_by_type[rt] = {"search_params": set(), "interactions": set()}
        required_by_type[rt]["search_params"].update(profile_def.get("requiredSearchParams", []))
        required_by_type[rt]["interactions"].update(profile_def.get("requiredInteractions", []))

    # Parse CapabilityStatement
    cs_by_type = {}
    for rest_entry in capability_statement.get("rest", []):
        for resource_entry in rest_entry.get("resource", []):
            rt = resource_entry.get("type", "")
            declared_sp = {sp["name"] for sp in resource_entry.get("searchParam", [])}
            declared_int = {i["code"] for i in resource_entry.get("interaction", [])}
            cs_by_type[rt] = {"search_params": declared_sp, "interactions": declared_int}

    # Compute gaps
    gaps = {}
    for rt in sorted(required_by_type.keys()):
        required = required_by_type[rt]
        declared = cs_by_type.get(rt, {"search_params": set(), "interactions": set()})
        missing_sp = sorted(required["search_params"] - declared["search_params"])
        missing_int = sorted(required["interactions"] - declared["interactions"])
        gaps[rt] = {
            "missing_search_params": missing_sp,
            "missing_interactions": missing_int,
        }

    return gaps, required_by_type, cs_by_type


def find_all_references(resources):
    """Find all FHIR references across all resources."""
    all_refs = []
    ref_pattern = re.compile(r"^[A-Z][a-zA-Z]+/[a-zA-Z0-9._-]+$")

    for resource in resources:
        rt = resource.get("resourceType", "")
        rid = resource.get("id", "")
        if not rt or not rid:
            continue
        source = f"{rt}/{rid}"
        _collect_refs(resource, [], source, all_refs, ref_pattern)

    return all_refs


def _collect_refs(obj, path, source, refs, pattern):
    """Recursively collect FHIR reference objects."""
    if isinstance(obj, dict):
        ref_val = obj.get("reference")
        if isinstance(ref_val, str) and pattern.match(ref_val):
            field = ".".join(path) if path else "unknown"
            refs.append({
                "source_resource": source,
                "reference": ref_val,
                "field": field,
            })
        for key, value in sorted(obj.items()):
            if key in ("resourceType", "id"):
                continue
            _collect_refs(value, path + [key], source, refs, pattern)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, path, source, refs, pattern)


def analyze_reference_integrity(resources, resource_index):
    """Analyze cross-resource reference integrity."""
    all_refs = find_all_references(resources)

    broken = []
    valid_count = 0
    for ref_info in all_refs:
        if ref_info["reference"] in resource_index:
            valid_count += 1
        else:
            broken.append(ref_info)

    broken_sorted = sorted(broken, key=lambda x: (x["source_resource"], x["field"]))

    return {
        "total_references": len(all_refs),
        "valid_references": valid_count,
        "broken_references": broken_sorted,
    }


def compute_overall_conformance(ms_results, capability_gaps, required_by_type, cs_by_type, ref_integrity):
    """Compute overall conformance scores."""
    # Must Support score: mean of per-profile coverage_pct
    coverage_pcts = [p["coverage_pct"] for p in ms_results.values()]
    ms_score = round(sum(coverage_pcts) / len(coverage_pcts), 4) if coverage_pcts else 0.0

    # Capability score: total present / total required
    total_required = 0
    total_present = 0
    for rt, required in required_by_type.items():
        req_sp = len(required["search_params"])
        req_int = len(required["interactions"])
        total_required += req_sp + req_int

        declared = cs_by_type.get(rt, {"search_params": set(), "interactions": set()})
        present_sp = len(required["search_params"] & declared["search_params"])
        present_int = len(required["interactions"] & declared["interactions"])
        total_present += present_sp + present_int

    cap_score = round(total_present / total_required, 4) if total_required > 0 else 0.0

    # Reference integrity score
    total_refs = ref_integrity["total_references"]
    valid_refs = ref_integrity["valid_references"]
    ri_score = round(valid_refs / total_refs, 4) if total_refs > 0 else 1.0

    # Total score: mean of three scores
    total_score = round((ms_score + cap_score + ri_score) / 3, 4)

    return {
        "must_support_score": ms_score,
        "capability_score": cap_score,
        "reference_integrity_score": ri_score,
        "total_score": total_score,
    }


def main():
    data_dir = "/app/data"
    output_dir = "/app/output"

    manifest = load_json(os.path.join(data_dir, "us_core_manifest.json"))
    capability_statement = load_json(os.path.join(data_dir, "capability_statement.json"))
    resources = extract_resources_from_bundles(os.path.join(data_dir, "bundles"))

    resource_index = build_resource_index(resources)

    ms_results = analyze_must_support(resources, manifest)
    cap_gaps, required_by_type, cs_by_type = analyze_capability_gaps(capability_statement, manifest)
    ref_integrity = analyze_reference_integrity(resources, resource_index)
    overall = compute_overall_conformance(ms_results, cap_gaps, required_by_type, cs_by_type, ref_integrity)

    report = {
        "must_support_coverage": ms_results,
        "capability_gaps": cap_gaps,
        "reference_integrity": ref_integrity,
        "overall_conformance": overall,
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "conformance_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    print("Conformance report written to /app/output/conformance_report.json")


if __name__ == "__main__":
    main()
