#!/usr/bin/env python3
"""
NVD Vulnerability Assessment Engine - Solution

Implements:
1. CVSS v3.1 base score calculation from vector strings
2. CPE version-range matching with alphanumeric suffix support
3. Full assessment pipeline matching CVEs against software inventory
"""

import json
import math
import re
import sys

# ─── CVSS v3.1 Calculator ───────────────────────────────────────────

CVSS_AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
CVSS_AC = {"L": 0.77, "H": 0.44}
CVSS_PR_UNCHANGED = {"N": 0.85, "L": 0.62, "H": 0.27}
CVSS_PR_CHANGED = {"N": 0.85, "L": 0.68, "H": 0.50}
CVSS_UI = {"N": 0.85, "R": 0.62}
CVSS_CIA = {"H": 0.56, "L": 0.22, "N": 0.0}


def roundup(x):
    """CVSS v3.1 Roundup function matching the NIST JavaScript reference."""
    int_input = int(math.floor(x * 100000 + 0.5))
    if int_input % 10000 == 0:
        return int_input / 100000.0
    else:
        return (int(math.floor(int_input / 10000)) + 1) / 10.0


def compute_cvss31_score(vector_string):
    """Compute CVSS v3.1 base score from a vector string."""
    parts = vector_string.split("/")
    metrics = {}
    for part in parts:
        if ":" in part:
            key, val = part.split(":", 1)
            metrics[key] = val

    scope_changed = metrics["S"] == "C"

    av = CVSS_AV[metrics["AV"]]
    ac = CVSS_AC[metrics["AC"]]
    pr = (CVSS_PR_CHANGED if scope_changed else CVSS_PR_UNCHANGED)[metrics["PR"]]
    ui = CVSS_UI[metrics["UI"]]
    c = CVSS_CIA[metrics["C"]]
    i = CVSS_CIA[metrics["I"]]
    a = CVSS_CIA[metrics["A"]]

    iss = 1.0 - ((1.0 - c) * (1.0 - i) * (1.0 - a))

    if scope_changed:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    else:
        impact = 6.42 * iss

    exploitability = 8.22 * av * ac * pr * ui

    if impact <= 0:
        return 0.0

    if scope_changed:
        base = roundup(min(1.08 * (impact + exploitability), 10.0))
    else:
        base = roundup(min(impact + exploitability, 10.0))

    return base


def severity_label(score):
    if score >= 9.0:
        return "CRITICAL"
    elif score >= 7.0:
        return "HIGH"
    elif score >= 4.0:
        return "MEDIUM"
    elif score >= 0.1:
        return "LOW"
    else:
        return "NONE"


# ─── Version Comparison ─────────────────────────────────────────────

def parse_version_component(comp):
    """Split a version component into (numeric_prefix, alpha_suffix).
    E.g., '1c' -> (1, 'c'), '14' -> (14, ''), 'beta9' -> (None, 'beta9')
    """
    m = re.match(r'^(\d+)(.*)', comp)
    if m:
        return (int(m.group(1)), m.group(2))
    return (None, comp)


def compare_components(a, b):
    """Compare two version components."""
    na, sa = parse_version_component(a)
    nb, sb = parse_version_component(b)

    if na is not None and nb is not None:
        if na != nb:
            return -1 if na < nb else 1
        # numeric parts equal, compare suffix
        if sa == sb:
            return 0
        return -1 if sa < sb else 1
    elif na is not None:
        return 1  # numeric > non-numeric
    elif nb is not None:
        return -1
    else:
        if a == b:
            return 0
        return -1 if a < b else 1


def version_compare(v1, v2):
    """Compare two version strings. Returns <0, 0, or >0."""
    parts1 = v1.split(".")
    parts2 = v2.split(".")

    max_len = max(len(parts1), len(parts2))
    while len(parts1) < max_len:
        parts1.append("0")
    while len(parts2) < max_len:
        parts2.append("0")

    for a, b in zip(parts1, parts2):
        cmp = compare_components(a, b)
        if cmp != 0:
            return cmp
    return 0


# ─── CPE Matching ───────────────────────────────────────────────────

def parse_cpe(cpe_string):
    """Extract vendor and product from a CPE 2.3 string."""
    parts = cpe_string.split(":")
    # cpe:2.3:part:vendor:product:version:...
    if len(parts) >= 5:
        return parts[3], parts[4]
    return None, None


def cpe_match_item(cpe_match, vendor, product, version):
    """Check if an inventory item matches a CPE match criterion."""
    if not cpe_match.get("vulnerable", False):
        return False

    cpe_vendor, cpe_product = parse_cpe(cpe_match["criteria"])
    if cpe_vendor is None:
        return False

    if cpe_vendor != vendor or cpe_product != product:
        return False

    # Check version ranges
    start_inc = cpe_match.get("versionStartIncluding")
    start_exc = cpe_match.get("versionStartExcluding")
    end_inc = cpe_match.get("versionEndIncluding")
    end_exc = cpe_match.get("versionEndExcluding")

    if start_inc is not None:
        if version_compare(version, start_inc) < 0:
            return False

    if start_exc is not None:
        if version_compare(version, start_exc) <= 0:
            return False

    if end_inc is not None:
        if version_compare(version, end_inc) > 0:
            return False

    if end_exc is not None:
        if version_compare(version, end_exc) >= 0:
            return False

    return True


