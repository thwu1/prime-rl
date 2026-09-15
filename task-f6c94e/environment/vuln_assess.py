#!/usr/bin/env python3
"""
Vulnerability Assessment Pipeline v2.3.1
Reads CVE data from vulndb.sqlite, matches against software inventory,
incorporates active threat intelligence from traffic analysis,
and produces prioritized remediation reports with CVSS v3.1 Environmental scoring.
"""

import sqlite3
import json
import math
import os
import sys

AV_VALUES = {"NETWORK": 0.85, "ADJACENT_NETWORK": 0.62, "LOCAL": 0.55, "PHYSICAL": 0.20}
AC_VALUES = {"LOW": 0.77, "HIGH": 0.44}
PR_VALUES_UNCHANGED = {"NONE": 0.85, "LOW": 0.62, "HIGH": 0.27}
PR_VALUES_CHANGED = {"NONE": 0.85, "LOW": 0.68, "HIGH": 0.50}
UI_VALUES = {"NONE": 0.85, "REQUIRED": 0.62}
CIA_VALUES = {"HIGH": 0.56, "LOW": 0.22, "NONE": 0.0}
SR_VALUES = {"NOT_DEFINED": 1.0, "LOW": 0.5, "MEDIUM": 1.0, "HIGH": 1.5}
E_VALUES = {"NOT_DEFINED": 1.0, "UNPROVEN": 0.91, "PROOF_OF_CONCEPT": 0.94,
            "FUNCTIONAL": 0.97, "HIGH": 1.0}
RL_VALUES = {"NOT_DEFINED": 1.0, "OFFICIAL_FIX": 0.95, "TEMPORARY_FIX": 0.96,
             "WORKAROUND": 0.97, "UNAVAILABLE": 1.0}
RC_VALUES = {"NOT_DEFINED": 1.0, "UNKNOWN": 0.92, "REASONABLE": 0.96, "CONFIRMED": 1.0}

AV_MAP = {"N": "NETWORK", "A": "ADJACENT_NETWORK", "L": "LOCAL", "P": "PHYSICAL"}
AC_MAP = {"L": "LOW", "H": "HIGH"}
PR_MAP = {"N": "NONE", "L": "LOW", "H": "HIGH"}
UI_MAP = {"N": "NONE", "R": "REQUIRED"}
S_MAP = {"U": "UNCHANGED", "C": "CHANGED"}
CIA_MAP = {"H": "HIGH", "L": "LOW", "N": "NONE"}


def roundup(x):
    """CVSS v3.1 Roundup function per specification."""
    return math.ceil(x * 10) / 10.0


def parse_vector(vector_string):
    """Parse CVSS v3.1 vector string into metric abbreviation dict."""
    prefix = "CVSS:3.1/"
    if vector_string.startswith(prefix):
        vector_string = vector_string[len(prefix):]
    metrics = {}
    for part in vector_string.split("/"):
        key, value = part.split(":")
        metrics[key] = value
    return metrics


def compute_base_score(vector_string):
    """Compute CVSS v3.1 base score from vector string."""
    m = parse_vector(vector_string)

    av = AV_MAP[m["AV"]]
    ac = AC_MAP[m["AC"]]
    pr = PR_MAP[m["PR"]]
    ui = UI_MAP[m["UI"]]
    s = S_MAP[m["S"]]
    c = CIA_MAP[m["C"]]
    i = CIA_MAP[m["I"]]
    a = CIA_MAP[m["A"]]

    iss = 1 - ((1 - CIA_VALUES[c]) * (1 - CIA_VALUES[i]) * (1 - CIA_VALUES[a]))

    if s == "UNCHANGED":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)

    pr_values = PR_VALUES_CHANGED if s == "CHANGED" else PR_VALUES_UNCHANGED
    exploitability = 8.22 * AV_VALUES[av] * AC_VALUES[ac] * pr_values[pr] * UI_VALUES[ui]

    if impact <= 0:
        return 0.0
    elif s == "UNCHANGED":
        return roundup(min(impact + exploitability, 10))
    else:
        return roundup(min(1.08 * (impact + exploitability), 10))


