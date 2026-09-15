"""FHIR search query evaluator."""


class SearchEngine:
    """Evaluates FHIR search queries against an in-memory resource store."""

    def __init__(self, store):
        self.store = store

    def search(self, resource_type, params):
        """Execute a FHIR search.

        Args:
            resource_type: FHIR resource type name
            params: list of (param_name, value_string) tuples
        Returns:
            sorted list of matching resource ids
        """
        candidates = self.store.get_resources_by_type(resource_type)
        matched = []
        for resource in candidates:
            if all(self._evaluate(resource, name, val) for name, val in params):
                matched.append(resource.get("id"))
        return sorted(matched)

    def _evaluate(self, resource, param, value):
        if param == "_id":
            return resource.get("id") == value
        if param == "status":
            return resource.get("status") == value
        if param == "code":
            return self._token_match(resource, "code", value)
        if param == "date":
            return self._date_match(resource, value)
        if param == "value-quantity":
            return self._quantity_match(resource, value)
        return False

    # ---- token search ----

    def _token_match(self, resource, element, value):
        """Match a token (CodeableConcept) search parameter."""
        cc = resource.get(element, {})
        codings = cc.get("coding", [])

        if "|" in value:
            search_system, search_code = value.split("|", 1)
            for coding in codings:
                if (coding.get("system") == search_system
                        or coding.get("code") == search_code):
                    return True
            return False

        return any(c.get("code") == value for c in codings)

    # ---- date search ----

    def _date_match(self, resource, value):
        """Match a date search parameter with comparison prefix support."""
        prefix, date_val = self._extract_prefix(value)
        resource_date = resource.get("effectiveDateTime") or resource.get(
            "effectivePeriod", {}
        ).get("start", "")
        if not resource_date:
            return False

        ops = {
            "eq": lambda a, b: a == b,
            "ge": lambda a, b: a >= b,
            "le": lambda a, b: a <= b,
            "gt": lambda a, b: a > b,
            "lt": lambda a, b: a < b,
            "ne": lambda a, b: a != b,
        }
        return ops.get(prefix, lambda a, b: False)(resource_date, date_val)

    # ---- quantity search ----

    def _quantity_match(self, resource, value):
        """Match a value-quantity search parameter."""
        prefix, num_str = self._extract_prefix(value)
        try:
            target = float(num_str)
        except ValueError:
            return False

        quantity = resource.get("value-quantity")
        if not quantity:
            return False

        actual = quantity.get("value")
        if actual is None:
            return False
        actual = float(actual)

        ops = {
            "eq": lambda a, b: a == b,
            "ge": lambda a, b: a >= b,
            "le": lambda a, b: a <= b,
            "gt": lambda a, b: a > b,
            "lt": lambda a, b: a < b,
        }
        return ops.get(prefix, lambda a, b: False)(actual, target)

    # ---- helpers ----

    def _extract_prefix(self, value):
        """Extract comparison prefix from a search value string."""
        for pfx in ("ge", "le", "gt", "lt", "ne", "eq", "sa", "eb", "ap"):
            if value.startswith(pfx) and len(value) > len(pfx):
                next_char = value[len(pfx)]
                if next_char in "0123456789.-":
                    return pfx, value[len(pfx):]
        return "eq", value
