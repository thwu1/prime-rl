#!/usr/bin/env python3
"""Generate /app/vulnerability_report.json with exact advisory metadata."""

import json

report = [
    {
        "package": "flat",
        "installed_version": "5.0.0",
        "cve": "CVE-2020-36632",
        "ghsa": "GHSA-2j2x-2gpw-g8fm",
        "cwe": "CWE-1321",
        "cvss_v3_score": 9.8,
        "severity": "critical",
        "patched_version": "5.0.1",
        "description": "Prototype pollution via unflatten function in flat"
    },
    {
        "package": "tar",
        "installed_version": "6.1.1",
        "cve": "CVE-2021-32803",
        "ghsa": "GHSA-r628-mhmh-qjhw",
        "cwe": "CWE-22",
        "cvss_v3_score": 8.2,
        "severity": "high",
        "patched_version": "6.1.2",
        "description": "Arbitrary file creation via symlink directory cache poisoning in node-tar"
    },
    {
        "package": "nth-check",
        "installed_version": "2.0.0",
        "cve": "CVE-2021-3803",
        "ghsa": "GHSA-rp65-9cf3-cjxr",
        "cwe": "CWE-1333",
        "cvss_v3_score": 7.5,
        "severity": "high",
        "patched_version": "2.0.1",
        "description": "ReDoS via crafted CSS nth-check selector with pathological backtracking"
    },
    {
        "package": "js-yaml",
        "installed_version": "3.13.0",
        "cve": None,
        "ghsa": "GHSA-8j8c-7jfh-h6hx",
        "cwe": "CWE-94",
        "cvss_v3_score": 8.1,
        "severity": "high",
        "patched_version": "3.13.1",
        "description": "Code injection via toString on mapping key with !!js/function type in js-yaml"
    }
]

with open("/app/vulnerability_report.json", "w") as f:
    json.dump(report, f, indent=2)

print("Vulnerability report written to /app/vulnerability_report.json")
