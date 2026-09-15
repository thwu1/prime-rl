"""
FHIR AccessPolicy Evaluation Engine with Audit Trail

Pipeline stages:
1. Extract search parameter field-path mappings from FHIR CapabilityStatement
2. Load FHIR resources from NDJSON Bulk Data files
3. Evaluate access scenarios against AccessPolicy rules
4. Generate HMAC-SHA256 audit signatures

Evaluation semantics replicated from Medplum TypeScript reference:
- Resource type matching with wildcard and admin type exclusions
- Interaction type gating
- Criteria matching with FHIR search parameter semantics (:not, :missing modifiers)
- Parameterized policy variable substitution
- Write constraint expression evaluation (simplified FHIRPath)
- Hidden and readonly field metadata reporting
"""


import glob
import hashlib
import hmac as hmac_module
import json
import sys

# From Medplum reference access.ts: projectAdminResourceTypes
ADMIN_RESOURCE_TYPES = {
    "Package", "PackageRelease", "PackageInstallation",
    "Project", "ProjectMembership", "User", "UserSecurityRequest",
}

SEARCH_PARAM_PATH_EXT_URL = (
    "http://medplum.com/fhir/StructureDefinition/search-parameter-path"
)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_ndjson_files(data_dir):
    """Load all .ndjson files from data_dir, returning a list of resources."""
    resources = []
    for filepath in sorted(glob.glob(f"{data_dir}/*.ndjson")):
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    resources.append(json.loads(line))
    return resources


def extract_search_params(capability_statement):
    """Extract search parameter field-path mappings from a FHIR CapabilityStatement.

    Traverses rest[0].resource[].searchParam[].extension[] looking for
    the medplum search-parameter-path extension to get the field path
    for each search parameter.
    """
    search_params = {}
    rest_list = capability_statement.get("rest", [])
    if not rest_list:
        return search_params

    server_rest = rest_list[0]
    for resource_def in server_rest.get("resource", []):
        resource_type = resource_def["type"]
        params = {}
        for sp in resource_def.get("searchParam", []):
            sp_name = sp["name"]
            for ext in sp.get("extension", []):
                if ext.get("url") == SEARCH_PARAM_PATH_EXT_URL:
                    params[sp_name] = ext["valueString"]
                    break
        if params:
            search_params[resource_type] = params

    return search_params


def resolve_path(obj, path):
    """Resolve a dot-separated path with [] array notation against a FHIR resource."""
    if obj is None:
        return []
    if not path:
        return [obj] if obj is not None else []

    parts = path.split(".", 1)
    current = parts[0]
    remaining = parts[1] if len(parts) > 1 else None

    if current.endswith("[]"):
        field_name = current[:-2]
        arr = obj.get(field_name) if isinstance(obj, dict) else None
        if not isinstance(arr, list):
            return []
        results = []
        for item in arr:
            if remaining:
                results.extend(resolve_path(item, remaining))
            else:
                if item is not None:
                    results.append(item)
        return results
    else:
        if not isinstance(obj, dict):
            return []
        value = obj.get(current)
        if value is None:
            return []
        if remaining:
            return resolve_path(value, remaining)
        return [value]


def resolve_parameters(policy, membership):
    """Substitute %variable and %variable.id in the policy using membership parameters."""
    params = {}
    for p in membership.get("parameter", []):
        name = p["name"]
        if "valueReference" in p:
            ref = p["valueReference"]["reference"]
            params[name] = ref
            ref_parts = ref.split("/")
            if len(ref_parts) == 2:
                params[name + ".id"] = ref_parts[1]

    if not params:
        return policy

    policy_str = json.dumps(policy)
    for var_name, var_value in sorted(params.items(), key=lambda x: -len(x[0])):
        policy_str = policy_str.replace(f"%{var_name}", var_value)

    return json.loads(policy_str)


def parse_criteria(criteria_string):
    """Parse 'ResourceType?param=val1,val2&param2:mod=val' into structured form."""
    if "?" not in criteria_string:
        return criteria_string, []

    resource_type, query_string = criteria_string.split("?", 1)
    params = []

    for part in query_string.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)

        modifier = None
        if ":" in key:
            param_name, modifier = key.split(":", 1)
        else:
            param_name = key

        values = value.split(",")
        params.append({"name": param_name, "modifier": modifier, "values": values})

    return resource_type, params


def matches_criteria_param(resource, param, search_params, resource_type):
    """Check if a resource matches a single criteria parameter."""
    param_name = param["name"]
    modifier = param["modifier"]
    values = param["values"]

    type_params = search_params.get(resource_type, {})
    path = type_params.get(param_name)

    if path is None:
        return False

    resource_values = resolve_path(resource, path)

    if modifier == "missing":
        is_missing = len(resource_values) == 0
        if values[0].lower() == "true":
            return is_missing
        else:
            return not is_missing

    if modifier == "not":
        for rv in resource_values:
            rv_str = str(rv)
            if rv_str in values:
                return False
        return True

    for rv in resource_values:
        rv_str = str(rv)
        if rv_str in values:
            return True

    return False


