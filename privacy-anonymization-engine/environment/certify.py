#!/usr/bin/env python3
"""MDPS Compliance Certification Tool v1.0

Generates a signed compliance certification for anonymized datasets.
Validates report structure, computes HMAC-SHA256 digest, and records
data provenance from the privacy database.

Usage:
    certify.py --report PATH --dataset PATH --key PATH --output PATH
               [--db PATH] [--provenance-key KEY]

Example:
    python3 certify.py \\
        --report /app/output/compliance_report.json \\
        --dataset /app/output/remediated.csv \\
        --key /app/compliance/signing.key \\
        --output /app/output/certification.json \\
        --db /app/data/privacy.db
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone


def canonicalize_json(obj):
    """Produce a canonical JSON string for HMAC computation."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'))


def compute_dataset_hash(path):
    """Compute SHA256 hash of the dataset file."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def validate_report(report):
    """Validate compliance report has required structure."""
    required_top = [
        'generalization_levels', 'num_records', 'num_equivalence_classes',
        'min_ec_size', 'max_ec_size', 'avg_ec_size', 'weighted_ncp',
        'privacy_checks'
    ]
    missing = [f for f in required_top if f not in report]
    if missing:
        return False, "Missing required fields: {}".format(', '.join(missing))

    pc = report.get('privacy_checks', {})
    required_controls = ['RIC', 'ADR', 'DCR', 'DDR']
    missing_controls = [c for c in required_controls if c not in pc]
    if missing_controls:
        return False, "Missing controls in privacy_checks: {}".format(
            ', '.join(missing_controls))

    for ctrl in required_controls:
        if 'satisfied' not in pc[ctrl]:
            return False, "Control {} missing 'satisfied' field".format(ctrl)
        if pc[ctrl]['satisfied'] is not True:
            return False, "Control {} is not satisfied".format(ctrl)

    return True, "OK"


def main():
    parser = argparse.ArgumentParser(
        description='MDPS Compliance Certification Tool v1.0',
        epilog='Generates a signed certification for MDPS-compliant anonymized datasets.'
    )
    parser.add_argument('--report', required=True,
        help='Path to compliance report JSON file')
    parser.add_argument('--dataset', required=True,
        help='Path to remediated dataset CSV file')
    parser.add_argument('--key', required=True,
        help='Path to HMAC signing key file')
    parser.add_argument('--output', required=True,
        help='Output path for certification JSON')
    parser.add_argument('--db',
        help='Path to privacy database for provenance lookup')
    parser.add_argument('--provenance-key', default='dataset_id',
        help='Provenance key to include in certification (default: dataset_id)')

    args = parser.parse_args()

    # Load and validate report
    if not os.path.exists(args.report):
        print("ERROR: Report file not found: {}".format(args.report),
              file=sys.stderr)
        sys.exit(1)

    with open(args.report) as f:
        report = json.load(f)

    valid, msg = validate_report(report)
    if not valid:
        print("ERROR: Report validation failed: {}".format(msg),
              file=sys.stderr)
        sys.exit(1)

    # Load dataset
    if not os.path.exists(args.dataset):
        print("ERROR: Dataset file not found: {}".format(args.dataset),
              file=sys.stderr)
        sys.exit(1)

    dataset_hash = compute_dataset_hash(args.dataset)

    # Load signing key
    if not os.path.exists(args.key):
        print("ERROR: Signing key not found: {}".format(args.key),
              file=sys.stderr)
        sys.exit(1)

    with open(args.key) as f:
        signing_key = f.read().strip()

    # Get provenance from database
    dataset_id = None
    if args.db and os.path.exists(args.db):
        try:
            import sqlite3
            conn = sqlite3.connect(args.db)
            cursor = conn.execute(
                "SELECT value FROM data_provenance WHERE key = ?",
                (args.provenance_key,)
            )
            row = cursor.fetchone()
            if row:
                dataset_id = row[0]
            conn.close()
        except Exception as e:
            print("WARNING: Could not read provenance from DB: {}".format(e),
                  file=sys.stderr)

    # Compute HMAC signature
    canonical_report = canonicalize_json(report)
    message = "{}|{}".format(canonical_report, dataset_hash)
    signature = hmac.new(
        signing_key.encode(),
        message.encode(),
        hashlib.sha256
    ).hexdigest()

    # Generate certification
    certification = {
        "certification_version": "1.0",
        "framework": "MDPS v2.1",
        "dataset_hash": dataset_hash,
        "report_hash": hashlib.sha256(canonical_report.encode()).hexdigest(),
        "signature": signature,
        "algorithm": "HMAC-SHA256",
        "controls_verified": sorted(report.get('privacy_checks', {}).keys()),
        "all_controls_satisfied": all(
            v.get('satisfied', False)
            for v in report.get('privacy_checks', {}).values()
        ),
        "num_records": report.get('num_records'),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }

    if dataset_id:
        certification["dataset_id"] = dataset_id

    os.makedirs(os.path.dirname(os.path.abspath(args.output)) or '.', exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(certification, f, indent=2)

    print("Certification generated: {}".format(args.output))
    print("  Dataset hash: {}".format(dataset_hash))
    print("  Signature:    {}".format(signature))
    if dataset_id:
        print("  Dataset ID:   {}".format(dataset_id))


if __name__ == '__main__':
    main()
