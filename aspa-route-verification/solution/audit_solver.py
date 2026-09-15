#!/usr/bin/env python3
"""
ASPA Cache Integrity Audit Solver

Queries the SQLite database for topology, ASPA attestations, and BGP routes.
Validates signing certificates. Implements ASPA verification algorithms.
Produces /app/audit.json.
"""

import json
import sqlite3
import subprocess
import sys
from collections import defaultdict


# ============================================================
# 1. DATABASE ACCESS
# ============================================================

def load_topology(db_path):
    """Extract topology from SQLite database."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # All ASNs
    c.execute("SELECT asn FROM autonomous_systems")
    all_asns = {row[0] for row in c.fetchall()}

    # Provider-customer relationships
    customer_of = defaultdict(set)  # customer -> set of providers
    provider_of = defaultdict(set)  # provider -> set of customers
    c.execute("SELECT provider_asn, customer_asn FROM transit_relationships")
    for prov, cust in c.fetchall():
        customer_of[cust].add(prov)
        provider_of[prov].add(cust)

    # Peering relationships
    peers = set()
    c.execute("SELECT asn_a, asn_b FROM peering_sessions")
    for a, b in c.fetchall():
        peers.add((min(a, b), max(a, b)))

    conn.close()
    return all_asns, customer_of, provider_of, peers


def load_aspa_from_db(db_path):
    """Load deployed ASPA attestations with cert paths from SQLite."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""
        SELECT a.customer_asn, a.signing_cert_path,
               GROUP_CONCAT(p.provider_asn)
        FROM aspa_attestations a
        LEFT JOIN aspa_provider_entries p ON a.id = p.attestation_id
        GROUP BY a.customer_asn, a.signing_cert_path
    """)

    attestations = []
    for customer_asn, cert_path, providers_str in c.fetchall():
        providers = []
        if providers_str:
            providers = [int(x) for x in providers_str.split(",")]
        attestations.append({
            "customer_asn": customer_asn,
            "provider_set": sorted(providers),
            "signing_cert_path": cert_path,
        })

    conn.close()
    return attestations


def load_routes_from_db(db_path):
    """Load BGP route observations from SQLite."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("SELECT update_id, receiver_asn, as_path, has_as_set FROM bgp_updates")
    routes = []
    for update_id, receiver, as_path_json, has_as_set in c.fetchall():
        routes.append({
            "id": update_id,
            "receiver_asn": receiver,
            "as_path": json.loads(as_path_json),
            "has_as_set": bool(has_as_set),
        })

    conn.close()
    return routes


# ============================================================
# 2. CERTIFICATE VALIDATION
# ============================================================

