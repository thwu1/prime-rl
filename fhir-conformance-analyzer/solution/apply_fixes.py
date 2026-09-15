#!/usr/bin/env python3

"""Apply all 4 fixes to the FHIR US Core conformance pipeline.

Bug 1 (filters/capability.jq): The jq reduce overwrites instead of
    unioning when multiple profiles share a resourceType (Observation
    has both lab and vital-signs profiles). Fix: check-and-merge.

Bug 2 (checker/must_support.py): Extension presence check incorrectly
    requires a direct value* key.  US Core race/ethnicity extensions use
    sub-extensions. Fix: match on URL only.

Bug 3 (checker/references.py): _SKIP_KEYS incorrectly includes
    "encounter", causing encounter references to be skipped. Fix: remove
    "encounter" from the skip set.

Bug 4 (filters/assemble.jq): Capability score only counts search params,
    ignoring interactions.  Fix: include both in numerator/denominator.
"""

import os


def fix_capability_jq():
    """Fix Bug 1: Union requirements instead of overwriting for shared
    resourceTypes in the jq capability gap filter."""
    path = "/app/filters/capability.jq"
    with open(path) as f:
        content = f.read()

    old = """($manifest[0].profiles | to_entries | reduce .[] as $p (
  {};
  .[$p.value.resourceType] = {
    search_params: ($p.value.requiredSearchParams // []),
    interactions: ($p.value.requiredInteractions // [])
  }
)) as $required"""

    new = """($manifest[0].profiles | to_entries | reduce .[] as $p (
  {};
  if .[$p.value.resourceType] then
    .[$p.value.resourceType].search_params += ($p.value.requiredSearchParams // []) |
    .[$p.value.resourceType].search_params |= unique |
    .[$p.value.resourceType].interactions += ($p.value.requiredInteractions // []) |
    .[$p.value.resourceType].interactions |= unique
  else
    .[$p.value.resourceType] = {
      search_params: ($p.value.requiredSearchParams // []),
      interactions: ($p.value.requiredInteractions // [])
    }
  end
)) as $required"""

    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


def fix_must_support():
    """Fix Bug 2: Extension handling should not require direct value keys."""
    path = "/app/checker/must_support.py"
    with open(path) as f:
        content = f.read()

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


def fix_assemble_jq():
    """Fix Bug 4: Include interactions in capability score computation."""
    path = "/app/filters/assemble.jq"
    with open(path) as f:
        content = f.read()

    old = """(
  $cg[0].required_by_type | to_entries |
  reduce .[] as $e (
    {total_req: 0, total_present: 0};

    # Count required search parameters for this resource type
    ($e.value.search_params | length) as $n_req |

    # Count how many required search params the server actually declares
    (($cg[0].cs_by_type[$e.key] // {search_params: []}).search_params) as $decl |
    ([$e.value.search_params[] | select(. as $s | $decl | any(. == $s))] | length) as $n_present |

    .total_req += $n_req |
    .total_present += $n_present
  )
) as $cap"""

    new = """(
  $cg[0].required_by_type | to_entries |
  reduce .[] as $e (
    {total_req: 0, total_present: 0};

    # Count required search parameters and interactions
    ($e.value.search_params | length) as $n_req_sp |
    ($e.value.interactions | length) as $n_req_int |

    # Count how many the server actually declares
    (($cg[0].cs_by_type[$e.key] // {search_params: [], interactions: []}).search_params) as $decl_sp |
    (($cg[0].cs_by_type[$e.key] // {search_params: [], interactions: []}).interactions) as $decl_int |
    ([$e.value.search_params[] | select(. as $s | $decl_sp | any(. == $s))] | length) as $n_pres_sp |
    ([$e.value.interactions[] | select(. as $s | $decl_int | any(. == $s))] | length) as $n_pres_int |

    .total_req += ($n_req_sp + $n_req_int) |
    .total_present += ($n_pres_sp + $n_pres_int)
  )
) as $cap"""

    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_capability_jq()
    print("Fixed Bug 1: Capability aggregation (capability.jq)")

    fix_must_support()
    print("Fixed Bug 2: Extension handling (must_support.py)")

    fix_references()
    print("Fixed Bug 3: Reference traversal (references.py)")

    fix_assemble_jq()
    print("Fixed Bug 4: Score computation (assemble.jq)")
