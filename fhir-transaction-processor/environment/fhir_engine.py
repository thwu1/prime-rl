#!/usr/bin/env python3
"""FHIR R4 Transaction Bundle Processor."""

import copy
import json
import os
import sys
from datetime import datetime, timezone


class FHIRTransactionEngine:
    """Processes FHIR R4 transaction Bundles against simulated server state."""

    VALID_METHODS = frozenset({"DELETE", "POST", "PUT", "PATCH", "GET", "HEAD"})

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
    # Validation
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
        if method not in FHIRTransactionEngine.VALID_METHODS:
            return f"Entry {index}: unsupported method '{method}'"
        if method in ("POST", "PUT", "PATCH") and "resource" not in entry:
            return f"Entry {index}: {method} requires a resource body"
        return None

    # ------------------------------------------------------------------
    # Search (conditional creates)
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

    def _resolve_references(self, resource: dict, id_map: dict[str, str]) -> None:
        """Replace urn:uuid: references in the resource using the id_map."""
        for key, value in resource.items():
            if isinstance(value, dict) and "reference" in value:
                ref = value["reference"]
                if isinstance(ref, str) and ref in id_map:
                    value["reference"] = id_map[ref]

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

        if info["action"] == "skip":
            existing = info["existing"]
            rt = info["resource_type"]
            rid = existing["id"]
            ver = existing.get("meta", {}).get("versionId", "1")
            return {
                "response": {
                    "status": "200 OK",
                    "location": f"{rt}/{rid}/_history/{ver}",
                    "etag": f'"{ver}"',
                },
                "resource": copy.deepcopy(existing),
            }

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
                "etag": '"1"',
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
                "etag": f'"{new_ver}"',
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
                "etag": f'"{resource.get("meta", {}).get("versionId", "1")}"',
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
        id_map: dict[str, str] = {}
        post_info: dict[int, dict] = {}

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
                    pass

            new_id = self._generate_id()
            post_info[i] = {"action": "create", "id": new_id, "resource_type": rt}
            if full_url.startswith("urn:uuid:"):
                id_map[full_url] = f"{rt}/{new_id}"

        # --- Phase 3: Resolve urn:uuid references -------------------------
        resolved = copy.deepcopy(entries)
        for entry in resolved:
            if "resource" in entry:
                self._resolve_references(entry["resource"], id_map)

        # --- Phase 4: Process entries -------------------------------------
        responses = []
        for idx in range(len(resolved)):
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
                responses.append({
                    "response": {"status": "400 Bad Request"},
                })
                continue

            responses.append(result)

        # --- Phase 5: Build response Bundle --------------------------------
        return {
            "resourceType": "Bundle",
            "type": "transaction-response",
            "entry": responses,
        }

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

    engine = FHIRTransactionEngine(state_dir)
    result = engine.process_bundle(bundle)

    with open(output_file, "w") as fh:
        json.dump(result, fh, indent=2)


if __name__ == "__main__":
    main()
