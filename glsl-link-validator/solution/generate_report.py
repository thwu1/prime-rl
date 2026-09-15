#!/usr/bin/env python3
"""
Generate the diagnostic report classifying all defects found
in the GLSL ES 3.00 conformance pipeline.

"""

import json
import subprocess
import os
import sys

VALIDATOR_ORIG = "/solution/glsl_link_validator.py"
VALIDATOR_FIXED = "/app/glsl_link_validator.py"
MANIFEST = "/app/test_harness/manifest.json"
SHADER_DIR = "/app/test_harness/shaders"


def run_validator(validator_path, vert_path, frag_path):
    """Run a validator and return parsed JSON output."""
    r = subprocess.run(
        ["python3", validator_path, vert_path, frag_path],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def main():
    with open(MANIFEST) as f:
        manifest = json.load(f)

    # Catalog of known defects with classifications
    defects = [
        {
            "source": "validator",
            "affected_cases": ["case_08"],
            "root_cause": (
                "Struct type comparison uses Python type-name string equality "
                "instead of structural comparison of members; structs with "
                "different names but identical member lists are incorrectly "
                "flagged as TYPE_MISMATCH"
            ),
            "fix_applied": (
                "Changed type comparison to first check whether both sides are "
                "struct types and, if so, compare member lists structurally "
                "(ordered list of (type, name) tuples) regardless of struct "
                "type name"
            ),
        },
        {
            "source": "validator",
            "affected_cases": ["case_09"],
            "root_cause": (
                "Struct member comparison converts member lists to set() before "
                "comparing, which discards declaration order; per GLSL ES 3.00 "
                "spec section 4.3.10, member declaration order must match"
            ),
            "fix_applied": (
                "Changed struct member comparison from set equality to ordered "
                "list equality to enforce declaration-order matching as required "
                "by the spec"
            ),
        },
        {
            "source": "validator",
            "affected_cases": ["case_10"],
            "root_cause": (
                "The declaration regex only recognizes name[N] array syntax "
                "(array size after variable name) but not type[N] name syntax "
                "(array size between type and name), causing type[N] declarations "
                "to be unparsed"
            ),
            "fix_applied": (
                "Added parsing branch for array size appearing between the type "
                "keyword and the variable name, treating type[N] name as "
                "semantically equivalent to type name[N]"
            ),
        },
        {
            "source": "validator",
            "affected_cases": ["case_11"],
            "root_cause": (
                "When parsing comma-separated multi-variable declarations "
                "(e.g., 'out vec4 a, b, c'), only the first variable name is "
                "captured; subsequent comma-separated names are silently dropped"
            ),
            "fix_applied": (
                "Updated parsing to split on commas and iterate over all "
                "variable names in a declaration, creating a separate VarDecl "
                "for each with inherited qualifiers"
            ),
        },
        {
            "source": "validator",
            "affected_cases": ["case_12"],
            "root_cause": (
                "The layout location regex 'layout\\(location=(\\d+)\\)' requires "
                "zero whitespace between tokens; any spaces inside the "
                "parentheses cause the match to fail and the location to be None"
            ),
            "fix_applied": (
                "Replaced rigid regex with a proper token-based parser that "
                "skips whitespace when reading the layout qualifier, accepting "
                "'layout( location = N )' as equivalent to 'layout(location=N)'"
            ),
        },
        {
            "source": "validator",
            "affected_cases": ["case_05"],
            "root_cause": (
                "The invariant mismatch check only tests whether the vertex "
                "output has the invariant flag set (unconditionally reporting "
                "an error), rather than comparing both vertex and fragment "
                "invariant flags; this produces false positives when both "
                "sides are correctly invariant"
            ),
            "fix_applied": (
                "Changed invariant check from 'if vd.invariant' (one-sided) "
                "to 'if vd.invariant != fd.invariant' (bilateral comparison), "
                "reporting INVARIANT_MISMATCH only when the flags disagree"
            ),
        },
        {
            "source": "manifest",
            "affected_cases": ["case_14"],
            "root_cause": (
                "Expected result incorrectly marks centroid-vs-smooth "
                "interpolation as valid; per spec section 4.3.10, centroid is "
                "a distinct auxiliary qualifier and 'centroid out' does NOT "
                "match a bare 'out' (which implies smooth without centroid)"
            ),
            "fix_applied": (
                "Changed case_14 expected to valid=false with an "
                "INTERPOLATION_MISMATCH error on the affected variable"
            ),
        },
        {
            "source": "manifest",
            "affected_cases": ["case_15"],
            "root_cause": (
                "Expected result incorrectly marks matching explicit highp "
                "precision qualifiers as invalid with PRECISION_MISMATCH; "
                "per spec section 4.3.10, when both sides carry matching "
                "explicit precision, linking is valid"
            ),
            "fix_applied": (
                "Changed case_15 expected to valid=true with no errors"
            ),
        },
        {
            "source": "manifest",
            "affected_cases": ["case_16"],
            "root_cause": (
                "Expected result incorrectly marks structs with different "
                "member names (but same member types) as valid; per spec "
                "section 4.3.10, structural comparison requires member names, "
                "types, AND order to all match"
            ),
            "fix_applied": (
                "Changed case_16 expected to valid=false with a "
                "STRUCT_MISMATCH error on the affected variable"
            ),
        },
    ]

    validator_count = sum(1 for d in defects if d["source"] == "validator")
    manifest_count = sum(1 for d in defects if d["source"] == "manifest")

    report = {
        "validator_bugs": validator_count,
        "manifest_errors": manifest_count,
        "defects": defects,
    }

    with open("/app/diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Diagnostic report generated: {validator_count} validator bugs, "
          f"{manifest_count} manifest errors, {len(defects)} total defects")


if __name__ == "__main__":
    main()