def resource_matches_criteria(resource, criteria_string, search_params):
    """Check if a resource matches a full criteria string (all params must match)."""
    resource_type, params = parse_criteria(criteria_string)

    if not params:
        return True

    for param in params:
        if not matches_criteria_param(resource, param, search_params, resource_type):
            return False

    return True


# --- Write Constraint Expression Evaluator ---


def tokenize_expression(expr):
    """Tokenize a simplified FHIRPath expression."""
    tokens = []
    i = 0
    while i < len(expr):
        if expr[i].isspace():
            i += 1
            continue

        if expr[i] == "'":
            j = i + 1
            while j < len(expr) and expr[j] != "'":
                j += 1
            tokens.append(("STRING", expr[i + 1 : j]))
            i = j + 1
            continue

        if expr[i] == "%" or expr[i].isalpha() or expr[i] == "_":
            j = i
            if expr[i] == "%":
                j += 1
            while j < len(expr) and (expr[j].isalnum() or expr[j] in "._"):
                j += 1
            word = expr[i:j]

            if word.endswith(".exists") and j + 2 <= len(expr) and expr[j : j + 2] == "()":
                base = word[: -len(".exists")]
                tokens.append(("EXISTS", base))
                i = j + 2
                continue

            if word == "exists" and j + 2 <= len(expr) and expr[j : j + 2] == "()":
                tokens.append(("EXISTS", ""))
                i = j + 2
                continue

            if word == "implies":
                tokens.append(("IMPLIES", word))
            elif word == "and":
                tokens.append(("AND", word))
            elif word == "or":
                tokens.append(("OR", word))
            else:
                tokens.append(("PATH", word))
            i = j
            continue

        if expr[i : i + 2] == "!=":
            tokens.append(("NEQ", "!="))
            i += 2
            continue
        if expr[i] == "=":
            tokens.append(("EQ", "="))
            i += 1
            continue
        if expr[i] == "(":
            tokens.append(("LPAREN", "("))
            i += 1
            continue
        if expr[i] == ")":
            tokens.append(("RPAREN", ")"))
            i += 1
            continue

        i += 1

    return tokens


def resolve_simple_field(resource, field_path):
    """Resolve a simple dot-separated field path (no array traversal)."""
    if resource is None or not field_path:
        return None
    current = resource
    for part in field_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def resolve_expr_path(path_str, before_resource, after_resource):
    """Resolve a path expression in the context of before/after resources."""
    if path_str.startswith("%before"):
        if before_resource is None:
            return None
        rest = path_str[len("%before") :]
        if rest.startswith("."):
            return resolve_simple_field(before_resource, rest[1:])
        return before_resource
    elif path_str.startswith("%after"):
        if after_resource is None:
            return None
        rest = path_str[len("%after") :]
        if rest.startswith("."):
            return resolve_simple_field(after_resource, rest[1:])
        return after_resource
    else:
        if after_resource is None:
            return None
        return resolve_simple_field(after_resource, path_str)


def evaluate_expression(tokens, pos, before_resource, after_resource):
    """Recursive descent parser/evaluator for FHIRPath-like expressions."""
    left, pos = evaluate_term(tokens, pos, before_resource, after_resource)

    while pos < len(tokens):
        op = tokens[pos]
        if op[0] == "IMPLIES":
            pos += 1
            right, pos = evaluate_term(tokens, pos, before_resource, after_resource)
            left = (not left) or right
        elif op[0] == "AND":
            pos += 1
            right, pos = evaluate_term(tokens, pos, before_resource, after_resource)
            left = left and right
        elif op[0] == "OR":
            pos += 1
            right, pos = evaluate_term(tokens, pos, before_resource, after_resource)
            left = left or right
        else:
            break

    return left, pos


def evaluate_term(tokens, pos, before_resource, after_resource):
    """Evaluate a single term in the expression."""
    if pos >= len(tokens):
        return False, pos

    token = tokens[pos]

    if token[0] == "LPAREN":
        pos += 1
        result, pos = evaluate_expression(tokens, pos, before_resource, after_resource)
        if pos < len(tokens) and tokens[pos][0] == "RPAREN":
            pos += 1
        return result, pos

    if token[0] == "EXISTS":
        path_str = token[1]
        if path_str == "%before":
            result = before_resource is not None
        elif path_str.startswith("%before."):
            field = path_str[len("%before.") :]
            result = (
                before_resource is not None
                and resolve_simple_field(before_resource, field) is not None
            )
        elif path_str.startswith("%after."):
            field = path_str[len("%after.") :]
            result = (
                after_resource is not None
                and resolve_simple_field(after_resource, field) is not None
            )
        elif path_str == "":
            result = False
        else:
            result = (
                after_resource is not None
                and resolve_simple_field(after_resource, path_str) is not None
            )
        return result, pos + 1

    if token[0] == "PATH":
        path_str = token[1]
        value = resolve_expr_path(path_str, before_resource, after_resource)

        if pos + 2 < len(tokens) and tokens[pos + 1][0] in ("EQ", "NEQ"):
            op = tokens[pos + 1]
            right_token = tokens[pos + 2]
            right_value = right_token[1]

            if op[0] == "EQ":
                result = str(value) == right_value if value is not None else False
            else:
                result = str(value) != right_value if value is not None else True

            return result, pos + 3

        return value is not None and value != False and value != "", pos + 1

    return False, pos + 1


