#!/usr/bin/env python3
"""FHIR R5 Transaction Bundle Processor -- Implementation B

Class-based architecture with phased operation processing
and recursive reference resolution.

"""

import argparse
import json
import os
import glob
import uuid
from copy import deepcopy
from datetime import datetime, timezone


class FHIRTransactionProcessor:
    """Processes FHIR R5 transaction Bundles against a file-based server state."""

    def __init__(self, base_url="http://fhir.example.org"):
        self.base_url = base_url
        self.state = {}
        self.uuid_map = {}
        self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def load_state(self, state_dir):
        for filepath in glob.glob(os.path.join(state_dir, "*.json")):
            with open(filepath) as f:
                resource = json.load(f)
                key = f"{resource['resourceType']}/{resource['id']}"
                self.state[key] = resource

    def save_state(self, output_dir):
        state_dir = os.path.join(output_dir, "server_state")
        os.makedirs(state_dir, exist_ok=True)
        for f in glob.glob(os.path.join(state_dir, "*.json")):
            os.remove(f)
        for key, resource in self.state.items():
            rt = resource["resourceType"]
            rid = resource["id"]
            with open(os.path.join(state_dir, f"{rt}_{rid}.json"), "w") as f:
                json.dump(resource, f, indent=2)

    def _resolve_references(self, obj):
        """Recursively resolve urn:uuid: references throughout the object tree."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "reference" and isinstance(value, str) and value.startswith("urn:uuid:"):
                    if value in self.uuid_map:
                        obj[key] = self.uuid_map[value]
                else:
                    self._resolve_references(value)
        elif isinstance(obj, list):
            for item in obj:
                self._resolve_references(item)

    def _generate_id(self):
        return uuid.uuid4().hex[:12]

    def _handle_delete(self, entry):
        url = entry["request"]["url"]
        if url in self.state:
            del self.state[url]
        return {"response": {"status": "204 No Content"}}

    def _handle_post(self, entry):
        resource = deepcopy(entry.get("resource", {}))
        resource_type = resource.get("resourceType", "Unknown")
        new_id = self._generate_id()

        full_url = entry.get("fullUrl", "")
        if full_url.startswith("urn:uuid:"):
            self.uuid_map[full_url] = f"{resource_type}/{new_id}"

        self._resolve_references(resource)

        resource["id"] = new_id
        resource["meta"] = {"versionId": "1", "lastUpdated": self.timestamp}
        self.state[f"{resource_type}/{new_id}"] = resource

        return {
            "response": {
                "status": "201 Created",
                "location": f"{self.base_url}/{resource_type}/{new_id}/_history/1",
                "etag": 'W/"1"',
                "lastModified": self.timestamp,
            }
        }

    def _handle_put(self, entry):
        resource = deepcopy(entry.get("resource", {}))
        url = entry["request"]["url"]
        self._resolve_references(resource)

        if url in self.state:
            old_version = int(self.state[url].get("meta", {}).get("versionId", "0"))
            new_version = str(old_version + 1)
            resource["meta"] = {"versionId": new_version}
            self.state[url] = resource
            return {
                "response": {
                    "status": "200 OK",
                    "etag": f'W/"{new_version}"',
                    "lastModified": self.timestamp,
                }
            }
        else:
            resource["meta"] = {"versionId": "1", "lastUpdated": self.timestamp}
            self.state[url] = resource
            return {
                "response": {
                    "status": "201 Created",
                    "location": f"{self.base_url}/{url}/_history/1",
                    "etag": 'W/"1"',
                    "lastModified": self.timestamp,
                }
            }

    def process(self, bundle_path, state_dir, output_dir):
        with open(bundle_path) as f:
            bundle = json.load(f)

        if bundle.get("type") != "transaction":
            raise ValueError(f"Expected transaction, got '{bundle.get('type')}'")

        self.load_state(state_dir)
        entries = bundle.get("entry", [])

        deletes, posts, puts = [], [], []
        for i, entry in enumerate(entries):
            method = entry.get("request", {}).get("method", "").upper()
            if method == "DELETE":
                deletes.append((i, entry))
            elif method == "POST":
                posts.append((i, entry))
            elif method == "PUT":
                puts.append((i, entry))

        response_entries = [None] * len(entries)

        for idx, entry in deletes:
            response_entries[idx] = self._handle_delete(entry)

        for idx, entry in posts:
            response_entries[idx] = self._handle_post(entry)

        for idx, entry in puts:
            response_entries[idx] = self._handle_put(entry)

        response_bundle = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": response_entries,
        }

        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "response_bundle.json"), "w") as f:
            json.dump(response_bundle, f, indent=2)

        self.save_state(output_dir)
        print(f"Processed {len(entries)} entries, {len(self.state)} resources in state.")


def main():
    parser = argparse.ArgumentParser(description="FHIR R5 Transaction Processor B")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://fhir.example.org")
    args = parser.parse_args()

    processor = FHIRTransactionProcessor(args.base_url)
    processor.process(args.bundle, args.state_dir, args.output_dir)


if __name__ == "__main__":
    main()
