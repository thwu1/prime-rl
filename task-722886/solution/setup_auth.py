#!/usr/bin/env python3
"""Set up iperf3 credentials and generate CVE assessment report."""

import hashlib
import json
import os
import re


def create_credentials():
    """Create iperf3 authorized-users credential file.

    iperf3 credential hashes use SHA-256 of the string '{username}password'
    where the curly braces are literal characters in the input.
    """
    users = [
        ('alice', 'benchmark2024'),
        ('bob', 'netperf#secure'),
        ('charlie', 'thr0ughput!'),
    ]

    os.makedirs('/app/auth', exist_ok=True)
    with open('/app/auth/credentials.csv', 'w') as f:
        for username, password in users:
            plaintext = '{' + username + '}' + password
            h = hashlib.sha256(plaintext.encode('utf-8')).hexdigest()
            f.write(f'{username},{h}\n')


def parse_version(version_str):
    """Parse a version string like '3.16' into a tuple of integers."""
    parts = version_str.strip().split('.')
    return tuple(int(p) for p in parts)


def version_in_range(version, low, high_inclusive):
    """Check if version is in [low, high_inclusive]."""
    return parse_version(low) <= parse_version(version) <= parse_version(high_inclusive)


def create_cve_report():
    """Assess CVE applicability based on deployment version and advisories."""
    with open('/app/deployment_info.json', 'r') as f:
        deploy = json.load(f)

    version = deploy['upstream_version']  # "3.16"

    # Read advisory files to extract info
    advisories_dir = '/app/advisories'
    cve_data = {}

    for filename in sorted(os.listdir(advisories_dir)):
        filepath = os.path.join(advisories_dir, filename)
        with open(filepath, 'r') as f:
            content = f.read()

        # Extract CVE ID
        cve_match = re.search(r'(CVE-\d{4}-\d+)', content)
        if not cve_match:
            continue
        cve_id = cve_match.group(1)

        # Extract CVSS score for severity
        cvss_match = re.search(r'CVSS Score:\s*([\d.]+)', content)
        cvss = float(cvss_match.group(1)) if cvss_match else 0.0

        if cvss >= 9.0:
            severity = 'critical'
        elif cvss >= 7.0:
            severity = 'high'
        elif cvss >= 4.0:
            severity = 'medium'
        else:
            severity = 'low'

        cve_data[cve_id] = {
            'content': content,
            'severity': severity,
        }

    # Assess each CVE
    report = {}
    v = parse_version(version)

    # CVE-2023-38403: Affects 3.13 and earlier, fixed in 3.14
    if 'CVE-2023-38403' in cve_data:
        applicable = v <= parse_version('3.13')
        report['CVE-2023-38403'] = {
            'applicable': applicable,
            'reason': f'Fixed in iperf3 3.14; deployed version {version} is '
                      + ('within affected range (<= 3.13)' if applicable
                         else 'not affected (>= 3.14)'),
            'severity': cve_data['CVE-2023-38403']['severity'],
        }

    # CVE-2024-26306: Affects 3.2 through 3.16 inclusive, fixed in 3.17
    if 'CVE-2024-26306' in cve_data:
        applicable = version_in_range(version, '3.2', '3.16')
        report['CVE-2024-26306'] = {
            'applicable': applicable,
            'reason': f'Affects iperf3 3.2 through 3.16 inclusive; deployed version '
                      f'{version} is '
                      + ('within the affected range' if applicable
                         else 'not within the affected range'),
            'severity': cve_data['CVE-2024-26306']['severity'],
        }

    # CVE-2024-53580: Affects all versions prior to 3.18, fixed in 3.18
    if 'CVE-2024-53580' in cve_data:
        applicable = v < parse_version('3.18')
        report['CVE-2024-53580'] = {
            'applicable': applicable,
            'reason': f'Affects all iperf3 versions prior to 3.18; deployed version '
                      f'{version} is '
                      + ('affected (< 3.18)' if applicable
                         else 'not affected (>= 3.18)'),
            'severity': cve_data['CVE-2024-53580']['severity'],
        }

    # CVE-2025-54351: Affects only version 3.19, fixed in 3.19.1
    if 'CVE-2025-54351' in cve_data:
        applicable = version == '3.19'
        report['CVE-2025-54351'] = {
            'applicable': applicable,
            'reason': f'Only affects iperf3 version 3.19 (skip-rx-copy feature); '
                      f'deployed version {version} '
                      + ('is affected' if applicable
                         else 'does not contain the vulnerable feature'),
            'severity': cve_data['CVE-2025-54351']['severity'],
        }

    with open('/app/cve_report.json', 'w') as f:
        json.dump(report, f, indent=2)


if __name__ == '__main__':
    create_credentials()
    create_cve_report()
