#!/usr/bin/env python3
"""
Solution: NVD Mirror Forensic Audit & Threat Prioritization

Performs HMAC tamper detection, CVSS v3.1 recomputation, CPE/CWE
cross-validation against canonical data, EPSS/KEV threat correlation,
and generates a structured audit report plus CPE Dictionary XML.
"""


import csv
import hashlib
import hmac as hmac_mod
import json
import math
import os
import sqlite3
import xml.etree.ElementTree as ET


DB_PATH = "/app/data/nvd_mirror.db"
CANONICAL_PATH = "/app/data/canonical/nvd_snapshot.json"
INVENTORY_PATH = "/app/data/inventory.json"
EPSS_PATH = "/app/data/feeds/epss_scores.csv"
KEV_PATH = "/app/data/feeds/kev_catalog.json"
HMAC_KEY_PATH = "/app/data/.hmac_key"
REPORT_PATH = "/app/output/audit_report.json"
XML_PATH = "/app/output/cpe_dictionary.xml"


# ===================== CVSS v3.1 Computation =====================

def roundup(x):
    return math.ceil(x * 10) / 10.0


def compute_cvss31(vector_string):
    parts = vector_string.replace("CVSS:3.1/", "").split("/")
    m = {}
    for part in parts:
        k, v = part.split(":")
        m[k] = v

    av_vals = {"N": 0.85, "A": 0.62, "L": 0.55, "P": 0.20}
    ac_vals = {"L": 0.77, "H": 0.44}
    ui_vals = {"N": 0.85, "R": 0.62}
    cia_vals = {"H": 0.56, "L": 0.22, "N": 0.0}

    scope = m["S"]
    pr_vals = ({"N": 0.85, "L": 0.68, "H": 0.50} if scope == "C"
               else {"N": 0.85, "L": 0.62, "H": 0.27})

    av = av_vals[m["AV"]]
    ac = ac_vals[m["AC"]]
    pr = pr_vals[m["PR"]]
    ui = ui_vals[m["UI"]]
    c_val = cia_vals[m["C"]]
    i_val = cia_vals[m["I"]]
    a_val = cia_vals[m["A"]]

    iss = 1.0 - ((1.0 - c_val) * (1.0 - i_val) * (1.0 - a_val))

    if scope == "U":
        impact = 6.42 * iss
    else:
        impact = 7.52 * (iss - 0.029) - 3.25 * ((iss - 0.02) ** 15)

    exploitability = 8.22 * av * ac * pr * ui

    if impact <= 0:
        return 0.0

    if scope == "U":
        return roundup(min(impact + exploitability, 10.0))
    else:
        return roundup(min(1.08 * (impact + exploitability), 10.0))


# ===================== HMAC Verification =====================

def canonical_json(obj):
    return json.dumps(obj, separators=(',', ':'), sort_keys=True)


def compute_record_hmac(key, cve_id, cvss_vector, base_score, cwe_id, cpe_config_json):
    msg = f"{cve_id}|{cvss_vector}|{base_score:.1f}|{cwe_id}|{cpe_config_json}"
    return hmac_mod.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


# ===================== Version Comparison =====================

def parse_version(v):
    parts = []
    for p in v.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(p)
    return tuple(parts)


def version_cmp(a, b):
    ta, tb = parse_version(a), parse_version(b)
    if ta < tb:
        return -1
    elif ta > tb:
        return 1
    return 0


# ===================== CPE Matching =====================

def parse_cpe(criteria):
    parts = criteria.split(":")
    if len(parts) >= 5:
        return parts[2], parts[3], parts[4]  # part, vendor, product
    return None, None, None


def version_in_range(version, match):
    si = match.get("versionStartIncluding")
    se = match.get("versionStartExcluding")
    ei = match.get("versionEndIncluding")
    ee = match.get("versionEndExcluding")

    if si and version_cmp(version, si) < 0:
        return False
    if se and version_cmp(version, se) <= 0:
        return False
    if ei and version_cmp(version, ei) > 0:
        return False
    if ee and version_cmp(version, ee) >= 0:
        return False
    return True


def cve_affects_item(config_list, item):
    vendor = item["vendor"]
    product = item["product"]
    version = item["version"]

    for config in config_list:
        config_op = config.get("operator")
        nodes = config.get("nodes", [])

        if config_op == "AND":
            all_match = True
            for node in nodes:
                node_matched = False
                for cm in node.get("cpeMatch", []):
                    cpe_part, cpe_vendor, cpe_product = parse_cpe(cm["criteria"])
                    if cpe_vendor == vendor and cpe_product == product:
                        if cm.get("vulnerable", True):
                            if version_in_range(version, cm):
                                node_matched = True
                                break
                        else:
                            node_matched = True
                            break
                if not node_matched:
                    all_match = False
                    break
            if all_match:
                return True
        else:
            for node in nodes:
                negate = node.get("negate", False)
                matched = False
                for cm in node.get("cpeMatch", []):
                    if not cm.get("vulnerable", True):
                        continue
                    _, cpe_vendor, cpe_product = parse_cpe(cm["criteria"])
                    if cpe_vendor == vendor and cpe_product == product:
                        if version_in_range(version, cm):
                            matched = True
                            break
                result = matched != negate
                if result:
                    return True
    return False