def evaluate_node(node, inventory):
    """Evaluate a configuration node against the full inventory.
    Returns the set of (vendor, product, version) tuples that match
    as vulnerable.
    """
    operator = node.get("operator", "OR")
    negate = node.get("negate", False)
    matches = set()

    for item in inventory:
        v, p, ver = item["vendor"], item["product"], item["version"]
        item_matches = False
        for cpe_match in node.get("cpeMatch", []):
            if cpe_match_item(cpe_match, v, p, ver):
                item_matches = True
                break

        if operator == "OR" and item_matches:
            if cpe_match.get("vulnerable", False):
                matches.add((v, p, ver))

    if negate:
        all_items = {(i["vendor"], i["product"], i["version"]) for i in inventory}
        matches = all_items - matches

    return matches


def evaluate_config(config, inventory):
    """Evaluate a top-level configuration against inventory.
    Returns set of (vendor, product, version) tuples that are vulnerable.
    """
    nodes = config.get("nodes", [])
    if not nodes:
        return set()

    # Simple case: single node with OR
    vulnerable = set()
    for node in nodes:
        node_matches = evaluate_node(node, inventory)
        vulnerable.update(node_matches)

    return vulnerable


def get_affected_items(cve, inventory):
    """Get all inventory items affected by a CVE."""
    affected = set()
    for config in cve.get("configurations", []):
        affected.update(evaluate_config(config, inventory))
    return affected


# ─── Main Pipeline ──────────────────────────────────────────────────

def main():
    # Load data
    with open("/app/nvd_dataset.json") as f:
        nvd_data = json.load(f)

    with open("/app/inventory.json") as f:
        inventory = json.load(f)

    # Process each CVE
    cve_info = {}
    for vuln in nvd_data["vulnerabilities"]:
        cve = vuln["cve"]
        cve_id = cve["id"]

        # Extract vector string
        vector = None
        for metric in cve.get("metrics", {}).get("cvssMetricV31", []):
            vector = metric["cvssData"]["vectorString"]
            break

        if vector is None:
            continue

        # Compute CVSS score
        score = compute_cvss31_score(vector)
        sev = severity_label(score)

        # Extract CWEs
        cwes = []
        for weakness in cve.get("weaknesses", []):
            for desc in weakness.get("description", []):
                if desc.get("lang") == "en" and desc["value"].startswith("CWE-"):
                    cwes.append(desc["value"])

        # Find affected inventory items
        affected = get_affected_items(cve, inventory)

        cve_info[cve_id] = {
            "score": score,
            "severity": sev,
            "cwes": cwes,
            "vector": vector,
            "affected": affected,
        }

    # Build assessment
    assessed_items = []
    severity_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    total_matches = 0
    affected_count = 0

    for item in inventory:
        key = (item["vendor"], item["product"], item["version"])
        matching_cves = []

        for cve_id, info in cve_info.items():
            if key in info["affected"]:
                matching_cves.append({
                    "id": cve_id,
                    "cvss_v3_1_score": info["score"],
                    "severity": info["severity"],
                    "cwes": info["cwes"],
                })
                severity_counts[info["severity"]] += 1
                total_matches += 1

        matching_cves.sort(key=lambda c: c["id"])

        risk_score = max((c["cvss_v3_1_score"] for c in matching_cves), default=0.0)

        if matching_cves:
            affected_count += 1

        assessed_items.append({
            "vendor": item["vendor"],
            "product": item["product"],
            "version": item["version"],
            "cves": matching_cves,
            "risk_score": risk_score,
        })

    assessment = {
        "assessed_items": assessed_items,
        "statistics": {
            "total_items": len(inventory),
            "affected_items": affected_count,
            "unaffected_items": len(inventory) - affected_count,
            "total_cve_matches": total_matches,
            "by_severity": severity_counts,
        },
    }

    # Write assessment
    with open("/app/assessment.json", "w") as f:
        json.dump(assessment, f, indent=2)

    # Write standalone CVSS calculator
    calc_script = '''#!/usr/bin/env python3
"""Standalone CVSS v3.1 Base Score Calculator."""
import math
import sys

AV = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
AC = {"L": 0.77, "H": 0.44}
PR_U = {"N": 0.85, "L": 0.62, "H": 0.27}
PR_C = {"N": 0.85, "L": 0.68, "H": 0.50}
UI = {"N": 0.85, "R": 0.62}
CIA = {"H": 0.56, "L": 0.22, "N": 0.0}

def roundup(x):
    int_input = int(math.floor(x * 100000 + 0.5))
    if int_input % 10000 == 0:
        return int_input / 100000.0
    else:
        return (int(math.floor(int_input / 10000)) + 1) / 10.0

def compute(vector):
    metrics = {}
    for part in vector.split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            metrics[k] = v

    sc = metrics["S"] == "C"
    av = AV[metrics["AV"]]
    ac = AC[metrics["AC"]]
    pr = (PR_C if sc else PR_U)[metrics["PR"]]
    ui = UI[metrics["UI"]]
    c = CIA[metrics["C"]]
    i = CIA[metrics["I"]]
    a = CIA[metrics["A"]]

    iss = 1.0 - ((1.0 - c) * (1.0 - i) * (1.0 - a))
    if sc:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)
    else:
        impact = 6.42 * iss

    exploitability = 8.22 * av * ac * pr * ui

    if impact <= 0:
        return 0.0
    if sc:
        return roundup(min(1.08 * (impact + exploitability), 10.0))
    else:
        return roundup(min(impact + exploitability, 10.0))

if __name__ == "__main__":
    print(compute(sys.argv[1]))
'''

    with open("/app/cvss_calc.py", "w") as f:
        f.write(calc_script)

    print(f"Assessment complete: {affected_count} affected items, "
          f"{total_matches} CVE matches")


if __name__ == "__main__":
    main()