def compute_environmental_score(vector_string, env_config):
    """Compute CVSS v3.1 Environmental score with modified metrics."""
    m = parse_vector(vector_string)

    base_av = AV_MAP[m["AV"]]
    base_ac = AC_MAP[m["AC"]]
    base_pr = PR_MAP[m["PR"]]
    base_ui = UI_MAP[m["UI"]]
    base_s = S_MAP[m["S"]]
    base_c = CIA_MAP[m["C"]]
    base_i = CIA_MAP[m["I"]]
    base_a = CIA_MAP[m["A"]]

    def resolve(mod_key, base_val):
        v = env_config.get(mod_key, "NOT_DEFINED")
        return base_val if v == "NOT_DEFINED" else v

    eff_av = resolve("modified_attack_vector", base_av)
    eff_ac = resolve("modified_attack_complexity", base_ac)
    eff_pr = resolve("modified_privileges_required", base_pr)
    eff_ui = resolve("modified_user_interaction", base_ui)
    eff_s = resolve("modified_scope", base_s)
    eff_c = resolve("modified_confidentiality", base_c)
    eff_i = resolve("modified_integrity", base_i)
    eff_a = resolve("modified_availability", base_a)

    cr = SR_VALUES[env_config.get("confidentiality_requirement", "NOT_DEFINED")]
    ir = SR_VALUES[env_config.get("integrity_requirement", "NOT_DEFINED")]
    ar = SR_VALUES[env_config.get("availability_requirement", "NOT_DEFINED")]

    e = E_VALUES[env_config.get("exploit_code_maturity", "NOT_DEFINED")]
    rl = RL_VALUES[env_config.get("remediation_level", "NOT_DEFINED")]
    rc = RC_VALUES[env_config.get("report_confidence", "NOT_DEFINED")]

    mc_val = CIA_VALUES[eff_c]
    mi_val = CIA_VALUES[eff_i]
    ma_val = CIA_VALUES[eff_a]

    miss = min(
        1 - ((1 - mc_val * cr) * (1 - mi_val * ir) * (1 - ma_val * ar)),
        0.915,
    )

    if eff_s == "UNCHANGED":
        mod_impact = 6.42 * miss
    else:
        mod_impact = 7.52 * (miss - 0.029) - 3.25 * ((miss - 0.02) ** 15)

    pr_values = PR_VALUES_CHANGED if eff_s == "CHANGED" else PR_VALUES_UNCHANGED
    mod_exploitability = (
        8.22 * AV_VALUES[eff_av] * AC_VALUES[eff_ac]
        * pr_values[eff_pr] * UI_VALUES[eff_ui]
    )

    if mod_impact <= 0:
        return 0.0
    elif eff_s == "UNCHANGED":
        return roundup(roundup(min(mod_impact + mod_exploitability, 10)) * e * rl * rc)
    else:
        return roundup(
            roundup(min(1.08 * (mod_impact + mod_exploitability), 10)) * e * rl * rc
        )


def compare_versions(v1, v2):
    """Compare version strings segment by segment."""
    parts1 = v1.split(".")
    parts2 = v2.split(".")
    max_len = max(len(parts1), len(parts2))
    for idx in range(max_len):
        p1 = parts1[idx] if idx < len(parts1) else ""
        p2 = parts2[idx] if idx < len(parts2) else ""
        if p1.isdigit() and p2.isdigit():
            n1, n2 = int(p1), int(p2)
            if n1 < n2:
                return -1
            if n1 > n2:
                return 1
        else:
            if p1 < p2:
                return -1
            if p1 > p2:
                return 1
    return 0


