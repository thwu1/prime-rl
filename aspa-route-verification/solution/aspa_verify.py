#!/usr/bin/env python3
"""
ASPA Route Verification Engine -- Solution

Implements the upstream and downstream ASPA verification algorithms
per the specification at /app/spec.md.
"""

import json
import sys


def load_aspa_db(filepath):
    with open(filepath) as f:
        data = json.load(f)
    db = {}
    if "aspa_objects" not in data:
        print(f"ERROR: 'aspa_objects' key not in {filepath}. Keys found: {list(data.keys())}", file=sys.stderr)
        print(f"File content preview: {json.dumps(data)[:500]}", file=sys.stderr)
        sys.exit(1)
    for obj in data["aspa_objects"]:
        db[obj["customer_asn"]] = set(obj["providers"])
    return db


def load_routes(filepath):
    with open(filepath) as f:
        data = json.load(f)
    if "routes" not in data:
        print(f"ERROR: 'routes' key not in {filepath}. Keys found: {list(data.keys())}", file=sys.stderr)
        sys.exit(1)
    return data["routes"]


def hop_check(db, customer_as, candidate_provider):
    """Section 4: Hop Check Function."""
    if customer_as not in db:
        return "no_attestation"
    if candidate_provider in db[customer_as]:
        return "provider"
    return "not_provider"


def collapse_prepends(path):
    """Section 3: Remove consecutive duplicate ASNs."""
    if not path:
        return path
    result = [path[0]]
    for asn in path[1:]:
        if asn != result[-1]:
            result.append(asn)
    return result


def upstream_verify(db, route):
    """Section 5: Upstream Path Verification."""
    if route.get("has_as_set", False):
        return "Unverifiable"

    path = collapse_prepends(route["as_path"])
    n = len(path)

    if n <= 1:
        return "Valid"

    checks = []
    for i in range(n - 1):
        checks.append(hop_check(db, path[i], path[i + 1]))

    if "not_provider" in checks:
        return "Invalid"
    if all(c == "provider" for c in checks):
        return "Valid"
    return "Unknown"


def downstream_verify(db, route):
    """Section 6: Downstream Path Verification."""
    if route.get("has_as_set", False):
        return "Unverifiable"

    path = collapse_prepends(route["as_path"])
    n = len(path)

    if n <= 1:
        return "Valid"
    if n == 2:
        return "Valid"

    # Compute forward (uphill) and backward (downhill) hop checks
    fwd = []
    bwd = []
    for i in range(n - 1):
        fwd.append(hop_check(db, path[i], path[i + 1]))
        bwd.append(hop_check(db, path[i + 1], path[i]))

    # Find up-ramp length (consecutive "provider" from start of fwd)
    u = 0
    while u < n - 1 and fwd[u] == "provider":
        u += 1

    # Find down-ramp length (consecutive "provider" from end of bwd)
    d = 0
    while d < n - 1 and bwd[n - 2 - d] == "provider":
        d += 1

    # Check if ramps cover the entire path
    if u + d >= n - 1:
        return "Valid"

    # Gap analysis: check each uncovered position
    for i in range(u, n - 1 - d):
        if fwd[i] == "not_provider" and bwd[i] == "not_provider":
            return "Invalid"

    return "Unknown"


def verify_route(db, route):
    if route["direction"] == "upstream":
        return upstream_verify(db, route)
    else:
        return downstream_verify(db, route)


def main():
    db = load_aspa_db("/app/aspa_objects.json")
    routes = load_routes("/app/routes.json")

    results = []
    for route in routes:
        result = verify_route(db, route)
        results.append({"id": route["id"], "result": result})

    with open("/app/results.json", "w") as f:
        json.dump({"results": results}, f, indent=2)

    print(f"Processed {len(results)} routes")
    for r in results:
        print(f"  {r['id']}: {r['result']}")


if __name__ == "__main__":
    main()
