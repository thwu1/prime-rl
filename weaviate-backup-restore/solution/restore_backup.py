#!/usr/bin/env python3
"""
Restores the filesystem backup to the restored Weaviate instance on port 8079.
"""


import json
import sys
import time
import requests

RESTORED_URL = "http://localhost:8079"
BACKUP_ID = "full_backup_001"


def wait_ready(url, label, timeout=120):
    """Wait for a Weaviate instance to become ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(f"{url}/v1/.well-known/ready", timeout=5)
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(2)
    print(f"ERROR: {label} did not become ready within {timeout}s", file=sys.stderr)
    return False


def restore_backup(url, backup_id):
    """Restore a filesystem backup and wait for completion."""
    resp = requests.post(
        f"{url}/v1/backups/filesystem/{backup_id}/restore",
        json={},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR initiating restore: {resp.status_code} {resp.text}",
              file=sys.stderr)
        sys.exit(1)

    print(f"  Restore of '{backup_id}' initiated. Polling for completion...")

    # Poll for completion
    for _ in range(120):
        time.sleep(2)
        try:
            resp = requests.get(
                f"{url}/v1/backups/filesystem/{backup_id}/restore",
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            status = data.get("status", "")
            if status == "SUCCESS":
                print(f"  Restore of '{backup_id}' completed successfully.")
                return True
            elif status == "FAILED":
                print(f"ERROR: Restore failed: {data}", file=sys.stderr)
                sys.exit(1)
        except requests.ConnectionError:
            pass

    print("ERROR: Restore did not complete in time.", file=sys.stderr)
    sys.exit(1)


def verify_restored(url, spec):
    """Verify object counts on the restored instance."""
    print("Verifying restored data...")
    for class_name, tenant_counts in spec["expectedCounts"].items():
        for tenant, expected in tenant_counts.items():
            query = {
                "query": (
                    "{ Aggregate { "
                    + class_name
                    + '(tenant: "'
                    + tenant
                    + '") { meta { count } } } }'
                )
            }
            resp = requests.post(f"{url}/v1/graphql", json=query, timeout=30)
            data = resp.json()
            if "errors" in data:
                print(f"  GraphQL error for {class_name}/{tenant}: {data['errors']}",
                      file=sys.stderr)
                return False
            actual = data["data"]["Aggregate"][class_name][0]["meta"]["count"]
            if actual != expected:
                print(f"  Count mismatch {class_name}/{tenant}: "
                      f"expected {expected}, got {actual}", file=sys.stderr)
                return False
            print(f"  {class_name}/{tenant}: {actual} objects (OK)")
    return True


def main():
    # Load schema specification for verification
    with open("/app/schema_spec.json") as f:
        spec = json.load(f)

    # Verify restored instance is ready
    if not wait_ready(RESTORED_URL, "Restored instance"):
        sys.exit(1)

    # Restore backup
    print("Restoring backup to restored instance...")
    restore_backup(RESTORED_URL, BACKUP_ID)

    # Give some time for data to settle
    time.sleep(3)

    # Verify restored data
    if not verify_restored(RESTORED_URL, spec):
        print("ERROR: Verification of restored data failed.", file=sys.stderr)
        sys.exit(1)

    print("Restore and verification complete.")


if __name__ == "__main__":
    main()
