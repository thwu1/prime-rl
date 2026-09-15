#!/usr/bin/env python3
"""
Solution: Multi-Layer RPKI Route Security Audit

1. Verify RPKI object signatures using openssl
2. Determine trusted ROAs and ASPAs
3. Perform ROV classification
4. Perform ASPA path verification
5. Compute composite verdicts with risk scores
6. Evaluate attack scenarios

This solution uses openssl for signature verification, sqlite3 for
the routing security database, and jq concepts for data extraction.
"""

import json
import subprocess
import sqlite3
import os
import ipaddress

APP = "/app"

def load_json(path):
    with open(path) as f:
        return json.load(f)


# ============================================================
# Step 1: Verify RPKI object signatures
# ============================================================

def verify_signature(data_file, sig_file, pub_key_file):
    """Use openssl to verify a signature. Returns True if valid."""
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", pub_key_file,
         "-signature", sig_file, data_file],
        capture_output=True, text=True
    )
    return result.returncode == 0


def determine_trust(manifest, entity_registry, revocation_list, base_dir):
    """Determine which RPKI objects are trusted."""
    revoked = set(revocation_list.get("revoked_entities", []))
    results = []

    for obj in manifest:
        obj_id = obj.get("roa_id") or obj.get("aspa_id")
        signer = obj["signing_entity"]
        data_file = os.path.join(base_dir, obj["data_file"])
        sig_file = os.path.join(base_dir, obj["signature_file"])
        pub_key = os.path.join(base_dir, entity_registry[signer]["public_key_file"])

        if signer in revoked:
            results.append({"id": obj_id, "trusted": False, "reason": "signing_entity_revoked"})
        elif not verify_signature(data_file, sig_file, pub_key):
            results.append({"id": obj_id, "trusted": False, "reason": "invalid_signature"})
        else:
            results.append({"id": obj_id, "trusted": True, "reason": "valid"})

    return results


# ============================================================
# Step 2: Route Origin Validation (ROV)
# ============================================================

def prefix_covers(roa_prefix_str, roa_max_length, route_prefix_str):
    """Check if a ROA covers a route prefix."""
    roa_net = ipaddress.ip_network(roa_prefix_str)
    route_net = ipaddress.ip_network(route_prefix_str)

    # The ROA prefix must contain the route prefix
    if not roa_net.supernet_of(route_net) and roa_net != route_net:
        return False
    # The route prefix length must not exceed max_length
    if route_net.prefixlen > roa_max_length:
        return False
    return True


def rov_classify(route, trusted_roas):
    """Classify a route using ROV.
    Returns (status, unsafe_flag)
    status: Valid, Invalid, NotFound
    unsafe_flag: True if a matching ROA has excessive MaxLength
    """
    prefix = route["prefix"]
    origin = route["origin_as"]

    covering_roas = []
    for roa in trusted_roas:
        roa_net = ipaddress.ip_network(roa["prefix"])
        route_net = ipaddress.ip_network(prefix)
        # Check if the ROA's prefix covers the route's prefix
        if (roa_net.supernet_of(route_net) or roa_net == route_net) and route_net.prefixlen <= roa["max_length"]:
            covering_roas.append(roa)

    if not covering_roas:
        return "NotFound", False

    # Check if any covering ROA matches the origin
    for roa in covering_roas:
        if roa["asn"] == origin:
            # Check for MaxLength vulnerability
            roa_net = ipaddress.ip_network(roa["prefix"])
            unsafe = (roa["max_length"] - roa_net.prefixlen) >= 4
            return "Valid", unsafe

    return "Invalid", False


# ============================================================
# Step 3: ASPA Path Verification
# ============================================================

def collapse_consecutive(seq):
    """Remove only consecutive duplicate ASNs."""
    if not seq:
        return []
    out = [seq[0]]
    for a in seq[1:]:
        if a != out[-1]:
            out.append(a)
    return out


def hop_check(customer, candidate, aspa_db):
    """Check if customer has authorized candidate as provider."""
    key = str(customer)
    if key not in aspa_db:
        return "NoAttestation"
    if candidate in aspa_db[key]:
        return "ProviderPlus"
    return "NotProviderPlus"


def verify_upstream(path, aspa_db):
    n = len(path)
    if n <= 1:
        return "Valid"
    has_unknown = False
    for i in range(n - 1):
        h = hop_check(path[i], path[i + 1], aspa_db)
        if h == "NotProviderPlus":
            return "Invalid"
        if h == "NoAttestation":
            has_unknown = True
    return "Unknown" if has_unknown else "Valid"


def verify_downstream(path, aspa_db):
    n = len(path)
    if n <= 2:
        return "Valid"

    # Forward scan: up-ramp
    u = 0
    for i in range(n - 1):
        if hop_check(path[i], path[i + 1], aspa_db) == "NotProviderPlus":
            break
        u = i + 1

    # Reverse scan: down-ramp
    d = n - 1
    for j in range(n - 1, 0, -1):
        if hop_check(path[j], path[j - 1], aspa_db) == "NotProviderPlus":
            break
        d = j - 1

    # Valley-free shape check
    if u + 1 < d:
        return "Invalid"

    # Attestation completeness
    for i in range(u):
        if hop_check(path[i], path[i + 1], aspa_db) == "NoAttestation":
            return "Unknown"
    for j in range(n - 1, d, -1):
        if hop_check(path[j], path[j - 1], aspa_db) == "NoAttestation":
            return "Unknown"

    return "Valid"


