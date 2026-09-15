#!/usr/bin/env python3
"""
Pipeline pre-deployment validator.
Checks data integrity across the CDN configuration pipeline.

"""
import json
import os
import sqlite3
import sys

MAX_FEATURES = 200
CONFIG_PATH = "/app/config/features.json"
PREFIX_PATH = "/app/data/prefixes.json"
DB_PATH = "/app/data/pipeline.db"


def validate_config():
    """Validate the generated feature configuration."""
    issues = []

    if not os.path.exists(CONFIG_PATH):
        return ["Feature config not found at " + CONFIG_PATH]

    with open(CONFIG_PATH) as f:
        try:
            config = json.load(f)
        except json.JSONDecodeError as e:
            return [f"Invalid JSON in config: {e}"]

    features = config.get("features", [])

    # Check for oversized config
    if len(features) > MAX_FEATURES:
        issues.append(
            f"Feature count {len(features)} exceeds maximum {MAX_FEATURES}"
        )

    # Check for duplicate feature names
    names = [f.get("name", "") for f in features]
    seen = set()
    dupes = set()
    for name in names:
        if name in seen:
            dupes.add(name)
        seen.add(name)
    if dupes:
        issues.append(f"Duplicate feature names detected: {sorted(dupes)}")

    # Check count consistency
    declared = config.get("feature_count", -1)
    if declared != len(features):
        issues.append(
            f"Declared feature_count ({declared}) does not match "
            f"actual feature count ({len(features)})"
        )

    return issues


def validate_prefixes():
    """Validate prefix data integrity."""
    issues = []

    if not os.path.exists(PREFIX_PATH):
        return ["Prefix data not found at " + PREFIX_PATH]

    with open(PREFIX_PATH) as f:
        try:
            prefixes = json.load(f)
        except json.JSONDecodeError as e:
            return [f"Invalid JSON in prefix data: {e}"]

    if not isinstance(prefixes, list):
        issues.append("Prefix data is not a list")
    elif len(prefixes) == 0:
        issues.append("Prefix data is empty - possible data loss")

    return issues


def check_database():
    """Check database for potential consistency risks (advisory)."""
    warnings = []

    if not os.path.exists(DB_PATH):
        return warnings

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT schema_name FROM feature_columns "
            "WHERE table_name = 'http_requests_features'"
        )
        schemas = [row[0] for row in cursor.fetchall()]
        conn.close()

        if len(schemas) > 1:
            warnings.append(
                f"Multiple schemas contain feature data: {schemas}. "
                f"Ensure queries filter by schema to avoid duplicates."
            )
    except Exception:
        pass

    return warnings


def main():
    print("=== Pipeline Pre-Deployment Validator ===\n")

    all_issues = []

    config_issues = validate_config()
    for issue in config_issues:
        print(f"[FAIL] {issue}")
    all_issues.extend(config_issues)

    prefix_issues = validate_prefixes()
    for issue in prefix_issues:
        print(f"[FAIL] {issue}")
    all_issues.extend(prefix_issues)

    db_warnings = check_database()
    for warning in db_warnings:
        print(f"[WARN] {warning}")

    if all_issues:
        print(f"\nResult: FAILED ({len(all_issues)} issue(s) found)")
        sys.exit(1)
    else:
        print("\nResult: PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()
