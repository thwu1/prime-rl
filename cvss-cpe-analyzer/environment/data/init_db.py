#!/usr/bin/env python3
"""
Initialize the NVD mirror SQLite database with HMAC-signed records and
deliberate post-signing corruptions. Uses a single consolidated table
with CPE configurations stored as JSON blobs (queryable via JSON1 extension).
"""

import sqlite3
import json
import hmac
import hashlib
import os

DB_PATH = "/app/data/nvd_mirror.db"
KEY_PATH = "/app/data/.hmac_key"


def compute_hmac(key, cve_id, cvss_vector, base_score, cwe_id, cpe_config_json):
    """Compute HMAC-SHA256 over canonical record fields."""
    msg = f"{cve_id}|{cvss_vector}|{base_score:.1f}|{cwe_id}|{cpe_config_json}"
    return hmac.new(key.encode(), msg.encode(), hashlib.sha256).hexdigest()


def canonical_json(obj):
    """Produce canonical JSON: compact, sorted keys."""
    return json.dumps(obj, separators=(',', ':'), sort_keys=True)


def main():
    key = open(KEY_PATH).read().strip()

    # ===== Define all CVE records with CORRECT data =====
    records = [
        {
            "cve_id": "CVE-MIRROR-0001",
            "description": "JNDI injection in AcmeLogLib allows remote code execution via crafted log messages in versions 2.0.0 through 2.15.0.",
            "published": "2024-01-15",
            "last_modified": "2024-01-16",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H",
            "cvss_base_score": 10.0,
            "cvss_severity": "CRITICAL",
            "cwe_id": "CWE-917",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:loglib:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "2.0.0", "versionEndExcluding": "2.15.1"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0002",
            "description": "Out-of-bounds read in AcmeCryptoLib TLS heartbeat extension allows information disclosure.",
            "published": "2024-02-10",
            "last_modified": "2024-02-11",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:N/A:N",
            "cvss_base_score": 7.5,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-125",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:cryptolib:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "1.0.1", "versionEndExcluding": "1.0.2"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0003",
            "description": "Command injection via environment variable processing in AcmeShellUtil allows arbitrary code execution.",
            "published": "2024-03-01",
            "last_modified": "2024-03-02",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "cvss_base_score": 9.8,
            "cvss_severity": "CRITICAL",
            "cwe_id": "CWE-78",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:shellutil:*:*:*:*:*:*:*:*",
                 "versionEndIncluding": "4.3.0"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0004",
            "description": "Race condition in AcmeKernelOS memory management allows local privilege escalation.",
            "published": "2024-03-15",
            "last_modified": "2024-03-16",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:L/AC:H/PR:L/UI:N/S:U/C:H/I:H/A:H",
            "cvss_base_score": 7.0,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-362",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:o:acme:kernelos:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "2.6.22", "versionEndExcluding": "4.8.3"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0005",
            "description": "Unsafe deserialization in AcmeBlogEngine allows authenticated remote code execution.",
            "published": "2024-04-01",
            "last_modified": "2024-04-02",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H",
            "cvss_base_score": 8.8,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-502",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:blogengine:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "5.0.0", "versionEndExcluding": "5.9.3"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0006",
            "description": "Reflected XSS in AcmeWebFramework search parameter allows session hijacking.",
            "published": "2024-04-15",
            "last_modified": "2024-04-16",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N",
            "cvss_base_score": 6.1,
            "cvss_severity": "MEDIUM",
            "cwe_id": "CWE-79",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:webframework:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "3.0.0", "versionEndExcluding": "3.2.14"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0007",
            "description": "Timing side-channel in AcmeDataStore authentication allows credential extraction.",
            "published": "2024-05-01",
            "last_modified": "2024-05-02",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "cvss_base_score": 8.1,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-208",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:datastore:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "8.0.0", "versionEndExcluding": "8.2.0"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0008",
            "description": "Buffer overflow in AcmeUSBCtrl firmware USB descriptor parsing allows code execution via physical access.",
            "published": "2024-05-15",
            "last_modified": "2024-05-16",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "cvss_base_score": 6.8,
            "cvss_severity": "MEDIUM",
            "cwe_id": "CWE-119",
            "cpe_config": [{"operator": "AND", "nodes": [
                {"operator": "OR", "negate": False, "cpeMatch": [
                    {"vulnerable": True, "criteria": "cpe:2.3:o:acme:usbctrl_firmware:*:*:*:*:*:*:*:*",
                     "versionStartIncluding": "1.0.0", "versionEndExcluding": "3.0.0"}
                ]},
                {"operator": "OR", "negate": False, "cpeMatch": [
                    {"vulnerable": False, "criteria": "cpe:2.3:h:acme:usbctrl:-:*:*:*:*:*:*:*"}
                ]}
            ]}],
        },
        {
            "cve_id": "CVE-MIRROR-0009",
            "description": "Container escape via improper capability handling in AcmeContainerRT allows host privilege escalation.",
            "published": "2024-06-01",
            "last_modified": "2024-06-02",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H",
            "cvss_base_score": 8.8,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-269",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:container_rt:*:*:*:*:*:*:*:*",
                 "versionStartExcluding": "1.0.0", "versionEndExcluding": "2.0.0"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0010",
            "description": "Improper authorization in AcmeMsgQueue admin API allows queue manipulation by high-privilege users.",
            "published": "2024-06-15",
            "last_modified": "2024-06-16",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H",
            "cvss_base_score": 7.2,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-863",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:msgqueue:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "3.0.0", "versionEndExcluding": "3.2.0"},
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:msgqueue:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "4.0.0", "versionEndExcluding": "4.1.5"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0011",
            "description": "SQL injection in AcmeAnalytics report generator allows unauthorized data access.",
            "published": "2024-07-01",
            "last_modified": "2024-07-02",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N",
            "cvss_base_score": 9.1,
            "cvss_severity": "CRITICAL",
            "cwe_id": "CWE-89",
            "cpe_config": [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
                {"vulnerable": True, "criteria": "cpe:2.3:a:acme:analytics:*:*:*:*:*:*:*:*",
                 "versionStartIncluding": "2.0.0", "versionEndExcluding": "2.5.0"}
            ]}]}],
        },
        {
            "cve_id": "CVE-MIRROR-0012",
            "description": "Server-side request forgery in AcmeProxy firmware allows internal network scanning from authenticated sessions.",
            "published": "2024-07-15",
            "last_modified": "2024-07-16",
            "vuln_status": "Analyzed",
            "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:L/A:N",
            "cvss_base_score": 8.5,
            "cvss_severity": "HIGH",
            "cwe_id": "CWE-918",
            "cpe_config": [{"operator": "AND", "nodes": [
                {"operator": "OR", "negate": False, "cpeMatch": [
                    {"vulnerable": True, "criteria": "cpe:2.3:o:acme:proxy_firmware:*:*:*:*:*:*:*:*",
                     "versionStartIncluding": "4.0.0", "versionEndExcluding": "4.5.0"}
                ]},
                {"operator": "OR", "negate": False, "cpeMatch": [
                    {"vulnerable": False, "criteria": "cpe:2.3:h:acme:proxy_appliance:-:*:*:*:*:*:*:*"}
                ]}
            ]}],
        },
    ]

    # ===== Create database =====
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE cve_records (
            cve_id TEXT PRIMARY KEY,
            description TEXT,
            published TEXT,
            last_modified TEXT,
            vuln_status TEXT,
            cvss_vector TEXT NOT NULL,
            cvss_base_score REAL NOT NULL,
            cvss_severity TEXT NOT NULL,
            cwe_id TEXT,
            cpe_config TEXT,
            hmac_sha256 TEXT
        )
    """)

    # ===== Insert records with CORRECT data and HMAC =====
    for r in records:
        cpe_json = canonical_json(r["cpe_config"])
        h = compute_hmac(key, r["cve_id"], r["cvss_vector"],
                         r["cvss_base_score"], r["cwe_id"], cpe_json)
        c.execute(
            "INSERT INTO cve_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["cve_id"], r["description"], r["published"],
             r["last_modified"], r["vuln_status"], r["cvss_vector"],
             r["cvss_base_score"], r["cvss_severity"], r["cwe_id"],
             cpe_json, h)
        )

    conn.commit()

    # ===== Apply post-signing corruptions =====
    # These UPDATE statements modify data WITHOUT updating the HMAC,
    # simulating post-ETL tampering.

    # CVE-0002: base_score 7.5 -> 8.2
    c.execute("UPDATE cve_records SET cvss_base_score = 8.2 WHERE cve_id = 'CVE-MIRROR-0002'")

    # CVE-0004: CWE-362 -> CWE-416
    c.execute("UPDATE cve_records SET cwe_id = 'CWE-416' WHERE cve_id = 'CVE-MIRROR-0004'")

    # CVE-0005: CPE versionEndExcluding 5.9.3 -> 5.7.0
    corrupted_0005 = [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
        {"vulnerable": True, "criteria": "cpe:2.3:a:acme:blogengine:*:*:*:*:*:*:*:*",
         "versionStartIncluding": "5.0.0", "versionEndExcluding": "5.7.0"}
    ]}]}]
    c.execute("UPDATE cve_records SET cpe_config = ? WHERE cve_id = 'CVE-MIRROR-0005'",
              (canonical_json(corrupted_0005),))

    # CVE-0007: base_score 8.1 -> 7.5
    c.execute("UPDATE cve_records SET cvss_base_score = 7.5 WHERE cve_id = 'CVE-MIRROR-0007'")

    # CVE-0008: CWE-119 -> CWE-787
    c.execute("UPDATE cve_records SET cwe_id = 'CWE-787' WHERE cve_id = 'CVE-MIRROR-0008'")

    # CVE-0009: base_score 8.8 -> 9.1, versionStartExcluding -> versionStartIncluding
    corrupted_0009 = [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
        {"vulnerable": True, "criteria": "cpe:2.3:a:acme:container_rt:*:*:*:*:*:*:*:*",
         "versionStartIncluding": "1.0.0", "versionEndExcluding": "2.0.0"}
    ]}]}]
    c.execute("UPDATE cve_records SET cvss_base_score = 9.1, cpe_config = ? WHERE cve_id = 'CVE-MIRROR-0009'",
              (canonical_json(corrupted_0009),))

    # CVE-0011: CPE versionEndExcluding 2.5.0 -> 2.3.0
    corrupted_0011 = [{"nodes": [{"operator": "OR", "negate": False, "cpeMatch": [
        {"vulnerable": True, "criteria": "cpe:2.3:a:acme:analytics:*:*:*:*:*:*:*:*",
         "versionStartIncluding": "2.0.0", "versionEndExcluding": "2.3.0"}
    ]}]}]
    c.execute("UPDATE cve_records SET cpe_config = ? WHERE cve_id = 'CVE-MIRROR-0011'",
              (canonical_json(corrupted_0011),))

    # CVE-0012: base_score 8.5 -> 7.6
    c.execute("UPDATE cve_records SET cvss_base_score = 7.6 WHERE cve_id = 'CVE-MIRROR-0012'")

    conn.commit()
    conn.close()

    print(f"Database initialized at {DB_PATH}")
    print("8 records have been tampered post-signing.")


if __name__ == "__main__":
    main()