def aspa_classify(route, aspa_db):
    """Classify a route using ASPA verification."""
    raw_path = list(reversed(route["as_path"]))
    path = collapse_consecutive(raw_path)
    relationship = route["relationship"]

    if relationship == "customer":
        return verify_upstream(path, aspa_db)
    else:  # provider or peer
        return verify_downstream(path, aspa_db)


# ============================================================
# Step 4: Composite Policy
# ============================================================

def compute_risk_score(rov_status, aspa_status, unsafe_flag, involves_revoked):
    score = 1  # base
    if rov_status == "Invalid":
        score += 5
    elif rov_status == "NotFound":
        score += 2
    if aspa_status == "Invalid":
        score += 4
    elif aspa_status == "Unknown":
        score += 1
    if unsafe_flag:
        score += 2
    if involves_revoked:
        score += 3
    return min(score, 10)


def compute_verdict(rov_status, aspa_status, risk_score):
    """Determine ACCEPT/REJECT/REVIEW based on policy requirements."""
    if risk_score >= 7:
        return "REJECT"
    if rov_status == "Invalid":
        return "REJECT"
    if aspa_status == "Invalid":
        return "REJECT"
    if rov_status != "Valid" and aspa_status != "Valid":
        return "REJECT"
    if rov_status == "Valid" and aspa_status == "Valid":
        return "ACCEPT"
    if rov_status == "NotFound" and aspa_status == "Valid":
        return "REVIEW"
    if rov_status == "Valid" and aspa_status == "Unknown":
        return "REVIEW"
    if rov_status == "NotFound" and aspa_status == "Unknown":
        return "REVIEW"
    return "REVIEW"


# ============================================================
# Step 5: Attack Evaluation
# ============================================================

def evaluate_attacks(attack_scenarios, verdicts_map):
    """Evaluate each attack scenario."""
    results = []
    for attack in attack_scenarios:
        affected = attack["affected_routes"]
        all_rejected = all(
            verdicts_map.get(rid, {}).get("verdict") == "REJECT"
            for rid in affected
        )
        any_detected = any(
            verdicts_map.get(rid, {}).get("verdict") in ("REJECT", "REVIEW")
            for rid in affected
        )
        results.append({
            "scenario_id": attack["scenario_id"],
            "name": attack["name"],
            "detected": any_detected,
            "mitigated": all_rejected,
            "affected_route_verdicts": {
                rid: verdicts_map.get(rid, {}).get("verdict", "MISSING")
                for rid in affected
            }
        })
    return results


# ============================================================
# Main
# ============================================================

