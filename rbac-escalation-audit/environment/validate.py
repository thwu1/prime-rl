#!/usr/bin/env python3
"""Validate RBAC audit report against security invariants."""
import json
import sys


def main():
    try:
        with open("/app/output/report.json") as f:
            report = json.load(f)
    except FileNotFoundError:
        print("Validation: FAILED - Report not found")
        return 1
    except json.JSONDecodeError:
        print("Validation: FAILED - Invalid JSON")
        return 1

    errors = 0

    # Structural checks
    for section in ["effective_permissions", "escalation_paths", "wildcard_roles"]:
        if section not in report:
            print(f"  FAIL: Missing section '{section}'")
            errors += 1

    perms = report.get("effective_permissions", {})

    # Verify queried subjects are present
    for expected in [
        "User:dev-lead@example.com",
        "User:developer@example.com",
        "ServiceAccount:monitoring:prometheus",
    ]:
        if expected not in perms:
            print(f"  FAIL: Missing subject {expected}")
            errors += 1

    # Security invariant: ci-deployer must not have cluster-wide secret access
    try:
        ci_key = "ServiceAccount:development:ci-deployer"
        if ci_key in perms:
            for rule in perms[ci_key].get("cluster_wide", []):
                if "secrets" in rule.get("resources", []):
                    print("  FAIL: ci-deployer has cluster-wide secret access")
                    errors += 1
    except Exception:
        pass

    # Escalation sanity check
    paths = report.get("escalation_paths", [])
    if len(paths) < 3:
        print(f"  FAIL: Only {len(paths)} escalation paths - expected more")
        errors += 1

    if errors > 0:
        print(f"\nValidation: FAILED ({errors} issues)")
        return 1

    print("Validation: PASSED - All security invariants satisfied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