def check_write_constraints(constraints, before_resource, after_resource):
    """Evaluate all write constraints. All must return true (AND logic)."""
    for constraint in constraints:
        if constraint.get("language") != "text/fhirpath":
            continue
        expr = constraint["expression"]
        tokens = tokenize_expression(expr)
        result, _ = evaluate_expression(tokens, 0, before_resource, after_resource)
        if not result:
            return False
    return True


# --- HMAC Audit Trail ---


def compute_hmac(key_hex, message):
    """Compute HMAC-SHA256 hex digest."""
    key = bytes.fromhex(key_hex)
    return hmac_module.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


# --- Main Evaluation Logic ---


def evaluate_scenario(scenario, policies_by_id, memberships_by_user, resources_by_key, search_params):
    """Evaluate a single access request scenario and return the decision."""
    user = scenario["user"]
    interaction = scenario["interaction"]
    target = scenario["target"]
    target_resource_type = target["resourceType"]
    target_id = target.get("id")
    resource_body = scenario.get("resource_body")

    membership = memberships_by_user.get(user)
    if membership is None:
        return {"decision": "deny"}

    policy_ref = membership["accessPolicy"]
    policy_id = policy_ref.split("/")[1] if "/" in policy_ref else policy_ref
    policy = policies_by_id.get(policy_id)
    if policy is None:
        return {"decision": "deny"}

    resolved_policy = resolve_parameters(policy, membership)

    existing_resource = None
    if target_id:
        resource_key = f"{target_resource_type}/{target_id}"
        existing_resource = resources_by_key.get(resource_key)

    if interaction == "create":
        criteria_resource = resource_body
    else:
        criteria_resource = existing_resource

    matched_policy = None
    for rp in resolved_policy.get("resource", []):
        rp_type = rp.get("resourceType")

        if rp_type == "*":
            if target_resource_type in ADMIN_RESOURCE_TYPES:
                continue
        elif rp_type != target_resource_type:
            continue

        interactions = rp.get("interaction")
        if interactions is not None:
            if interaction not in interactions:
                continue

        criteria = rp.get("criteria")
        if criteria and criteria_resource:
            if not resource_matches_criteria(criteria_resource, criteria, search_params):
                continue
        elif criteria and not criteria_resource:
            continue

        matched_policy = rp
        break

    if matched_policy is None:
        return {"decision": "deny"}

    if interaction in ("create", "update"):
        constraints = matched_policy.get("writeConstraint", [])
        if constraints:
            before = existing_resource if interaction == "update" else None
            after = resource_body
            if not check_write_constraints(constraints, before, after):
                return {"decision": "deny"}

    result = {"decision": "allow"}

    if interaction in ("read", "vread", "search", "history"):
        hidden = matched_policy.get("hiddenFields", [])
        if hidden:
            result["hidden_fields"] = sorted(hidden)

    if interaction == "update":
        readonly = matched_policy.get("readonlyFields", [])
        if readonly:
            result["readonly_fields"] = sorted(readonly)

    return result


def main():
    # Stage 1: Extract search params from FHIR CapabilityStatement
    cap_stmt = load_json("/app/data/capability_statement.json")
    search_params = extract_search_params(cap_stmt)
    print(f"Extracted search params for {len(search_params)} resource types from CapabilityStatement")

    # Stage 2: Load resources from NDJSON Bulk Data files
    resources = load_ndjson_files("/app/data")
    print(f"Loaded {len(resources)} resources from NDJSON files")

    # Stage 3: Load policies, memberships, scenarios
    policies = load_json("/app/data/policies.json")
    memberships = load_json("/app/data/memberships.json")
    scenarios = load_json("/app/data/scenarios.json")

    # Index data
    policies_by_id = {p["id"]: p for p in policies}
    memberships_by_user = {m["user"]: m for m in memberships}
    resources_by_key = {
        f"{r['resourceType']}/{r['id']}": r for r in resources if "id" in r
    }

    # Stage 4: Evaluate scenarios
    results = {}
    for scenario in scenarios:
        sid = scenario["id"]
        results[sid] = evaluate_scenario(
            scenario, policies_by_id, memberships_by_user, resources_by_key, search_params
        )

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"Evaluated {len(results)} scenarios -> /app/results.json")

    # Stage 5: Generate HMAC-SHA256 audit trail
    with open("/app/data/audit_key.hex") as f:
        key_hex = f.read().strip()

    audit = {}
    for sid, result in sorted(results.items()):
        canonical = f"{sid}:{result['decision']}"
        audit[sid] = compute_hmac(key_hex, canonical)

    with open("/app/audit.json", "w") as f:
        json.dump(audit, f, indent=2)
    print(f"Generated audit trail with {len(audit)} HMAC signatures -> /app/audit.json")


if __name__ == "__main__":
    main()
