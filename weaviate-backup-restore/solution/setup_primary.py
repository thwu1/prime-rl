#!/usr/bin/env python3
"""
Creates collections from schema_spec.json, loads data via seed_data.py,
and verifies object counts on the primary Weaviate instance (port 8080).
"""


import json
import sys
import time
import subprocess
import requests

PRIMARY_URL = "http://localhost:8080"


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


def create_collection(url, class_name, spec):
    """Create a collection via the REST API."""
    body = {
        "class": class_name,
        "description": spec.get("description", ""),
        "vectorizer": spec.get("vectorizer", "none"),
        "vectorIndexType": spec.get("vectorIndexType", "hnsw"),
    }

    # Multi-tenancy
    mt = spec.get("multiTenancyConfig", {})
    if mt.get("enabled"):
        body["multiTenancyConfig"] = {"enabled": True}

    # Vector index config
    vic = spec.get("vectorIndexConfig", {})
    if vic:
        body["vectorIndexConfig"] = {}
        for key in ("distance", "efConstruction", "maxConnections", "ef"):
            if key in vic:
                body["vectorIndexConfig"][key] = vic[key]

    # Inverted index config
    iic = spec.get("invertedIndexConfig", {})
    if iic:
        body["invertedIndexConfig"] = {}
        if "bm25" in iic:
            body["invertedIndexConfig"]["bm25"] = iic["bm25"]
        if "indexTimestamps" in iic:
            body["invertedIndexConfig"]["indexTimestamps"] = iic["indexTimestamps"]

    # Properties
    props = spec.get("properties", [])
    if props:
        body["properties"] = []
        for p in props:
            prop_def = {
                "name": p["name"],
                "dataType": p["dataType"],
            }
            if "tokenization" in p:
                prop_def["tokenization"] = p["tokenization"]
            if "indexFilterable" in p:
                prop_def["indexFilterable"] = p["indexFilterable"]
            if "indexSearchable" in p:
                prop_def["indexSearchable"] = p["indexSearchable"]
            if "indexRangeFilters" in p:
                prop_def["indexRangeFilters"] = p["indexRangeFilters"]
            body["properties"].append(prop_def)

    resp = requests.post(f"{url}/v1/schema", json=body, timeout=30)
    if resp.status_code not in (200, 201):
        print(f"ERROR creating {class_name}: {resp.status_code} {resp.text}",
              file=sys.stderr)
        sys.exit(1)
    print(f"  Created collection: {class_name}")


def create_tenants(url, class_name, tenant_names):
    """Create tenants on a collection via the REST API."""
    tenants = [{"name": t} for t in tenant_names]
    resp = requests.post(
        f"{url}/v1/schema/{class_name}/tenants",
        json=tenants,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR creating tenants for {class_name}: {resp.status_code} {resp.text}",
              file=sys.stderr)
        sys.exit(1)
    print(f"  Created tenants for {class_name}: {tenant_names}")


def main():
    # Load schema specification
    with open("/app/schema_spec.json") as f:
        spec = json.load(f)

    # Verify primary is ready
    if not wait_ready(PRIMARY_URL, "Primary instance"):
        sys.exit(1)

    # Create collections
    print("Creating collections...")
    for class_name, class_spec in spec["collections"].items():
        create_collection(PRIMARY_URL, class_name, class_spec)
        create_tenants(PRIMARY_URL, class_name, class_spec["tenants"])

    # Load data using seed_data.py
    print("Loading data via seed_data.py...")
    result = subprocess.run(
        [sys.executable, "/app/seed_data.py"],
        capture_output=True, text=True, timeout=120,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR running seed_data.py: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Verify counts
    print("Verifying object counts...")
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
            resp = requests.post(
                f"{PRIMARY_URL}/v1/graphql", json=query, timeout=30
            )
            data = resp.json()
            if "errors" in data:
                print(f"  GraphQL error for {class_name}/{tenant}: {data['errors']}",
                      file=sys.stderr)
                sys.exit(1)
            actual = data["data"]["Aggregate"][class_name][0]["meta"]["count"]
            if actual != expected:
                print(f"  Count mismatch {class_name}/{tenant}: "
                      f"expected {expected}, got {actual}", file=sys.stderr)
                sys.exit(1)
            print(f"  {class_name}/{tenant}: {actual} objects (OK)")

    print("Primary setup complete.")


if __name__ == "__main__":
    main()
