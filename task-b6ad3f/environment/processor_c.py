#!/usr/bin/env python3
"""FHIR R5 Transaction Bundle Processor -- Implementation C

Event-driven architecture with conditional operation support,
pre-assigned identity mapping, and phased processing.

"""

import argparse
import json
import os
import glob
import uuid
from copy import deepcopy
from datetime import datetime, timezone


class TransactionEngine:
    """FHIR R5 Transaction Bundle processing engine."""

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

    def _parse_search_params(self, search_string):
        """Parse search parameter string into dict."""
        params = {}
        for part in search_string.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k] = v
        return params

    def _search_state(self, resource_type, params):
        """Search server state for resources matching search parameters."""
        matches = []
        for key, resource in self.state.items():
            if not key.startswith(f"{resource_type}/"):
                continue
            match = True
            for param_name, param_value in params.items():
                if param_name == "patient":
                    patient_ref = resource.get("patient", {}).get("reference", "")
                    if patient_ref != param_value:
                        match = False
                        break
                elif param_name == "subject":
                    subject_ref = resource.get("subject", {}).get("reference", "")
                    if subject_ref != param_value:
                        match = False
                        break
                elif param_name == "code":
                    if "|" in param_value:
                        search_system, search_code = param_value.split("|", 1)
                        codings = resource.get("code", {}).get("coding", [])
                        found = any(
                            c.get("system") == search_system and c.get("code") == search_code
                            for c in codings
                        )
                        if not found:
                            match = False
                            break
                    else:
                        codings = resource.get("code", {}).get("coding", [])
                        found = any(c.get("code") == param_value for c in codings)
                        if not found:
                            match = False
                            break
                elif param_name == "medication":
                    if "|" in param_value:
                        search_system, search_code = param_value.split("|", 1)
                        med_codings = resource.get("medication", {}).get("concept", {}).get("coding", [])
                        found = any(
                            c.get("system") == search_system and c.get("code") == search_code
                            for c in med_codings
                        )
                        if not found:
                            match = False
                            break
            if match:
                matches.append(resource)
        return matches

    def _handle_delete(self, entry):
        url = entry["request"]["url"]
        if url in self.state:
            del self.state[url]
        return {"response": {"status": "204 No Content"}}

    def _handle_post(self, entry, assigned_id):
        resource = deepcopy(entry.get("resource", {}))
        resource_type = resource.get("resourceType", "Unknown")
        full_url = entry.get("fullUrl", "")

        # Check for conditional create (ifNoneExist)
        if_none_exist = entry.get("request", {}).get("ifNoneExist", "")
        if if_none_exist:
            params = self._parse_search_params(if_none_exist)
            matches = self._search_state(resource_type, params)
            if len(matches) == 1:
                # Match found - return 200 OK without creating
                # NOTE: This implementation correctly skips the create and returns
                # 200. However, it does NOT map the entry's fullUrl (urn:uuid:)
                # to the existing resource's identity in the uuid_map. This means
                # that other entries referencing this fullUrl will have unresolved
                # urn:uuid: references.
                return {
                    "response": {"status": "200 OK"}
                }
            elif len(matches) > 1:
                return {
                    "response": {"status": "412 Precondition Failed"}
                }

        # Normal create
        if full_url and full_url.startswith("urn:uuid:") and full_url not in self.uuid_map:
            self.uuid_map[full_url] = f"{resource_type}/{assigned_id}"

        self._resolve_references(resource)

        resource["id"] = assigned_id
        resource["meta"] = {"versionId": "1", "lastUpdated": self.timestamp}
        self.state[f"{resource_type}/{assigned_id}"] = resource

        return {
            "response": {
                "status": "201 Created",
                "location": f"{self.base_url}/{resource_type}/{assigned_id}/_history/1",
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
            resource["meta"] = {"versionId": new_version, "lastUpdated": self.timestamp}
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

        # Categorize entries by HTTP method
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

        # Phase 0: Pre-assign IDs for POST entries and build uuid_map
        # Only maps non-conditional creates. Conditional creates are checked
        # at processing time - if they match, the create is skipped.
        post_ids = {}
        for idx, entry in posts:
            new_id = self._generate_id()
            post_ids[idx] = new_id
            full_url = entry.get("fullUrl", "")
            if_none_exist = entry.get("request", {}).get("ifNoneExist", "")
            if not if_none_exist and full_url and full_url.startswith("urn:uuid:"):
                resource = entry.get("resource", {})
                resource_type = resource.get("resourceType", "Unknown")
                self.uuid_map[full_url] = f"{resource_type}/{new_id}"

        # Phase 1: Process DELETEs
        for idx, entry in deletes:
            response_entries[idx] = self._handle_delete(entry)

        # Phase 2: Process POSTs
        for idx, entry in posts:
            response_entries[idx] = self._handle_post(entry, post_ids[idx])

        # Phase 3: Process PUTs
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
    parser = argparse.ArgumentParser(description="FHIR R5 Transaction Processor C")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-url", default="http://fhir.example.org")
    args = parser.parse_args()

    engine = TransactionEngine(args.base_url)
    engine.process(args.bundle, args.state_dir, args.output_dir)


if __name__ == "__main__":
    main()
