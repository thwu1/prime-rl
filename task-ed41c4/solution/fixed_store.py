"""FHIR Resource Store — fixed: also indexes by ResourceType/id."""

import json
import os


class ResourceStore:
    """In-memory FHIR resource store with reference resolution support."""

    def __init__(self):
        self._index = {}
        self._resources = []

    def load_bundle(self, filepath):
        """Load a FHIR Bundle JSON and index its entries."""
        with open(filepath) as f:
            bundle = json.load(f)

        if bundle.get("resourceType") != "Bundle":
            raise ValueError(f"Not a Bundle: {bundle.get('resourceType')}")

        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if resource is None:
                continue
            self._resources.append(resource)
            full_url = entry.get("fullUrl", "")
            if full_url:
                self._index[full_url] = resource
            rtype = resource.get("resourceType")
            rid = resource.get("id")
            if rtype and rid:
                self._index[f"{rtype}/{rid}"] = resource

    def load_directory(self, dirpath):
        """Load all .json Bundle files from a directory."""
        for name in sorted(os.listdir(dirpath)):
            if name.endswith(".json"):
                self.load_bundle(os.path.join(dirpath, name))

    def resolve(self, reference):
        """Resolve a reference string to a resource, or None."""
        return self._index.get(reference)

    def get_resources_by_type(self, resource_type):
        """Return all resources of the given FHIR type."""
        return [r for r in self._resources if r.get("resourceType") == resource_type]

    def get_all_resources(self):
        """Return all loaded top-level resources."""
        return list(self._resources)

    def get_summary(self):
        """Return resource count summary."""
        by_type = {}
        for r in self._resources:
            rt = r.get("resourceType", "Unknown")
            by_type[rt] = by_type.get(rt, 0) + 1
        return {
            "total_resources": len(self._resources),
            "by_type": dict(sorted(by_type.items())),
        }
