#!/usr/bin/env python3
"""
FHIR R5 Transaction Bundle Processor

Processes a FHIR transaction Bundle against a server state directory,
following FHIR R5 transaction processing semantics:
  - Operation ordering: DELETE -> POST -> PUT
  - urn:uuid: reference resolution (including in extensions and nested structures)
  - Conditional create (ifNoneExist) with proper urn:uuid mapping
  - Conditional reference resolution (Type?search=value)
  - Server-assigned IDs and versioning
  - Response Bundle generation

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
    """Save all resources to individual JSON files in the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    for f in glob.glob(os.path.join(output_dir, "*.json")):
        os.remove(f)
    for key, resource in state.items():
        rt = resource["resourceType"]
        rid = resource["id"]
        filename = f"{rt}_{rid}.json"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            json.dump(resource, f, indent=2)


def resolve_urn_references(obj, uuid_map):
    """Recursively walk a JSON-like object and replace all urn:uuid: reference values."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "reference" and isinstance(value, str) and value.startswith("urn:uuid:"):
                if value in uuid_map:
                    obj[key] = uuid_map[value]
            else:
                resolve_urn_references(value, uuid_map)
    elif isinstance(obj, list):
        for item in obj:
            resolve_urn_references(item, uuid_map)


def resolve_conditional_references(obj, state):
    """Recursively resolve conditional references (Type?search=value) in a resource."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if (key == "reference" and isinstance(value, str)
                    and "?" in value and not value.startswith("urn:")
                    and not value.startswith("http")):
                resolved = _resolve_single_conditional_ref(value, state)
                if resolved:
                    obj[key] = resolved
            else:
                resolve_conditional_references(value, state)
    elif isinstance(obj, list):
        for item in obj:
            resolve_conditional_references(item, state)


def _resolve_single_conditional_ref(ref_value, state):
    """Resolve a single conditional reference like Patient?identifier=system|value."""
    if "?" not in ref_value:
        return None
    type_part, search_part = ref_value.split("?", 1)
    params = _parse_search_params(search_part)

    matches = []
    for key, resource in state.items():
        if not key.startswith(f"{type_part}/"):
            continue
        if _matches_search_params(resource, params):
            matches.append(key)

    if len(matches) == 1:
        return matches[0]
    return None


def _parse_search_params(search_string):
    """Parse search parameter string into dict."""
    params = {}
    for part in search_string.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v
    return params


def _matches_search_params(resource, params):
    """Check if a resource matches given search parameters."""
    for param_name, param_value in params.items():
        if param_name == "identifier":
            identifiers = resource.get("identifier", [])
            if "|" in param_value:
                sys, val = param_value.split("|", 1)
                found = any(
                    i.get("system") == sys and i.get("value") == val
                    for i in identifiers
                )
            else:
                found = any(i.get("value") == param_value for i in identifiers)
            if not found:
                return False
        elif param_name == "patient":
            patient_ref = resource.get("patient", {}).get("reference", "")
            if patient_ref != param_value:
                return False
        elif param_name == "subject":
            subject_ref = resource.get("subject", {}).get("reference", "")
            if subject_ref != param_value:
                return False
        elif param_name == "code":
            if "|" in param_value:
                sys, code = param_value.split("|", 1)
                codings = resource.get("code", {}).get("coding", [])
                found = any(
                    c.get("system") == sys and c.get("code") == code
                    for c in codings
                )
            else:
                codings = resource.get("code", {}).get("coding", [])
                found = any(c.get("code") == param_value for c in codings)
            if not found:
                return False
        elif param_name == "medication":
            if "|" in param_value:
                sys, code = param_value.split("|", 1)
                med_codings = resource.get("medication", {}).get("concept", {}).get("coding", [])
                found = any(
                    c.get("system") == sys and c.get("code") == code
                    for c in med_codings
                )
            else:
                med_codings = resource.get("medication", {}).get("concept", {}).get("coding", [])
                found = any(c.get("code") == param_value for c in med_codings)
            if not found:
                return False
    return True


def search_state(state, resource_type, params):
    """Search server state for resources matching search parameters."""
    matches = []
    for key, resource in state.items():
        if not key.startswith(f"{resource_type}/"):
            continue
        if _matches_search_params(resource, params):
            matches.append(resource)
    return matches


def generate_id():
    """Generate a short unique ID for a new resource."""
    return uuid.uuid4().hex[:12]


