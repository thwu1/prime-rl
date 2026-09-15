#!/usr/bin/env python3

"""FHIR R4 Transaction Bundle Processor.

Processes a FHIR transaction Bundle against simulated server state and
produces a transaction-response Bundle (or OperationOutcome on failure).

Usage:
    python3 fhir_processor.py <input_bundle.json> <server_state_dir> <output.json>
"""

import copy
import json
import os
import sys
from datetime import datetime, timezone


class FHIRTransactionProcessor:
    """Processes FHIR R4 transaction Bundles with correct semantics."""

    PROCESSING_ORDER = {"DELETE": 0, "POST": 1, "PUT": 2, "PATCH": 3, "GET": 4, "HEAD": 5}
    VALID_METHODS = frozenset(PROCESSING_ORDER.keys())

    def __init__(self, server_state_dir: str):
        self.resources: dict[str, dict[str, dict]] = {}
        self._id_counter = 0
        self._load_state(server_state_dir)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def _load_state(self, state_dir: str) -> None:
        if not os.path.isdir(state_dir):
            return
        for fname in sorted(os.listdir(state_dir)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(state_dir, fname)) as fh:
                resource = json.load(fh)
            rt = resource["resourceType"]
            rid = resource["id"]
            self.resources.setdefault(rt, {})[rid] = copy.deepcopy(resource)

    def _generate_id(self) -> str:
        self._id_counter += 1
        return f"generated-{self._id_counter}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ------------------------------------------------------------------
    # Entry-level validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_entry(entry: dict, index: int) -> str | None:
        if "request" not in entry:
            return f"Entry {index}: missing 'request'"
        req = entry["request"]
        if "method" not in req:
            return f"Entry {index}: missing 'request.method'"
        if "url" not in req:
            return f"Entry {index}: missing 'request.url'"
        method = req["method"]
        if method not in FHIRTransactionProcessor.VALID_METHODS:
            return f"Entry {index}: unsupported method '{method}'"
        if method in ("POST", "PUT", "PATCH") and "resource" not in entry:
            return f"Entry {index}: {method} requires a resource body"
        return None

    # ------------------------------------------------------------------
    # Search (for conditional creates)
    # ------------------------------------------------------------------

    def _search_identifier(self, resource_type: str, query: str) -> list[dict]:
        """Minimal search supporting identifier=system|value."""
        resources = list(self.resources.get(resource_type, {}).values())
        if not query.startswith("identifier="):
            return []
        id_value = query[len("identifier="):]
        if "|" not in id_value:
            return []
        system, value = id_value.split("|", 1)
        return [
            r
            for r in resources
            if any(
                ident.get("system") == system and ident.get("value") == value
                for ident in r.get("identifier", [])
            )
        ]

    # ------------------------------------------------------------------
    # Reference resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_refs(obj, id_map: dict[str, str]) -> None:
        """Recursively replace urn:uuid: references using id_map."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == "reference" and isinstance(value, str) and value in id_map:
                    obj[key] = id_map[value]
                elif isinstance(value, (dict, list)):
                    FHIRTransactionProcessor._resolve_refs(value, id_map)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    FHIRTransactionProcessor._resolve_refs(item, id_map)

    # ------------------------------------------------------------------
    # Individual operation processors
    # ------------------------------------------------------------------

    def _process_delete(self, entry: dict) -> dict:
        url = entry["request"]["url"]
        parts = url.split("/")
        if len(parts) >= 2:
            rt, rid = parts[0], parts[1]
            if rt in self.resources:
                self.resources[rt].pop(rid, None)
        return {"response": {"status": "204 No Content"}}

    def _process_post(self, entry: dict, post_info: dict) -> dict:
        info = post_info

        # Conditional create matched an existing resource — skip creation
        if info["action"] == "skip":
            existing = info["existing"]
            rt = info["resource_type"]
            rid = existing["id"]
            ver = existing.get("meta", {}).get("versionId", "1")
            return {
                "response": {
                    "status": "200 OK",
                    "location": f"{rt}/{rid}/_history/{ver}",
                    "etag": f'W/"{ver}"',
                },
                "resource": copy.deepcopy(existing),
            }

        # Standard create
        resource = copy.deepcopy(entry["resource"])
        rt = resource["resourceType"]
        new_id = info["id"]

        resource["id"] = new_id
        resource.setdefault("meta", {})["versionId"] = "1"
        resource["meta"]["lastUpdated"] = self._now()

        self.resources.setdefault(rt, {})[new_id] = resource

        return {
            "response": {
                "status": "201 Created",
                "location": f"{rt}/{new_id}/_history/1",
                "etag": 'W/"1"',
                "lastModified": resource["meta"]["lastUpdated"],
            },
            "resource": copy.deepcopy(resource),
        }

    def _process_put(self, entry: dict) -> dict:
        url = entry["request"]["url"]
        parts = url.split("/")
        if len(parts) < 2:
            return {"error": f"Invalid PUT URL format: {url}"}
        rt, rid = parts[0], parts[1]
        resource = copy.deepcopy(entry["resource"])

        # Conditional version check (If-Match / ETag)
        if_match = entry["request"].get("ifMatch")
        if if_match:
            existing = self.resources.get(rt, {}).get(rid)
            if existing is None:
                return {"error": f"Resource {url} not found for conditional update"}
            current_ver = existing.get("meta", {}).get("versionId", "1")
            expected_ver = if_match.replace('W/"', "").rstrip('"')
            if current_ver != expected_ver:
                return {
                    "error": (
                        f"Version conflict on {url}: "
                        f"expected version {expected_ver}, found {current_ver}"
                    )
                }

        existing = self.resources.get(rt, {}).get(rid)
        if existing:
            old_ver = int(existing.get("meta", {}).get("versionId", "0"))
            new_ver = str(old_ver + 1)
            status = "200 OK"
        else:
            new_ver = "1"
            status = "201 Created"

        resource["id"] = rid
        resource.setdefault("meta", {})["versionId"] = new_ver
        resource["meta"]["lastUpdated"] = self._now()
        self.resources.setdefault(rt, {})[rid] = resource

        return {
            "response": {
                "status": status,
                "location": f"{rt}/{rid}/_history/{new_ver}",
                "etag": f'W/"{new_ver}"',
                "lastModified": resource["meta"]["lastUpdated"],
            },
            "resource": copy.deepcopy(resource),
        }

    def _process_get(self, entry: dict) -> dict:
        url = entry["request"]["url"]
        parts = url.split("/")
        if len(parts) < 2:
            return {"error": f"Invalid GET URL format: {url}"}
        rt, rid = parts[0], parts[1]
        resource = self.resources.get(rt, {}).get(rid)
        if resource is None:
            return {"error": f"Resource {url} not found"}
        return {
            "response": {
                "status": "200 OK",
                "etag": f'W/"{resource.get("meta", {}).get("versionId", "1")}"',
            },
            "resource": copy.deepcopy(resource),
        }

    # ------------------------------------------------------------------
    # Main Bundle processor
    # ------------------------------------------------------------------

    def process_bundle(self, bundle: dict) -> dict:
        if bundle.get("resourceType") != "Bundle":
            return self._error_outcome("Input is not a Bundle resource")
        if bundle.get("type") != "transaction":
            return self._error_outcome("Bundle.type must be 'transaction'")

        entries = bundle.get("entry", [])
        if not entries:
            return {"resourceType": "Bundle", "type": "transaction-response", "entry": []}

        # --- Phase 1: Validate every entry --------------------------------
        for i, entry in enumerate(entries):
            err = self._validate_entry(entry, i)
            if err:
                return self._error_outcome(err)

        # --- Phase 2: Pre-scan POST entries --------------------------------
        # Evaluate conditional creates and assign IDs so we can build the
        # urn:uuid → server-reference map *before* any processing.
        id_map: dict[str, str] = {}          # urn:uuid:xxx → ResourceType/id
        post_info: dict[int, dict] = {}      # entry-index → info dict

        for i, entry in enumerate(entries):
            if entry["request"]["method"] != "POST":
                continue
            resource = entry["resource"]
            rt = resource["resourceType"]
            full_url = entry.get("fullUrl", "")

            if_none_exist = entry["request"].get("ifNoneExist")
            if if_none_exist:
                matches = self._search_identifier(rt, if_none_exist)
                if len(matches) > 1:
                    return self._error_outcome(
                        f"Entry {i}: conditional create matched "
                        f"{len(matches)} resources (expected 0 or 1)"
                    )
                if len(matches) == 1:
                    existing = matches[0]
                    post_info[i] = {
                        "action": "skip",
                        "existing": existing,
                        "id": existing["id"],
                        "resource_type": rt,
                    }
                    if full_url.startswith("urn:uuid:"):
                        id_map[full_url] = f"{rt}/{existing['id']}"
                    continue

            new_id = self._generate_id()
            post_info[i] = {"action": "create", "id": new_id, "resource_type": rt}
            if full_url.startswith("urn:uuid:"):
                id_map[full_url] = f"{rt}/{new_id}"

        # --- Phase 3: Resolve urn:uuid references in all entries -----------
        resolved = copy.deepcopy(entries)
        for entry in resolved:
            if "resource" in entry:
                self._resolve_refs(entry["resource"], id_map)

        # --- Phase 4: Determine processing order --------------------------
        # FHIR R4 mandates: DELETE → POST → PUT/PATCH → GET/HEAD
        indices_by_phase: list[list[int]] = [[] for _ in range(6)]
        for i, entry in enumerate(resolved):
            method = entry["request"]["method"]
            phase = self.PROCESSING_ORDER[method]
            indices_by_phase[phase].append(i)

        processing_order: list[int] = []
        for group in indices_by_phase:
            processing_order.extend(group)

        # --- Phase 5: Process atomically -----------------------------------
        snapshot = copy.deepcopy(self.resources)
        responses: list[dict | None] = [None] * len(resolved)

        for idx in processing_order:
            entry = resolved[idx]
            method = entry["request"]["method"]

            if method == "DELETE":
                result = self._process_delete(entry)
            elif method == "POST":
                result = self._process_post(entry, post_info[idx])
            elif method == "PUT":
                result = self._process_put(entry)
            elif method == "GET":
                result = self._process_get(entry)
            else:
                result = {"error": f"Unsupported method: {method}"}

            if "error" in result:
                self.resources = snapshot  # rollback
                return self._error_outcome(result["error"])

            responses[idx] = result

        # --- Phase 6: Build response Bundle --------------------------------
        response_bundle: dict = {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": [],
        }
        for resp in responses:
            entry_out: dict = {"response": resp["response"]}
            if "resource" in resp:
                entry_out["resource"] = resp["resource"]
            response_bundle["entry"].append(entry_out)

        return response_bundle

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error_outcome(message: str) -> dict:
        return {
            "resourceType": "OperationOutcome",
            "issue": [
                {
                    "severity": "error",
                    "code": "processing",
                    "diagnostics": message,
                }
            ],
        }


# ======================================================================
# CLI entry point
# ======================================================================

def main() -> None:
    if len(sys.argv) != 4:
        print(
            f"Usage: {sys.argv[0]} <input_bundle.json> <server_state_dir> <output.json>",
            file=sys.stderr,
        )
        sys.exit(1)

    input_file = sys.argv[1]
    state_dir = sys.argv[2]
    output_file = sys.argv[3]

    with open(input_file) as fh:
        bundle = json.load(fh)

    processor = FHIRTransactionProcessor(state_dir)
    result = processor.process_bundle(bundle)

    with open(output_file, "w") as fh:
        json.dump(result, fh, indent=2)


if __name__ == "__main__":
    main()
