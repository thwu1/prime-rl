"""TTCN-3 Template Matching Engine

Implements matching semantics from ETSI ES 201 873-1 (TTCN-3 Core Language).
Used as the oracle for protocol conformance test suites.

"""

import re
import copy
from itertools import permutations as iter_permutations


def match(template, value, registry=None):
    """Match a value against a TTCN-3 template.

    Args:
        template: Template definition (dict with "t" key, or primitive for exact)
        value: Value to match (JSON-compatible, None for absent)
        registry: Dict mapping template names to definitions (for modifies)

    Returns:
        bool: True if value matches template
    """
    if registry is None:
        registry = {}

    if not isinstance(template, dict) or "t" not in template:
        return _exact_match(template, value)

    t = template["t"]

    if t == "exact":
        return _exact_match(template["v"], value)
    if t == "any":
        return value is not None
    if t == "any_or_none":
        return True
    if t == "omit":
        return value is None
    if t == "complement":
        return _match_complement(template["list"], value, registry)
    if t == "range":
        return _match_range(template["lo"], template["hi"], value)
    if t == "record":
        return _match_record(template, value, registry)
    if t == "list":
        return _match_list(template["items"], value, registry)
    if t == "pattern":
        return _match_pattern(template["expr"], value)
    if t == "ifpresent":
        return value is None or match(template["inner"], value, registry)
    if t == "length":
        return _match_length(template, value, registry)
    if t == "subset":
        return _match_subset(template["members"], value)
    if t == "superset":
        return _match_superset(template["members"], value)
    if t == "permutation":
        return _match_permutation_standalone(template["items"], value, registry)
    if t == "modifies":
        return match(_resolve_modifies(template, registry), value, registry)
    raise ValueError(f"Unknown template type: {t}")


