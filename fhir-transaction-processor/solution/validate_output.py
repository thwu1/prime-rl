#!/usr/bin/env python3

"""FHIR transaction-response Bundle conformance validator using FHIRPath."""

import json
import re
import sys

from fhirpathpy import evaluate


def validate_bundle(bundle: dict) -> list[str]:
    """Validate a transaction-response Bundle. Returns list of error messages."""
    errors = []

    # 1. Check Bundle.type using FHIRPath
    bundle_type = evaluate(bundle, "Bundle.type", {})
    if not bundle_type or bundle_type[0] != "transaction-response":
        actual = bundle_type[0] if bundle_type else None
        errors.append(
            f"Bundle.type must be 'transaction-response', got '{actual}'"
        )

    # 2. Check all entries have response.status using FHIRPath
    entries = bundle.get("entry", [])
    statuses = evaluate(bundle, "Bundle.entry.response.status", {})
    if len(statuses) < len(entries):
        errors.append(
            f"Not all entries have response.status: "
            f"{len(statuses)} statuses for {len(entries)} entries"
        )

    # 3. Check ETag format (FHIR R4 mandates weak validators: W/"...")
    etags = evaluate(bundle, "Bundle.entry.response.etag", {})
    weak_etag_re = re.compile(r'^W/"[^"]*"$')
    for etag in etags:
        if not weak_etag_re.match(str(etag)):
            errors.append(
                f"ETag '{etag}' does not use weak validator format W/\"...\""
            )

    # 4. Check for unresolved urn:uuid references
    serialized = json.dumps(bundle)
    if "urn:uuid:" in serialized:
        errors.append("Bundle contains unresolved urn:uuid references")

    return errors


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <bundle.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        bundle = json.load(f)

    errors = validate_bundle(bundle)

    if errors:
        print("VALIDATION FAILED:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("VALIDATION PASSED: Bundle is conformant")
        sys.exit(0)


if __name__ == "__main__":
    main()