def parse_cpe(cpe_uri):
    """Parse CPE 2.3 URI into components."""
    parts = cpe_uri.split(":")
    return {"part": parts[2], "vendor": parts[3], "product": parts[4], "version": parts[5]}


def match_cpe(inv_cpe, inv_version, criteria, vsi, vse, vei, vee):
    """Check if an inventory item matches a CPE criteria with version bounds."""
    inv = parse_cpe(inv_cpe)
    crit = parse_cpe(criteria)

    for field in ["part", "vendor", "product"]:
        if crit[field] != "*" and crit[field] != inv[field]:
            return False

    if crit["version"] != "*":
        return inv["version"] == crit["version"]

    version = inv_version
    if vsi and compare_versions(version, vsi) < 0:
        return False
    if vse and compare_versions(version, vse) <= 0:
        return False
    if vei and compare_versions(version, vei) > 0:
        return False
    if vee and compare_versions(version, vee) >= 0:
        return False
    return True


def main():
    db = sqlite3.connect('/app/vulndb.sqlite')

    with open('/app/inventory.json') as f:
        inventory = json.load(f)
    with open('/app/env_config.json') as f:
        env_config = json.load(f)

    # Step 1: Compute base scores
    score_validation = {}
    vector_map = {}
    for cve_id, vector in db.execute('SELECT cve_id, cvss_vector FROM cves ORDER BY cve_id'):
        vector_map[cve_id] = vector
        score_validation[cve_id] = compute_base_score(vector)

    with open('/app/score_validation.json', 'w') as f:
        json.dump(score_validation, f, indent=2)
    print(f"[+] Base scores computed for {len(score_validation)} CVEs")

    # Step 2: Match CPEs against inventory
    affected_inventory = {}
    for (cve_id,) in db.execute('SELECT cve_id FROM cves ORDER BY cve_id'):
        matched = set()
        rows = db.execute('''
            SELECT cm.criteria, cm.vulnerable,
                   cm.version_start_including, cm.version_start_excluding,
                   cm.version_end_including, cm.version_end_excluding
            FROM cpe_matches cm
            JOIN cpe_configurations cc ON cm.config_id = cc.id
            WHERE cc.cve_id = ?
        ''', (cve_id,))
        for criteria, vulnerable, vsi, vse, vei, vee in rows:
            if not vulnerable:
                continue
            for item in inventory:
                if match_cpe(item['cpe_uri'], item['version'], criteria, vsi, vse, vei, vee):
                    matched.add(item['id'])
        if matched:
            affected_inventory[cve_id] = sorted(list(matched))

    with open('/app/affected_inventory.json', 'w') as f:
        json.dump(affected_inventory, f, indent=2)
    print(f"[+] CPE matching: {len(affected_inventory)} CVEs affect inventory")

    # Step 3: Read active threat intelligence from traffic analysis
    active_cves = set()
    try:
        with open('/app/active_threats.json') as f:
            threats = json.load(f)
        for entry in threats.get('active_exploits', []):
            active_cves.add(entry['cve_id'])
        print(f"[+] Active threat intel: {len(active_cves)} CVEs with observed exploitation")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print("[!] No active threat data available")

    # Step 4: Environmental scores and remediation report
    report = []
    for cve_id, items in affected_inventory.items():
        vector = vector_map[cve_id]
        base_score = score_validation[cve_id]
        env_score = compute_environmental_score(vector, env_config)
        report.append({
            "cve_id": cve_id,
            "base_score": base_score,
            "environmental_score": env_score,
            "actively_exploited": cve_id in active_cves,
            "affected_items": items,
        })

    report.sort(key=lambda x: (
        -int(x["actively_exploited"]),
        -x["environmental_score"],
        -x["base_score"],
        x["cve_id"]
    ))

    with open('/app/remediation_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f"[+] Remediation report: {len(report)} entries, ranked by priority")

    db.close()
    print("[+] Assessment complete")


if __name__ == "__main__":
    main()