def _exact_match(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return type(a) is type(b) and a == b


def _match_complement(templates, value, registry):
    if value is None:
        return False
    return not any(match(ct, value, registry) for ct in templates)


def _match_range(lo, hi, value):
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return lo <= value <= hi


def _match_record(template, value, registry):
    if not isinstance(value, dict):
        return False
    if "_set" in value:
        return False

    fields = template["fields"]

    for fname, fspec in fields.items():
        ftmpl = fspec["tmpl"]
        is_optional = fspec.get("opt", False)

        if fname not in value:
            if not is_optional:
                return False
            tmpl_type = ftmpl.get("t") if isinstance(ftmpl, dict) else None
            if tmpl_type in ("omit", "any_or_none", "ifpresent"):
                continue
            return False

        field_val = value[fname]

        if isinstance(ftmpl, dict) and ftmpl.get("t") == "omit":
            return False

        if not match(ftmpl, field_val, registry):
            return False

    for fname in value:
        if fname.startswith("_"):
            continue
        if fname not in fields:
            return False

    return True


def _match_list(tmpl_items, value, registry):
    if not isinstance(value, list):
        return False
    return _match_list_rec(tmpl_items, 0, value, 0, registry)


def _match_list_rec(tmpl_items, ti, value, vi, registry):
    if ti == len(tmpl_items):
        return vi == len(value)

    item = tmpl_items[ti]

    if isinstance(item, dict) and item.get("t") == "any_or_none":
        for end in range(vi, len(value) + 1):
            if _match_list_rec(tmpl_items, ti + 1, value, end, registry):
                return True
        return False

    if isinstance(item, dict) and item.get("t") == "permutation":
        perm_items = item["items"]
        n = len(perm_items)
        if vi + n > len(value):
            return False
        sublist = value[vi:vi + n]
        for perm in iter_permutations(range(n)):
            if all(match(perm_items[j], sublist[perm[j]], registry) for j in range(n)):
                if _match_list_rec(tmpl_items, ti + 1, value, vi + n, registry):
                    return True
        return False

    if vi >= len(value):
        return False
    if not match(item, value[vi], registry):
        return False
    return _match_list_rec(tmpl_items, ti + 1, value, vi + 1, registry)


def _ttcn3_pattern_to_regex(pattern):
    result = []
    i = 0
    while i < len(pattern):
        c = pattern[i]

        if c == '\\' and i + 1 < len(pattern):
            nc = pattern[i + 1]
            if nc == 'd':
                result.append('[0-9]')
            elif nc == 'w':
                result.append('[a-zA-Z]')
            elif nc == 'n':
                result.append('\n')
            elif nc == 't':
                result.append('\t')
            else:
                result.append(re.escape(nc))
            i += 2

        elif c == '?':
            result.append('.')
            i += 1

        elif c == '*':
            result.append('.*')
            i += 1

        elif c == '#' and i + 1 < len(pattern) and pattern[i + 1] == '(':
            i += 2
            rep = ''
            while i < len(pattern) and pattern[i] != ')':
                rep += pattern[i]
                i += 1
            if i < len(pattern):
                i += 1
            result.append('{' + rep + '}')

        elif c == '[':
            cls = '['
            i += 1
            if i < len(pattern) and pattern[i] == '^':
                cls += '^'
                i += 1
            while i < len(pattern) and pattern[i] != ']':
                if pattern[i] == '\\' and i + 1 < len(pattern):
                    nc = pattern[i + 1]
                    if nc == 'd':
                        cls += '0-9'
                    elif nc == 'w':
                        cls += 'a-zA-Z'
                    else:
                        cls += re.escape(nc)
                    i += 2
                else:
                    cls += pattern[i]
                    i += 1
            if i < len(pattern):
                cls += ']'
                i += 1
            result.append(cls)

        else:
            if c in r'.+(){}|^$':
                result.append('\\' + c)
            else:
                result.append(c)
            i += 1

    return ''.join(result)


def _match_pattern(expr, value):
    if not isinstance(value, str):
        return False
    try:
        regex = _ttcn3_pattern_to_regex(expr)
        return bool(re.fullmatch(regex, value, re.DOTALL))
    except re.error:
        return False


def _match_length(template, value, registry):
    lo = template.get("lo", 0)
    hi = template.get("hi")

    if isinstance(value, str):
        length = len(value)
    elif isinstance(value, list):
        length = len(value)
    elif isinstance(value, dict) and "_set" in value:
        length = len(value["_set"])
    else:
        return False

    if length < lo:
        return False
    if hi is not None and length > hi:
        return False

    return match(template["inner"], value, registry)


def _match_subset(members, value):
    if not isinstance(value, dict) or "_set" not in value:
        return False
    elements = value["_set"]
    for elem in elements:
        if not any(_exact_match(m, elem) for m in members):
            return False
    return True


def _match_superset(members, value):
    if not isinstance(value, dict) or "_set" not in value:
        return False
    elements = value["_set"]
    for m in members:
        if not any(_exact_match(m, elem) for elem in elements):
            return False
    return True


def _match_permutation_standalone(items, value, registry):
    if not isinstance(value, list):
        return False
    if len(value) != len(items):
        return False
    n = len(items)
    for perm in iter_permutations(range(n)):
        if all(match(items[j], value[perm[j]], registry) for j in range(n)):
            return True
    return False


def _resolve_modifies(template, registry):
    base_name = template["base"]
    if base_name not in registry:
        raise ValueError(f"Base template '{base_name}' not found in registry")

    base = registry[base_name]
    if isinstance(base, dict) and base.get("t") == "modifies":
        base = _resolve_modifies(base, registry)

    result = copy.deepcopy(base)

    if result.get("t") != "record":
        raise ValueError("modifies only supported for record templates")

    for fname, ftmpl in template["delta"].items():
        if fname in result["fields"]:
            result["fields"][fname]["tmpl"] = ftmpl
        else:
            result["fields"][fname] = {"tmpl": ftmpl, "opt": True}

    return result


class VerdictResolver:
    VERDICT_ORDER = {"none": 0, "pass": 1, "inconc": 2, "fail": 3, "error": 4}
    VERDICT_NAMES = {v: k for k, v in VERDICT_ORDER.items()}

    def __init__(self):
        self.components = {}

    def create_component(self, component_id):
        if component_id not in self.components:
            self.components[component_id] = 0

    def set_verdict(self, component_id, verdict):
        if component_id not in self.components:
            raise ValueError(f"Component '{component_id}' not found")
        new_val = self.VERDICT_ORDER.get(verdict)
        if new_val is None:
            raise ValueError(f"Invalid verdict: {verdict}")
        self.components[component_id] = max(self.components[component_id], new_val)

    def get_verdict(self, component_id):
        if component_id not in self.components:
            raise ValueError(f"Component '{component_id}' not found")
        return self.VERDICT_NAMES[self.components[component_id]]

    def get_test_verdict(self):
        if not self.components:
            return "none"
        return self.VERDICT_NAMES[max(self.components.values())]

    def resolve_from_operations(self, operations):
        for op in operations:
            if op.get("action") == "create":
                self.create_component(op["component"])
            else:
                self.set_verdict(op["component"], op["verdict"])
        return self.get_test_verdict()