def get_cpe_part_type(config_list, vendor, product):
    """Extract CPE part type (a/o/h) from matching CPE criteria."""
    for config in config_list:
        for node in config.get("nodes", []):
            for cm in node.get("cpeMatch", []):
                if not cm.get("vulnerable", True):
                    continue
                cpe_part, cpe_vendor, cpe_product = parse_cpe(cm["criteria"])
                if cpe_vendor == vendor and cpe_product == product:
                    return cpe_part
    return "a"


# ===================== Data Loading =====================

def load_canonical():
    with open(CANONICAL_PATH) as f:
        data = json.load(f)
    result = {}
    for vuln in data["vulnerabilities"]:
        cve = vuln["cve"]
        cve_id = cve["id"]
        cvss = cve["metrics"]["cvssMetricV31"][0]["cvssData"]
        cwe_list = cve.get("weaknesses", [])
        cwe = cwe_list[0]["description"][0]["value"] if cwe_list else None
        configs = cve.get("configurations", [])
        result[cve_id] = {
            "vector": cvss["vectorString"],
            "base_score": cvss["baseScore"],
            "cwe": cwe,
            "configurations": configs,
        }
    return result


def load_epss():
    epss = {}
    with open(EPSS_PATH) as f:
        for line in f:
            if line.startswith("#"):
                continue
            break
        reader = csv.DictReader(f, fieldnames=["cve", "epss", "percentile"])
        # The header line was already consumed; re-read
    with open(EPSS_PATH) as f:
        lines = [l for l in f if not l.startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        epss[row["cve"]] = float(row["epss"])
    return epss


def load_kev():
    with open(KEV_PATH) as f:
        data = json.load(f)
    return {v["cveID"] for v in data["vulnerabilities"]}


# ===================== CPE Config Comparison =====================

def normalize_config(config):
    """Normalize a CPE config for comparison."""
    return canonical_json(config)


def cpe_configs_match(db_config_json, canonical_configs):
    """Compare DB CPE config JSON against canonical configs."""
    db_configs = json.loads(db_config_json)
    return normalize_config(db_configs) == normalize_config(canonical_configs)


# ===================== XML Generation =====================

def generate_cpe_xml(affected_items):
    """Generate CPE Dictionary 2.3 XML for affected products."""
    CPE_NS = "http://cpe.mitre.org/dictionary/2.0"
    CPE23_NS = "http://scap.nist.gov/schema/cpe-extension/2.3"

    ET.register_namespace('', CPE_NS)
    ET.register_namespace('cpe-23', CPE23_NS)

    root = ET.Element(f'{{{CPE_NS}}}cpe-list')

    for item in affected_items:
        part = item["cpe_part"]
        vendor = item["vendor"]
        product = item["product"]
        version = item["version"]

        cpe22_uri = f"cpe:/{part}:{vendor}:{product}:{version}"
        cpe23_name = f"cpe:2.3:{part}:{vendor}:{product}:{version}:*:*:*:*:*:*:*"

        cpe_item = ET.SubElement(root, f'{{{CPE_NS}}}cpe-item')
        cpe_item.set('name', cpe22_uri)

        title = ET.SubElement(cpe_item, f'{{{CPE_NS}}}title')
        title.set('{http://www.w3.org/XML/1998/namespace}lang', 'en')
        title.text = f"{vendor} {product} {version}"

        cpe23_item = ET.SubElement(cpe_item, f'{{{CPE23_NS}}}cpe23-item')
        cpe23_item.set('name', cpe23_name)

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    os.makedirs(os.path.dirname(XML_PATH), exist_ok=True)
    tree.write(XML_PATH, encoding="unicode", xml_declaration=True)


# ===================== Main =====================

def main():
    # Load HMAC key
    hmac_key = open(HMAC_KEY_PATH).read().strip()

    # Connect to DB and read all records
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM cve_records")
    db_records = {row["cve_id"]: dict(row) for row in c.fetchall()}
    conn.close()

    # Load canonical data
    canonical = load_canonical()

    # Load threat intelligence feeds
    epss_scores = load_epss()
    kev_set = load_kev()

    # Load inventory
    with open(INVENTORY_PATH) as f:
        inventory = json.load(f)

    # ===== 1. HMAC tamper detection =====
    tampered_records = []
    for cve_id in sorted(db_records.keys()):
        rec = db_records[cve_id]
        cpe_json_raw = rec["cpe_config"]
        # Re-canonicalize for consistent HMAC computation
        cpe_obj = json.loads(cpe_json_raw)
        cpe_json_canonical = canonical_json(cpe_obj)

        computed_hmac = compute_record_hmac(
            hmac_key, cve_id, rec["cvss_vector"],
            rec["cvss_base_score"], rec["cwe_id"], cpe_json_canonical
        )

        if computed_hmac != rec["hmac_sha256"]:
            tampered_records.append({
                "cve_id": cve_id,
                "hmac_stored": rec["hmac_sha256"],
                "hmac_computed": computed_hmac,
            })

    # ===== 2. CVSS score anomalies =====
    score_anomalies = []
    computed_scores = {}
    for cve_id in sorted(db_records.keys()):
        rec = db_records[cve_id]
        computed = compute_cvss31(rec["cvss_vector"])
        computed_scores[cve_id] = computed
        if abs(computed - rec["cvss_base_score"]) > 0.01:
            score_anomalies.append({
                "cve_id": cve_id,
                "stored_score": rec["cvss_base_score"],
                "computed_score": computed,
                "vector_string": rec["cvss_vector"],
            })

    # ===== 3. CPE discrepancies =====
    cpe_discrepancies = []
    for cve_id in sorted(canonical.keys()):
        canon_configs = canonical[cve_id]["configurations"]
        db_cpe_json = db_records[cve_id]["cpe_config"]
        if not cpe_configs_match(db_cpe_json, canon_configs):
            cpe_discrepancies.append({"cve_id": cve_id})

    # ===== 4. CWE errors =====
    cwe_errors = []
    for cve_id in sorted(canonical.keys()):
        canon_cwe = canonical[cve_id]["cwe"]
        db_cwe = db_records[cve_id]["cwe_id"]
        if canon_cwe and db_cwe and canon_cwe != db_cwe:
            cwe_errors.append({
                "cve_id": cve_id,
                "stored_cwe": db_cwe,
                "correct_cwe": canon_cwe,
            })

    # ===== 5. Inventory matching & threat prioritization =====
    threat_priority = []
    for item in inventory:
        matched_cves = []
        max_cvss = 0.0
        cpe_part = "a"

        for cve_id, canon in canonical.items():
            if cve_affects_item(canon["configurations"], item):
                score = computed_scores.get(cve_id, canon["base_score"])
                matched_cves.append(cve_id)
                if score > max_cvss:
                    max_cvss = score
                    cpe_part = get_cpe_part_type(
                        canon["configurations"], item["vendor"], item["product"]
                    )

        if matched_cves:
            matched_cves.sort()
            max_epss = max(epss_scores.get(cve, 0.0) for cve in matched_cves)
            in_kev = any(cve in kev_set for cve in matched_cves)
            kev_mult = 2.0 if in_kev else 1.0
            priority = round(max_cvss * max_epss * kev_mult, 4)

            threat_priority.append({
                "vendor": item["vendor"],
                "product": item["product"],
                "version": item["version"],
                "matched_cves": matched_cves,
                "cvss_score": max_cvss,
                "epss_score": max_epss,
                "in_kev": in_kev,
                "priority_score": priority,
                "cpe_part": cpe_part,
            })

    # Sort by priority_score descending
    threat_priority.sort(key=lambda x: -x["priority_score"])

    # ===== 6. Generate CPE Dictionary XML =====
    generate_cpe_xml(threat_priority)

    # ===== 7. Build report =====
    # Remove cpe_part from threat_priority entries (internal field)
    report_priority = []
    for tp in threat_priority:
        entry = {k: v for k, v in tp.items() if k != "cpe_part"}
        report_priority.append(entry)

    risk_score = sum(tp["cvss_score"] for tp in threat_priority)

    report = {
        "tampered_records": tampered_records,
        "score_anomalies": score_anomalies,
        "cpe_discrepancies": cpe_discrepancies,
        "cwe_errors": cwe_errors,
        "threat_priority": report_priority,
        "summary": {
            "total_cves_audited": len(canonical),
            "tampered_count": len(tampered_records),
            "score_anomalies_found": len(score_anomalies),
            "cpe_discrepancies_found": len(cpe_discrepancies),
            "cwe_errors_found": len(cwe_errors),
            "inventory_items_total": len(inventory),
            "inventory_items_vulnerable": len(threat_priority),
            "risk_score": round(risk_score, 1),
        },
    }

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Audit report: {REPORT_PATH}")
    print(f"CPE Dictionary XML: {XML_PATH}")
    print(f"Tampered records: {len(tampered_records)}")
    print(f"Score anomalies: {len(score_anomalies)}")
    print(f"CPE discrepancies: {len(cpe_discrepancies)}")
    print(f"CWE errors: {len(cwe_errors)}")
    print(f"Vulnerable items: {len(threat_priority)}/{len(inventory)}")
    print(f"Risk score: {risk_score:.1f}")


if __name__ == "__main__":
    main()
