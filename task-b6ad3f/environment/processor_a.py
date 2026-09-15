#!/usr/bin/env python3
"""FHIR R5 Transaction Bundle Processor -- Implementation A

Processes a FHIR R5 transaction Bundle against a file-based server state,
producing a transaction-response Bundle and updated server state directory.

"""

import argparse
import json
import os
import glob
import uuid
from copy import deepcopy
from datetime import datetime, timezone


def load_server_state(state_dir):
    """Load all FHIR resources from a directory into a dict keyed by ResourceType/id."""
    state = {}
    for filepath in glob.glob(os.path.join(state_dir, "*.json")):
        with open(filepath) as f:
            resource = json.load(f)
            key = f"{resource['resourceType']}/{resource['id']}"
            state[key] = resource
    return state


def save_server_state(state, output_dir):
    """Save all resources to individual JSON files."""
    os.makedirs(output_dir, exist_ok=True)
    for f in glob.glob(os.path.join(output_dir, "*.json")):
        os.remove(f)
    for key, resource in state.items():
        rt = resource["resourceType"]
        rid = resource["id"]
        filepath = os.path.join(output_dir, f"{rt}_{rid}.json")
        with open(filepath, "w") as f:
            json.dump(resource, f, indent=2)


def resolve_references(resource, uuid_map):
    """Resolve urn:uuid: references in FHIR resource reference fields."""
    for field in ("subject", "encounter", "requester", "author", "performer"):
        if field in resource and isinstance(resource[field], dict):
            ref = resource[field].get("reference", "")
            if ref in uuid_map:
                resource[field]["reference"] = uuid_map[ref]
    for p in resource.get("participant", []):
        if "actor" in p and isinstance(p["actor"], dict):
            ref = p["actor"].get("reference", "")
            if ref in uuid_map:
                p["actor"]["reference"] = uuid_map[ref]


def generate_id():
    """Generate a server-assigned resource ID."""
    return uuid.uuid4().hex[:12]


def get_timestamp():
    """Current timestamp in FHIR instant format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def process_transaction(bundle_path, state_dir, output_dir, base_url):
    """Process a FHIR transaction Bundle."""
    with open(bundle_path) as f:
        bundle = json.load(f)

    if bundle.get("type") != "transaction":
        raise ValueError(f"Expected transaction bundle, got '{bundle.get('type')}'")

    state = load_server_state(state_dir)
    entries = bundle.get("entry", [])
    now = get_timestamp()

    uuid_map = {}
    response_entries = [None] * len(entries)

    for i, entry in enumerate(entries):
        method = entry.get("request", {}).get("method", "").upper()
        url = entry.get("request", {}).get("url", "")

        if method == "DELETE":
            if url in state:
                del state[url]
            response_entries[i] = {
                "response": {"status": "200 OK"}
            }

        elif method == "POST":
            resource = deepcopy(entry.get("resource", {}))
            resource_type = resource.get("resourceType", "Unknown")
            new_id = generate_id()

            full_url = entry.get("fullUrl", "")
            if full_url.startswith("urn:uuid:"):
                uuid_map[full_url] = f"{resource_type}/{new_id}"

            resolve_references(resource, uuid_map)

            resource["id"] = new_id
            resource["meta"] = {"versionId": "1", "lastUpdated": now}

            state[f"{resource_type}/{new_id}"] = resource

            response_entries[i] = {
                "response": {
                    "status": "201 Created",
                    "location": f"{base_url}/{resource_type}/{new_id}/_history/1",
                    "etag": 'W/"1"',
                    "lastModified": now,
                }
            }

        elif method == "PUT":
            resource = deepcopy(entry.get("resource", {}))
            resolve_references(resource, uuid_map)

            resource["meta"] = {"versionId": "1", "lastUpdated": now}
            state[url] = resource

            response_entries[i] = {
                "response": {
                    "status": "200 OK",
                    "etag": 'W/"1"',
                    "lastModified": now,
                }
            }

    response_bundle = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": response_entries,
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "response_bundle.json"), "w") as f:
        json.dump(response_bundle, f, indent=2)

    save_server_state(state, os.path.join(output_dir, "server_state"))
    print(f"Processed {len(entries)} entries, {len(state)} resources in state.")


def main():
    parser = argparse.ArgumentParser(description="FHIR R5 Transaction Processor")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://fhir.example.org")
    args = parser.parse_args()
    process_transaction(args.bundle, args.state_dir, args.output_dir, args.base_url)


if __name__ == "__main__":
    main()
