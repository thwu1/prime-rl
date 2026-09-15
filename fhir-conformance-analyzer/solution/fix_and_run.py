#!/usr/bin/env python3

"""Fix all 4 bugs in the FHIR US Core conformance checker and re-run it.

Bug 1 (must_support.py): Extension presence check incorrectly requires a
    direct value* key on the extension object. US Core race/ethnicity
    extensions use sub-extensions (nested extension arrays) rather than
    direct values. The fix: check only that the extension URL matches,
    regardless of whether it carries a direct value or sub-extensions.

Bug 2 (capability.py): When building per-resource-type requirement sets,
    the code overwrites rather than taking the union when multiple profiles
    share a resourceType (e.g., Observation has both lab and vital-signs
    profiles). The fix: initialize once, then update/union subsequent profiles.

Bug 3 (references.py): The _SKIP_KEYS set incorrectly includes "encounter",
    causing encounter references to be skipped during traversal. Encounter
    is a clinical backbone element containing real references, not metadata.
    The fix: remove "encounter" from _SKIP_KEYS.

Bug 4 (scoring.py): Capability score computation only counts search params,
    ignoring interactions (read, search-type, vread). The fix: include
    both search params and interactions in the numerator and denominator.
"""

import os
import subprocess


def fix_must_support():
    """Fix Bug 1: Extension handling should not require direct value keys."""
    path = "/app/checker/must_support.py"
    with open(path) as f:
        content = f.read()

    # Replace the buggy extension check that requires value* keys
    old = """        # Check that the extension is present and carries a value rather than
        # being an empty or structurally incomplete entry
        for ext in extensions:
            if ext.get("url") == ext_url:
                # Verify extension carries a value (not just metadata)
                if any(k.startswith("value") for k in ext):
                    return True
        return False"""

    new = """        # An extension is present if any entry has the matching URL,
        # regardless of whether it uses a direct value or sub-extensions
        return any(ext.get("url") == ext_url for ext in extensions)"""

    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


def fix_capability():
    """Fix Bug 2: Aggregate requirements via union, not overwrite."""
    path = "/app/checker/capability.py"
    with open(path) as f:
        content = f.read()

    old = """    required_by_type = {}
    for profile_def in profiles.values():
        rt = profile_def["resourceType"]
        required_by_type[rt] = {
            "search_params": set(profile_def.get("requiredSearchParams", [])),
            "interactions": set(profile_def.get("requiredInteractions", [])),
        }"""

    new = """    required_by_type = {}
    for profile_def in profiles.values():
        rt = profile_def["resourceType"]
        if rt not in required_by_type:
            required_by_type[rt] = {"search_params": set(), "interactions": set()}
        required_by_type[rt]["search_params"].update(
            profile_def.get("requiredSearchParams", [])
        )
        required_by_type[rt]["interactions"].update(
            profile_def.get("requiredInteractions", [])
        )"""

    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


def fix_references():
    """Fix Bug 3: Remove 'encounter' from skip keys."""
    path = "/app/checker/references.py"
    with open(path) as f:
        content = f.read()

    old = """_SKIP_KEYS = frozenset({
    "text", "meta", "contained", "encounter", "resourceType", "id",
})"""

    new = """_SKIP_KEYS = frozenset({
    "text", "meta", "contained", "resourceType", "id",
})"""

    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


def fix_scoring():
    """Fix Bug 4: Include interactions in capability score computation."""
    path = "/app/checker/scoring.py"
    with open(path) as f:
        content = f.read()

    old = """    # Capability score: ratio of present search parameters to total required
    total_required = 0
    total_present = 0
    for rt, required in required_by_type.items():
        req_sp = len(required["search_params"])
        total_required += req_sp

        declared = cs_by_type.get(
            rt, {"search_params": set(), "interactions": set()}
        )
        present_sp = len(required["search_params"] & declared["search_params"])
        total_present += present_sp"""

    new = """    # Capability score: ratio of present items to total required
    # (both search parameters and interactions contribute)
    total_required = 0
    total_present = 0
    for rt, required in required_by_type.items():
        req_sp = len(required["search_params"])
        req_int = len(required["interactions"])
        total_required += req_sp + req_int

        declared = cs_by_type.get(
            rt, {"search_params": set(), "interactions": set()}
        )
        present_sp = len(required["search_params"] & declared["search_params"])
        present_int = len(required["interactions"] & declared["interactions"])
        total_present += present_sp + present_int"""

    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_must_support()
    print("Fixed Bug 1: Extension handling (must_support.py)")

    fix_capability()
    print("Fixed Bug 2: Capability aggregation (capability.py)")

    fix_references()
    print("Fixed Bug 3: Reference traversal (references.py)")

    fix_scoring()
    print("Fixed Bug 4: Score computation (scoring.py)")

    # Remove stale output and re-run the checker
    output_path = "/app/output/conformance_report.json"
    if os.path.exists(output_path):
        os.remove(output_path)

    print("\nRunning corrected checker...")
    subprocess.run(["python3", "-m", "checker"], cwd="/app", check=True)