def main():
    # Load data
    entity_registry = load_json(f"{APP}/entity_registry.json")
    revocation_list = load_json(f"{APP}/revocation_list.json")
    roa_manifest = load_json(f"{APP}/roa_manifest.json")
    aspa_manifest = load_json(f"{APP}/aspa_manifest.json")
    routes = load_json(f"{APP}/rib.json")
    topology = load_json(f"{APP}/topology.json")
    attack_scenarios = load_json(f"{APP}/attack_scenarios.json")

    # Step 1: Verify signatures and determine trust
    print("Step 1: Verifying RPKI object signatures...")
    roa_trust = determine_trust(roa_manifest, entity_registry, revocation_list, APP)
    aspa_trust = determine_trust(aspa_manifest, entity_registry, revocation_list, APP)

    all_trust = roa_trust + aspa_trust
    with open(f"{APP}/trusted_objects.json", "w") as f:
        json.dump(all_trust, f, indent=2)
    print(f"  Trusted: {sum(1 for t in all_trust if t['trusted'])}, "
          f"Untrusted: {sum(1 for t in all_trust if not t['trusted'])}")

    # Build trusted ROA and ASPA sets
    trusted_roa_ids = {t["id"] for t in roa_trust if t["trusted"]}
    trusted_aspa_ids = {t["id"] for t in aspa_trust if t["trusted"]}

    trusted_roas = []
    for entry in roa_manifest:
        if entry["roa_id"] in trusted_roa_ids:
            roa_data = load_json(os.path.join(APP, entry["data_file"]))
            trusted_roas.append(roa_data)

    # Build trusted ASPA database
    aspa_db = {}
    for entry in aspa_manifest:
        if entry["aspa_id"] in trusted_aspa_ids:
            aspa_data = load_json(os.path.join(APP, entry["data_file"]))
            key = str(aspa_data["customer_as"])
            aspa_db[key] = aspa_data["authorized_providers"]

    # Determine which routes involve revoked cert entities
    revoked_roa_signers = {
        entry["roa_id"]: entry["signing_entity"]
        for entry in roa_manifest
    }
    revoked_aspa_signers = {
        entry["aspa_id"]: entry["signing_entity"]
        for entry in aspa_manifest
    }
    revoked_entities = set(revocation_list.get("revoked_entities", []))

    # Step 2: ROV
    print("Step 2: Performing Route Origin Validation...")
    rov_results = []
    for route in routes:
        status, unsafe = rov_classify(route, trusted_roas)
        rov_results.append({
            "route_id": route["route_id"],
            "rov_status": status,
            "unsafe_maxlength": unsafe
        })
    with open(f"{APP}/rov_results.json", "w") as f:
        json.dump(rov_results, f, indent=2)

    # Step 3: ASPA
    print("Step 3: Performing ASPA path verification...")
    aspa_results = []
    for route in routes:
        status = aspa_classify(route, aspa_db)
        aspa_results.append({
            "route_id": route["route_id"],
            "aspa_status": status
        })
    with open(f"{APP}/aspa_results.json", "w") as f:
        json.dump(aspa_results, f, indent=2)

    # Step 4: Composite verdicts
    print("Step 4: Computing composite route verdicts...")

    # Check if any route's path traverses an AS whose ASPA is revoked/tampered
    def route_involves_revoked(route):
        """Check if the route's prefix is only covered by revoked/tampered ROAs,
        or if key ASes in the path have revoked/tampered ASPAs."""
        # Check ROA coverage from revoked entities
        prefix = route["prefix"]
        origin = route["origin_as"]
        for entry in roa_manifest:
            if entry["roa_id"] not in trusted_roa_ids:
                roa_data_path = os.path.join(APP, entry["data_file"])
                try:
                    roa_data = load_json(roa_data_path)
                    roa_net = ipaddress.ip_network(roa_data["prefix"])
                    route_net = ipaddress.ip_network(prefix)
                    if (roa_net.supernet_of(route_net) or roa_net == route_net):
                        signer = entry["signing_entity"]
                        if signer in revoked_entities:
                            return True
                except:
                    pass
        return False

    verdicts = []
    verdicts_map = {}
    for i, route in enumerate(routes):
        rov = rov_results[i]
        aspa = aspa_results[i]
        involves_revoked = route_involves_revoked(route)
        risk = compute_risk_score(
            rov["rov_status"], aspa["aspa_status"],
            rov["unsafe_maxlength"], involves_revoked
        )
        verdict = compute_verdict(rov["rov_status"], aspa["aspa_status"], risk)
        entry = {
            "route_id": route["route_id"],
            "rov_status": rov["rov_status"],
            "aspa_status": aspa["aspa_status"],
            "unsafe_maxlength": rov["unsafe_maxlength"],
            "risk_score": risk,
            "verdict": verdict
        }
        verdicts.append(entry)
        verdicts_map[route["route_id"]] = entry

    with open(f"{APP}/route_verdicts.json", "w") as f:
        json.dump(verdicts, f, indent=2)

    # Step 5: Build SQLite database
    print("Step 5: Building routing security database...")
    db_path = f"{APP}/route_security.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE trusted_objects (
        id TEXT PRIMARY KEY,
        type TEXT,
        trusted INTEGER,
        reason TEXT
    )""")
    for t in all_trust:
        obj_type = "ROA" if t["id"].startswith("ROA") else "ASPA"
        c.execute("INSERT INTO trusted_objects VALUES (?, ?, ?, ?)",
                  (t["id"], obj_type, 1 if t["trusted"] else 0, t["reason"]))

    c.execute("""CREATE TABLE route_verdicts (
        route_id TEXT PRIMARY KEY,
        prefix TEXT,
        origin_as INTEGER,
        relationship TEXT,
        rov_status TEXT,
        aspa_status TEXT,
        unsafe_maxlength INTEGER,
        risk_score INTEGER,
        verdict TEXT
    )""")
    for v, r in zip(verdicts, routes):
        c.execute("INSERT INTO route_verdicts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (v["route_id"], r["prefix"], r["origin_as"], r["relationship"],
                   v["rov_status"], v["aspa_status"],
                   1 if v["unsafe_maxlength"] else 0, v["risk_score"], v["verdict"]))

    conn.commit()
    conn.close()

    # Step 6: Evaluate attacks
    print("Step 6: Evaluating attack scenarios...")
    attack_eval = evaluate_attacks(attack_scenarios, verdicts_map)
    with open(f"{APP}/policy_evaluation.json", "w") as f:
        json.dump(attack_eval, f, indent=2)

    # Summary
    accept = sum(1 for v in verdicts if v["verdict"] == "ACCEPT")
    reject = sum(1 for v in verdicts if v["verdict"] == "REJECT")
    review = sum(1 for v in verdicts if v["verdict"] == "REVIEW")
    print(f"\nResults: {accept} ACCEPT, {reject} REJECT, {review} REVIEW")

    detected = sum(1 for a in attack_eval if a["detected"])
    mitigated = sum(1 for a in attack_eval if a["mitigated"])
    print(f"Attacks: {detected}/8 detected, {mitigated}/8 mitigated")


if __name__ == "__main__":
    main()