def check_cert_validity(cert_path):
    """Use openssl to check if a certificate is currently valid."""
    try:
        result = subprocess.run(
            ["openssl", "x509", "-in", cert_path, "-noout", "-checkend", "0"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


# ============================================================
# 3. ASPA ERROR DETECTION
# ============================================================

def detect_errors(attestations, true_providers, cert_validity):
    """Find attestations with invalid certs or wrong provider sets."""
    errors = []
    for att in attestations:
        asn = att["customer_asn"]
        deployed = set(att["provider_set"])
        true = true_providers.get(asn, set())
        unauthorized = sorted(deployed - true)
        missing = sorted(true - deployed)
        is_valid_cert = cert_validity.get(asn, False)

        if not is_valid_cert or unauthorized or missing:
            errors.append({
                "customer_asn": asn,
                "unauthorized_providers": unauthorized,
                "missing_providers": missing,
            })
    return sorted(errors, key=lambda x: x["customer_asn"])


# ============================================================
# 4. ASPA VERIFICATION ENGINE
# ============================================================

def hop_check(db, customer, candidate_provider):
    if customer not in db:
        return "no_attestation"
    if candidate_provider in db[customer]:
        return "provider"
    return "not_provider"


def collapse(path):
    if not path:
        return path
    result = [path[0]]
    for asn in path[1:]:
        if asn != result[-1]:
            result.append(asn)
    return result


def upstream_verify(db, path, has_as_set=False):
    if has_as_set:
        return "Unverifiable", None
    p = collapse(path)
    n = len(p)
    if n <= 1:
        return "Valid", None
    checks = [hop_check(db, p[i], p[i + 1]) for i in range(n - 1)]
    for i, c in enumerate(checks):
        if c == "not_provider":
            return "Invalid", p[i]
    if all(c == "provider" for c in checks):
        return "Valid", None
    return "Unknown", None


def downstream_verify(db, path, has_as_set=False):
    if has_as_set:
        return "Unverifiable", None
    p = collapse(path)
    n = len(p)
    if n <= 1:
        return "Valid", None
    if n == 2:
        return "Valid", None

    fwd = [hop_check(db, p[i], p[i + 1]) for i in range(n - 1)]
    bwd = [hop_check(db, p[i + 1], p[i]) for i in range(n - 1)]

    u = 0
    while u < n - 1 and fwd[u] == "provider":
        u += 1

    d = 0
    while d < n - 1 and bwd[n - 2 - d] == "provider":
        d += 1

    if u + d >= n - 1:
        return "Valid", None

    for i in range(u, n - 1 - d):
        if fwd[i] == "not_provider" and bwd[i] == "not_provider":
            return "Invalid", p[i]

    return "Unknown", None


# ============================================================
# 5. DIRECTION INFERENCE
# ============================================================

def build_relationship_map(customer_of, provider_of, peers):
    rels = {}
    for customer, providers in customer_of.items():
        for provider in providers:
            rels[(provider, customer)] = "provider_of"
            rels[(customer, provider)] = "customer_of"
    for a, b in peers:
        rels[(a, b)] = "peer"
        rels[(b, a)] = "peer"
    return rels


def infer_direction(rels, receiver, neighbor):
    rel = rels.get((receiver, neighbor))
    if rel == "provider_of":
        return "downstream"
    elif rel == "customer_of":
        return "upstream"
    elif rel == "peer":
        return "upstream"
    return "unknown"


# ============================================================
# 6. DEPLOYMENT COVERAGE OPTIMIZATION
# ============================================================

def compute_deployment(corrected_db, all_asns, true_providers, unknown_routes):
    uncovered = all_asns - set(corrected_db.keys())

    coverage = {}
    for asn in uncovered:
        hyp_db = dict(corrected_db)
        hyp_db[asn] = true_providers.get(asn, set())
        resolved = []
        for rid, path, direction, has_as_set in unknown_routes:
            if direction == "upstream":
                result, _ = upstream_verify(hyp_db, path, has_as_set)
            else:
                result, _ = downstream_verify(hyp_db, path, has_as_set)
            if result != "Unknown":
                resolved.append(rid)
        if resolved:
            coverage[asn] = resolved

    remaining = set(r[0] for r in unknown_routes)
    recommendation = []
    while remaining and coverage:
        best = max(coverage.keys(),
                   key=lambda a: (len([r for r in coverage[a] if r in remaining]), -a))
        resolved_now = sorted([r for r in coverage[best] if r in remaining])
        if not resolved_now:
            break
        recommendation.append({
            "asn": best,
            "provider_set": sorted(true_providers.get(best, set())),
            "resolves_routes": resolved_now,
        })
        remaining -= set(resolved_now)
        del coverage[best]

    return recommendation


# ============================================================
# MAIN
# ============================================================

def main():
    db_path = "/app/rpki_cache.db"

    # Load data from SQLite
    all_asns, customer_of, provider_of, peers = load_topology(db_path)
    rels = build_relationship_map(customer_of, provider_of, peers)
    attestations = load_aspa_from_db(db_path)
    routes = load_routes_from_db(db_path)

    # Build true provider map from topology
    true_providers = {}
    for asn in all_asns:
        true_providers[asn] = customer_of.get(asn, set())

    # Check certificate validity
    cert_validity = {}
    for att in attestations:
        asn = att["customer_asn"]
        cert_validity[asn] = check_cert_validity(att["signing_cert_path"])
        status = "VALID" if cert_validity[asn] else "EXPIRED"
        print(f"  AS{asn} cert: {status}")

    # Detect errors
    erroneous = detect_errors(attestations, true_providers, cert_validity)
    print(f"Found {len(erroneous)} erroneous ASPA attestations")

    # Build corrected ASPA database from topology
    corrected_db = {}
    for att in attestations:
        asn = att["customer_asn"]
        corrected_db[asn] = true_providers.get(asn, set())

    corrected_aspa_json = {}
    for asn in sorted(corrected_db.keys()):
        corrected_aspa_json[str(asn)] = sorted(corrected_db[asn])

    # Analyze routes
    route_analysis = []
    unknown_routes = []
    for route in routes:
        path = route["as_path"]
        receiver = route["receiver_asn"]
        neighbor = path[-1]
        has_as_set = route.get("has_as_set", False)

        direction = infer_direction(rels, receiver, neighbor)
        if direction == "upstream":
            result, leak_asn = upstream_verify(corrected_db, path, has_as_set)
        else:
            result, leak_asn = downstream_verify(corrected_db, path, has_as_set)

        entry = {
            "id": route["id"],
            "direction": direction,
            "result": result,
            "leak_source_asn": leak_asn,
        }
        route_analysis.append(entry)
        if result == "Unknown":
            unknown_routes.append((route["id"], path, direction, has_as_set))

    print(f"Analyzed {len(route_analysis)} routes")

    # Coverage optimization
    deployment = compute_deployment(corrected_db, all_asns, true_providers,
                                    unknown_routes)
    print(f"Deployment recommendation: {len(deployment)} ASes")

    # Write output
    output = {
        "erroneous_objects": erroneous,
        "corrected_aspa": corrected_aspa_json,
        "route_analysis": route_analysis,
        "deployment_recommendation": deployment,
    }

    with open("/app/audit.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Audit report written to /app/audit.json")


if __name__ == "__main__":
    main()
