
"""FHIR US Core Conformance Checker — Entry Point

Audits FHIR Bundle exports against US Core v6.1.0 profile requirements,
analyzing Must Support coverage, CapabilityStatement compliance,
reference integrity, and overall conformance scores.
"""

import json
import os
import glob

from .must_support import analyze_must_support
from .capability import analyze_capability_gaps
from .references import analyze_reference_integrity
from .scoring import compute_overall_conformance


def load_json(path):
    """Load and parse a JSON file."""
    with open(path) as f:
        return json.load(f)


def extract_resources_from_bundles(bundle_dir):
    """Extract all resources from all Bundle JSON files in a directory."""
    resources = []
    for filepath in sorted(glob.glob(os.path.join(bundle_dir, "*.json"))):
        bundle = load_json(filepath)
        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if resource:
                resources.append(resource)
    return resources


def main():
    data_dir = "/app/data"
    output_dir = "/app/output"

    manifest = load_json(os.path.join(data_dir, "us_core_manifest.json"))
    capability_statement = load_json(os.path.join(data_dir, "capability_statement.json"))
    resources = extract_resources_from_bundles(os.path.join(data_dir, "bundles"))

    ms_results = analyze_must_support(resources, manifest)
    cap_gaps, required_by_type, cs_by_type = analyze_capability_gaps(
        capability_statement, manifest
    )
    ref_integrity = analyze_reference_integrity(resources)
    overall = compute_overall_conformance(
        ms_results, cap_gaps, required_by_type, cs_by_type, ref_integrity
    )

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
