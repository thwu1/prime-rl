#!/usr/bin/env python3
"""
Migrates all schema, tenants, and data from the primary Weaviate instance
(port 8080) to the secondary instance (port 8079) via the REST API.

Recreates collections with exact HNSW/BM25/property configurations from
schema_spec.json, creates tenants, exports all objects with vectors from
the primary, and batch-imports them to the secondary.
"""


import json
import sys
import time
import requests

PRIMARY_URL = "http://localhost:8080"
SECONDARY_URL = "http://localhost:8079"


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
    """Create a collection on the target instance from the schema spec."""
    body = {
        "class": class_name,
        "description": spec.get("description", ""),
        "vectorizer": spec.get("vectorizer", "none"),
        "vectorIndexType": spec.get("vectorIndexType", "hnsw"),
    }

    mt = spec.get("multiTenancyConfig", {})
    if mt.get("enabled"):
        body["multiTenancyConfig"] = {"enabled": True}

    vic = spec.get("vectorIndexConfig", {})
    if vic:
        body["vectorIndexConfig"] = {}
        for key in ("distance", "efConstruction", "maxConnections", "ef"):
            if key in vic:
                body["vectorIndexConfig"][key] = vic[key]

    iic = spec.get("invertedIndexConfig", {})
    if iic:
        body["invertedIndexConfig"] = {}
        if "bm25" in iic:
            body["invertedIndexConfig"]["bm25"] = iic["bm25"]
        if "indexTimestamps" in iic:
            body["invertedIndexConfig"]["indexTimestamps"] = iic["indexTimestamps"]

    props = spec.get("properties", [])
    if props:
        body["properties"] = []
        for p in props:
            prop_def = {
                "name": p["name"],
                "dataType": p["dataType"],
            }
            for opt_key in ("tokenization", "indexFilterable",
                            "indexSearchable", "indexRangeFilters"):
                if opt_key in p:
                    prop_def[opt_key] = p[opt_key]
            body["properties"].append(prop_def)

    resp = requests.post(f"{url}/v1/schema", json=body, timeout=30)
    if resp.status_code not in (200, 201):
        print(f"ERROR creating {class_name} on secondary: "
              f"{resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    print(f"  Created collection: {class_name}")


def create_tenants(url, class_name, tenant_names):
    """Create tenants on a collection."""
    tenants = [{"name": t} for t in tenant_names]
    resp = requests.post(
        f"{url}/v1/schema/{class_name}/tenants",
        json=tenants,
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR creating tenants for {class_name}: "
              f"{resp.status_code} {resp.text}", file=sys.stderr)
        sys.exit(1)
    print(f"  Created tenants for {class_name}: {tenant_names}")


def export_objects(url, class_name, tenant, limit=100):
    """Export all objects for a class/tenant from the source instance."""
    all_objects = []
    offset = 0
    while True:
        params = {
            "class": class_name,
            "tenant": tenant,
            "include": "vector",
            "limit": limit,
            "offset": offset,
        }
        resp = requests.get(f"{url}/v1/objects", params=params, timeout=60)
        if resp.status_code != 200:
            print(f"ERROR exporting {class_name}/{tenant}: "
                  f"{resp.status_code} {resp.text}", file=sys.stderr)
            sys.exit(1)
        data = resp.json()
        objects = data.get("objects", [])
        if not objects:
            break
        all_objects.extend(objects)
        offset += len(objects)
        if len(objects) < limit:
            break
    return all_objects


def batch_import(url, class_name, tenant, objects):
    """Import objects via the batch API to the target instance."""
    if not objects:
        return True

    batch_payload = {"objects": []}
    for obj in objects:
        batch_obj = {
            "class": class_name,
            "tenant": tenant,
            "properties": obj["properties"],
            "id": obj["id"],
        }
        if "vector" in obj:
            batch_obj["vector"] = obj["vector"]
        batch_payload["objects"].append(batch_obj)

    resp = requests.post(f"{url}/v1/batch/objects", json=batch_payload, timeout=60)
    if resp.status_code not in (200, 201):
        print(f"ERROR importing {class_name}/{tenant}: "
              f"{resp.status_code} {resp.text}", file=sys.stderr)
        return False

    result = resp.json()
    errors = []
    for item in result:
        item_result = item.get("result", {})
        if item_result.get("errors"):
            errors.append(item_result["errors"])
    if errors:
        print(f"  Batch errors for {class_name}/{tenant}: {errors}",
              file=sys.stderr)
        return False
    return True


def main():
    # Load schema specification
    with open("/app/schema_spec.json") as f:
        spec = json.load(f)

    # Verify secondary is ready
    if not wait_ready(SECONDARY_URL, "Secondary instance"):
        sys.exit(1)

    # Step 1: Recreate schema on secondary
    print("Creating collections on secondary instance...")
    for class_name, class_spec in spec["collections"].items():
        create_collection(SECONDARY_URL, class_name, class_spec)
        create_tenants(SECONDARY_URL, class_name, class_spec["tenants"])

    # Step 2: Export from primary, import to secondary
    print("\nMigrating object data...")
    for class_name, class_spec in spec["collections"].items():
        for tenant in class_spec["tenants"]:
            objects = export_objects(PRIMARY_URL, class_name, tenant)
            if objects:
                success = batch_import(SECONDARY_URL, class_name, tenant, objects)
                if success:
                    print(f"  Migrated {len(objects)} objects: "
                          f"{class_name}/{tenant}")
                else:
                    print(f"  FAILED to migrate: {class_name}/{tenant}",
                          file=sys.stderr)
                    sys.exit(1)
            else:
                print(f"  No objects found: {class_name}/{tenant}")

    # Step 3: Verify counts on secondary
    print("\nVerifying migrated data on secondary...")
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
                f"{SECONDARY_URL}/v1/graphql", json=query, timeout=30
            )
            data = resp.json()
            if "errors" in data:
                print(f"  GraphQL error for {class_name}/{tenant}: "
                      f"{data['errors']}", file=sys.stderr)
                sys.exit(1)
            actual = data["data"]["Aggregate"][class_name][0]["meta"]["count"]
            if actual != expected:
                print(f"  Count mismatch {class_name}/{tenant}: "
                      f"expected {expected}, got {actual}", file=sys.stderr)
                sys.exit(1)
            print(f"  {class_name}/{tenant}: {actual} objects (OK)")

    print("\nMigration complete and verified.")


if __name__ == "__main__":
    main()
