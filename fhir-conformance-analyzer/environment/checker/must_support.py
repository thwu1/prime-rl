#!/usr/bin/env python3

"""Must Support element coverage analysis for FHIR US Core profiles.

Reads extracted resources from /app/build/resources.json and the US Core
manifest from /app/data/us_core_manifest.json.  Outputs the analysis as
JSON to stdout for consumption by the pipeline Makefile.
"""

import json
import sys


# ── FHIR path utilities ──────────────────────────────────────────────

def element_exists(obj, parts):
    """Check if a dot-separated element path exists in a FHIR resource.

    Handles traversal into nested objects and arrays.  For arrays, checks
    if any element in the array satisfies the remaining path.
    """
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
        return element_exists(val, rest)
    elif isinstance(obj, list):
        return any(element_exists(item, parts) for item in obj)
    return False


def path_has_value(obj, parts, target):
    """Check if traversing a path through nested objects/arrays reaches
    *target*.  Used for discriminator matching (e.g., checking
    ``category.coding.code == "laboratory"``).
    """
    if not parts:
        return obj == target
    key = parts[0]
    rest = parts[1:]
    if isinstance(obj, dict):
        if key in obj:
            return path_has_value(obj[key], rest, target)
        return False
    elif isinstance(obj, list):
        return any(path_has_value(item, parts, target) for item in obj)
    return False


# ── Core analysis ─────────────────────────────────────────────────────

def _matches_discriminator(resource, discriminator):
    """Return True if *resource* matches *discriminator* criteria."""
    if discriminator is None:
        return True
    path_parts = discriminator["path"].split(".")
    return path_has_value(resource, path_parts, discriminator["value"])


def _element_is_present(resource, element_path, extension_urls):
    """Check if a Must Support element is populated in *resource*.

    Two path forms are handled:
    * ``extension:<name>`` — resolved via *extension_urls* mapping
    * dot-separated regular paths — traversed through nested objects/arrays
    """
    if element_path.startswith("extension:"):
        ext_name = element_path.split(":", 1)[1]
        ext_url = extension_urls.get(ext_name, "")
        if not ext_url:
            return False
        extensions = resource.get("extension", [])
        # Check that the extension is present and carries a value rather than
        # being an empty or structurally incomplete entry
        for ext in extensions:
            if ext.get("url") == ext_url:
                # Verify extension carries a value (not just metadata)
                if any(k.startswith("value") for k in ext):
                    return True
        return False

    parts = element_path.split(".")
    return element_exists(resource, parts)


def analyze_must_support(resources, manifest):
    """Analyze Must Support element coverage for each profile in *manifest*.

    Returns a dict keyed by profile name with total_resources,
    covered_elements, missing_elements, and coverage_pct per profile.
    """
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
            and _matches_discriminator(r, discriminator)
        ]

        covered = []
        missing = []
        for elem in ms_elements:
            if any(_element_is_present(r, elem, extension_urls) for r in matching):
                covered.append(elem)
            else:
                missing.append(elem)

        total_elements = len(ms_elements)
        coverage_pct = (
            round(len(covered) / total_elements, 4) if total_elements > 0 else 0.0
        )

        results[profile_name] = {
            "total_resources": len(matching),
            "covered_elements": sorted(covered),
            "missing_elements": sorted(missing),
            "coverage_pct": coverage_pct,
        }

    return results


# ── Entry point ───────────────────────────────────────────────────────

def main():
    with open("/app/build/resources.json") as f:
        resources = json.load(f)
    with open("/app/data/us_core_manifest.json") as f:
        manifest = json.load(f)

    result = analyze_must_support(resources, manifest)
    json.dump(result, sys.stdout, indent=2)


if __name__ == "__main__":
    main()
