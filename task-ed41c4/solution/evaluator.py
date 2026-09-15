"""FHIR Search Query Evaluator.

Loads FHIR Bundle JSON files and evaluates parsed search queries against
the contained resources.

"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fhir_search import parse_fhir_search


# Search parameter definitions: (resource_type, param_name) -> (element_path, type)
SEARCH_PARAM_MAP = {
    ("Observation", "code"): ("code", "token"),
    ("Observation", "date"): ("effectiveDateTime", "date"),
    ("Observation", "value-quantity"): ("valueQuantity", "quantity"),
    ("Observation", "status"): ("status", "code"),
    ("Observation", "subject"): ("subject", "reference"),
    ("MedicationRequest", "status"): ("status", "code"),
    ("MedicationRequest", "subject"): ("subject", "reference"),
    ("Condition", "code"): ("code", "token"),
    ("Condition", "clinical-status"): ("clinicalStatus", "token"),
    ("Condition", "subject"): ("subject", "reference"),
    ("Patient", "name"): ("name", "humanname"),
    ("Patient", "birthdate"): ("birthDate", "date"),
    ("Patient", "gender"): ("gender", "code"),
}


def load_bundles(bundle_dir):
    """Load all FHIR Bundle JSON files and return a flat list of resources."""
    resources = []
    for name in sorted(os.listdir(bundle_dir)):
        if name.endswith(".json"):
            with open(os.path.join(bundle_dir, name)) as f:
                bundle = json.load(f)
            if bundle.get("resourceType") != "Bundle":
                continue
            for entry in bundle.get("entry", []):
                resource = entry.get("resource")
                if resource:
                    resources.append(resource)
    return resources


def evaluate_search(resources, resource_type, query_string):
    """Evaluate a FHIR search query and return sorted list of matched resource IDs."""
    parsed = parse_fhir_search(query_string)
    candidates = [r for r in resources if r.get("resourceType") == resource_type]
    matched = []
    for resource in candidates:
        if _matches_all_params(resource, resource_type, parsed.parameters):
            rid = resource.get("id")
            if rid:
                matched.append(rid)
    return sorted(matched)


def _matches_all_params(resource, resource_type, parameters):
    """Check if resource matches ALL search parameters (AND semantics)."""
    for param in parameters:
        if not _matches_param(resource, resource_type, param):
            return False
    return True


def _matches_param(resource, resource_type, param):
    """Check if resource matches a single search parameter (OR across values)."""
    key = (resource_type, param.name)
    if key not in SEARCH_PARAM_MAP:
        return False
    element_path, param_type = SEARCH_PARAM_MAP[key]
    element_value = _get_element(resource, element_path)
    if element_value is None:
        return False
    return any(_matches_value(element_value, param_type, v) for v in param.values)


def _get_element(resource, path):
    """Get an element value from a resource by dotted path."""
    parts = path.split(".")
    current = resource
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
        if current is None:
            return None
    return current


def _matches_value(element_value, param_type, value):
    """Check if an element value matches a search parameter value."""
    if param_type == "code":
        return element_value == value.raw_value
    elif param_type == "token":
        return _token_match(element_value, value)
    elif param_type == "date":
        return _date_match(element_value, value)
    elif param_type == "quantity":
        return _quantity_match(element_value, value)
    return False


def _token_match(element_value, value):
    """Match a token (CodeableConcept) value."""
    if not isinstance(element_value, dict):
        return False
    codings = element_value.get("coding", [])
    if value.parts is not None:
        search_system = value.parts[0] if len(value.parts) > 0 else ""
        search_code = value.parts[1] if len(value.parts) > 1 else ""
        for coding in codings:
            if search_system and search_code:
                if (coding.get("system") == search_system
                        and coding.get("code") == search_code):
                    return True
            elif search_system:
                if coding.get("system") == search_system:
                    return True
            elif search_code:
                if coding.get("code") == search_code:
                    return True
        return False
    else:
        return any(c.get("code") == value.raw_value for c in codings)


def _date_match(element_value, value):
    """Match a date value with precision-aware comparison."""
    if not isinstance(element_value, str):
        return False
    prefix = value.prefix or "eq"
    search_date = value.raw_value
    precision = len(search_date)
    normalized = element_value[:precision]
    ops = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b,
        "le": lambda a, b: a <= b,
        "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b,
    }
    return ops.get(prefix, lambda a, b: False)(normalized, search_date)


def _quantity_match(element_value, value):
    """Match a quantity value with prefix comparison."""
    if not isinstance(element_value, dict):
        return False
    actual = element_value.get("value")
    if actual is None:
        return False
    actual = float(actual)
    prefix = value.prefix or "eq"
    try:
        target = float(value.raw_value)
    except (ValueError, TypeError):
        return False
    ops = {
        "eq": lambda a, b: a == b,
        "ne": lambda a, b: a != b,
        "lt": lambda a, b: a < b,
        "le": lambda a, b: a <= b,
        "gt": lambda a, b: a > b,
        "ge": lambda a, b: a >= b,
    }
    return ops.get(prefix, lambda a, b: False)(actual, target)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FHIR Search Evaluator")
    parser.add_argument("--bundles", default="/app/bundles")
    parser.add_argument("--queries", default="/app/queries.json")
    args = parser.parse_args()

    resources = load_bundles(args.bundles)

    with open(args.queries) as f:
        queries = json.load(f)

    results = {}
    for q in queries:
        matched = evaluate_search(resources, q["resource_type"], q["query"])
        results[q["name"]] = {
            "query": q["query"],
            "resource_type": q["resource_type"],
            "matched_ids": matched,
            "count": len(matched),
        }

    print(json.dumps(results, indent=2, sort_keys=True))
