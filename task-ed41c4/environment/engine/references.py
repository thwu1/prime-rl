"""FHIR reference integrity checker."""


class ReferenceChecker:
    """Validates that all references in FHIR resources point to existing targets."""

    def __init__(self, store):
        self.store = store

    def check_all(self):
        """Check reference integrity across all loaded resources."""
        results = {"total_checked": 0, "valid": 0, "broken": []}
        for resource in self.store.get_all_resources():
            self._walk(resource, resource, "", results)
        return results

    def _walk(self, root, obj, path, results):
        """Recursively walk a resource tree and validate references."""
        if isinstance(obj, dict):
            if "reference" in obj and isinstance(obj["reference"], str):
                ref_value = obj["reference"]
                results["total_checked"] += 1
                if self._is_valid(ref_value):
                    results["valid"] += 1
                else:
                    results["broken"].append(
                        {
                            "source": f"{root.get('resourceType')}/{root.get('id')}",
                            "path": f"{path}.reference" if path else "reference",
                            "target": ref_value,
                            "error": "Target resource not found",
                        }
                    )
            for key, val in obj.items():
                if key == "contained":
                    continue
                child_path = f"{path}.{key}" if path else key
                self._walk(root, val, child_path, results)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                self._walk(root, item, f"{path}[{i}]", results)

    def _is_valid(self, reference):
        """Check whether a FHIR reference target exists."""
        if reference.startswith("#"):
            target_id = reference[1:]
            return any(
                r.get("id") == target_id for r in self.store.get_all_resources()
            )
        return self.store.resolve(reference) is not None
