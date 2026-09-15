#!/usr/bin/env python3

"""Cross-resource reference integrity analysis for FHIR conformance.

Reads extracted resources from /app/build/resources.json, scans for FHIR
references (objects containing a ``reference`` key with a ResourceType/id
pattern), builds a global resource index, and identifies broken references
that point to non-existent resources.  Outputs JSON to stdout.
"""

import json
import re
import sys

# Keys to skip during reference traversal — these contain narrative text,
# resource metadata, or embedded resources that should not be treated as
# external references
_SKIP_KEYS = frozenset({
    "text", "meta", "contained", "encounter", "resourceType", "id",
})


def _build_resource_index(resources):
    """Build a lookup set of ``ResourceType/id`` for all known resources."""
    index = set()
    for r in resources:
        rt = r.get("resourceType", "")
        rid = r.get("id", "")
        if rt and rid:
            index.add(f"{rt}/{rid}")
    return index


def _collect_refs(obj, path, source, refs, pattern):
    """Recursively collect FHIR reference objects from a resource tree.

    Traverses the resource structure looking for objects that contain a
    ``reference`` key whose value matches the ResourceType/id pattern.
    Skips keys in ``_SKIP_KEYS`` to avoid noise from narrative and metadata.
    """
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
            if key in _SKIP_KEYS:
                continue
            _collect_refs(value, path + [key], source, refs, pattern)
    elif isinstance(obj, list):
        for item in obj:
            _collect_refs(item, path, source, refs, pattern)


def _find_all_references(resources):
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


def analyze_reference_integrity(resources):
    """Analyze cross-resource reference integrity.

    Returns a dict with total_references, valid_references, and
    broken_references (sorted by source_resource then field).
    """
    resource_index = _build_resource_index(resources)
    all_refs = _find_all_references(resources)

    broken = []
    valid_count = 0
    for ref_info in all_refs:
        if ref_info["reference"] in resource_index:
            valid_count += 1
        else:
            broken.append(ref_info)

    broken_sorted = sorted(
        broken, key=lambda x: (x["source_resource"], x["field"])
    )

    return {
        "total_references": len(all_refs),
        "valid_references": valid_count,
        "broken_references": broken_sorted,
    }


# ── Entry point ───────────────────────────────────────────────────────

def main():
    with open("/app/build/resources.json") as f:
        resources = json.load(f)

    result = analyze_reference_integrity(resources)
    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