def get_timestamp():
    """Get current timestamp in FHIR instant format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def process_transaction(bundle_path, state_dir, output_dir, base_url):
    """Main transaction processing logic."""
    with open(bundle_path) as f:
        bundle = json.load(f)

    if bundle.get("type") != "transaction":
        raise ValueError(f"Expected Bundle type 'transaction', got '{bundle.get('type')}'")

    state = load_server_state(state_dir)
    entries = bundle.get("entry", [])
    now = get_timestamp()

    # Categorize entries by HTTP method, preserving original index
    deletes = []
    posts = []
    puts = []
    for i, entry in enumerate(entries):
        method = entry.get("request", {}).get("method", "").upper()
        if method == "DELETE":
            deletes.append((i, entry))
        elif method == "POST":
            posts.append((i, entry))
        elif method == "PUT":
            puts.append((i, entry))

    # Prepare response entries (one per input entry, in input order)
    response_entries = [None] * len(entries)

    # ---------------------------------------------------------------
    # Phase 1: Assign IDs to all POST entries and build the uuid_map.
    # For conditional creates (ifNoneExist), evaluate the condition:
    #   - If match found: map fullUrl to EXISTING resource identity
    #   - If no match: assign new ID and map fullUrl to new identity
    # This must happen before any reference resolution so that mutual
    # references and conditional-create-dependent references resolve.
    # ---------------------------------------------------------------
    uuid_map = {}
    post_assigned_ids = {}  # original index -> assigned id (None if conditional match)
    conditional_matches = {}  # original index -> existing resource key

    for idx, entry in posts:
        resource = entry.get("resource", {})
        resource_type = resource.get("resourceType", "Unknown")
        full_url = entry.get("fullUrl", "")
        if_none_exist = entry.get("request", {}).get("ifNoneExist", "")

        if if_none_exist:
            # Evaluate conditional create
            params = _parse_search_params(if_none_exist)
            matches = search_state(state, resource_type, params)
            if len(matches) == 1:
                # Match found - map fullUrl to existing resource
                existing = matches[0]
                existing_key = f"{existing['resourceType']}/{existing['id']}"
                conditional_matches[idx] = existing_key
                if full_url and full_url.startswith("urn:uuid:"):
                    uuid_map[full_url] = existing_key
                continue
            elif len(matches) > 1:
                # Multiple matches - will return 412
                conditional_matches[idx] = None  # signal 412
                continue

        # Normal create (or conditional with no match) - assign new ID
        new_id = generate_id()
        post_assigned_ids[idx] = new_id
        if full_url and full_url.startswith("urn:uuid:"):
            uuid_map[full_url] = f"{resource_type}/{new_id}"

    # ---------------------------------------------------------------
    # Phase 2: Process DELETEs
    # ---------------------------------------------------------------
    for idx, entry in deletes:
        url = entry["request"]["url"]
        if url in state:
            del state[url]
            response_entries[idx] = {
                "response": {"status": "204 No Content"}
            }
        else:
            response_entries[idx] = {
                "response": {"status": "204 No Content"}
            }

    # ---------------------------------------------------------------
    # Phase 3: Process POSTs (creates and conditional creates)
    # ---------------------------------------------------------------
    for idx, entry in posts:
        # Handle conditional create matches
        if idx in conditional_matches:
            existing_key = conditional_matches[idx]
            if existing_key is None:
                # Multiple matches - 412
                response_entries[idx] = {
                    "response": {"status": "412 Precondition Failed"}
                }
            else:
                # Single match - return 200
                response_entries[idx] = {
                    "response": {"status": "200 OK"}
                }
            continue

        # Normal create
        resource = deepcopy(entry.get("resource", {}))
        resource_type = resource.get("resourceType", "Unknown")
        new_id = post_assigned_ids[idx]

        # Resolve all urn:uuid: references in this resource
        resolve_urn_references(resource, uuid_map)

        # Resolve conditional references (Type?search=value)
        resolve_conditional_references(resource, state)

        # Set server-assigned ID and meta
        resource["id"] = new_id
        resource["meta"] = {
            "versionId": "1",
            "lastUpdated": now,
        }

        key = f"{resource_type}/{new_id}"
        state[key] = resource

        location = f"{base_url}/{key}/_history/1"
        response_entries[idx] = {
            "response": {
                "status": "201 Created",
                "location": location,
                "etag": 'W/"1"',
                "lastModified": now,
            }
        }

    # ---------------------------------------------------------------
    # Phase 4: Process PUTs (updates)
    # ---------------------------------------------------------------
    for idx, entry in puts:
        resource = deepcopy(entry.get("resource", {}))
        url = entry["request"]["url"]

        # Resolve references
        resolve_urn_references(resource, uuid_map)
        resolve_conditional_references(resource, state)

        if url in state:
            # Update existing
            old_version = int(state[url].get("meta", {}).get("versionId", "0"))
            new_version = str(old_version + 1)
            resource["meta"] = {
                "versionId": new_version,
                "lastUpdated": now,
            }
            state[url] = resource
            response_entries[idx] = {
                "response": {
                    "status": "200 OK",
                    "etag": f'W/"{new_version}"',
                    "lastModified": now,
                }
            }
        else:
            # Upsert (create at specified ID)
            resource["meta"] = {
                "versionId": "1",
                "lastUpdated": now,
            }
            state[url] = resource
            location = f"{base_url}/{url}/_history/1"
            response_entries[idx] = {
                "response": {
                    "status": "201 Created",
                    "location": location,
                    "etag": 'W/"1"',
                    "lastModified": now,
                }
            }

    # ---------------------------------------------------------------
    # Build and save response Bundle
    # ---------------------------------------------------------------
    response_bundle = {
        "resourceType": "Bundle",
        "type": "transaction-response",
        "entry": response_entries,
    }

    os.makedirs(output_dir, exist_ok=True)
    response_path = os.path.join(output_dir, "response_bundle.json")
    with open(response_path, "w") as f:
        json.dump(response_bundle, f, indent=2)

    # Save updated server state
    state_output = os.path.join(output_dir, "server_state")
    save_server_state(state, state_output)

    print(f"Transaction processed successfully.")
    print(f"  Response bundle: {response_path}")
    print(f"  Updated state:   {state_output}/")
    print(f"  Resources in state: {len(state)}")


def main():
    parser = argparse.ArgumentParser(
        description="FHIR R5 Transaction Bundle Processor"
    )
    parser.add_argument(
        "--bundle", required=True, help="Path to the transaction Bundle JSON file"
    )
    parser.add_argument(
        "--state-dir", required=True,
        help="Path to directory containing current server state resources",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Path to output directory for response bundle and updated state",
    )
    parser.add_argument(
        "--base-url",
        default="http://fhir.example.org",
        help="FHIR server base URL for location headers",
    )
    args = parser.parse_args()
    process_transaction(args.bundle, args.state_dir, args.output_dir, args.base_url)


if __name__ == "__main__":
    main()
