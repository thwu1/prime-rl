#!/usr/bin/env python3

"""
Cilium Network Policy Evaluator

Reads endpoint state from SQLite, policies from YAML, and evaluates
traffic flow queries according to Cilium's policy resolution semantics.
"""

import yaml
import json
import sqlite3
import ipaddress
from pathlib import Path


def load_endpoints_from_db(db_path):
    """Extract endpoint data from the Cilium state SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Pre-fetch all endpoint rows into a list so that the inner query
    # on the same cursor does not break the outer iteration.
    endpoint_rows = list(c.execute(
        "SELECT id, name, ip_v4, identity_id FROM endpoints"
    ))

    endpoints = {}
    for row in endpoint_rows:
        ep_id = row["id"]
        labels = {}
        for lrow in c.execute(
            "SELECT key, value FROM endpoint_labels WHERE endpoint_id = ?",
            (ep_id,),
        ):
            labels[lrow["key"]] = lrow["value"]
        endpoints[row["name"]] = {
            "name": row["name"],
            "ip": row["ip_v4"],
            "labels": labels,
            "identity_id": row["identity_id"],
        }

    conn.close()
    return endpoints


def load_policies(directory):
    """Load CiliumNetworkPolicy or CiliumClusterwideNetworkPolicy YAML files."""
    policies = []
    policy_dir = Path(directory)
    if not policy_dir.exists():
        return policies
    for pf in sorted(policy_dir.glob("*.yaml")):
        with open(pf) as f:
            p = yaml.safe_load(f)
            if p:
                policies.append(p)
    return policies


def match_labels(endpoint_labels, selector_labels):
    """Check if endpoint labels satisfy matchLabels (all must match = AND)."""
    if not selector_labels:
        return True
    for key, value in selector_labels.items():
        if endpoint_labels.get(key) != value:
            return False
    return True


def match_expression(endpoint_labels, expression):
    """Check if endpoint labels satisfy a single matchExpression."""
    key = expression["key"]
    operator = expression["operator"]
    values = expression.get("values", [])
    has_key = key in endpoint_labels
    label_value = endpoint_labels.get(key)

    if operator == "In":
        return has_key and label_value in values
    elif operator == "NotIn":
        return not has_key or label_value not in values
    elif operator == "Exists":
        return has_key
    elif operator == "DoesNotExist":
        return not has_key
    else:
        raise ValueError(f"Unknown operator: {operator}")


def match_expressions(endpoint_labels, expressions):
    """Check if endpoint labels satisfy ALL matchExpressions (AND)."""
    if not expressions:
        return True
    return all(match_expression(endpoint_labels, expr) for expr in expressions)


def endpoint_matches_selector(endpoint_labels, selector):
    """Check if an endpoint matches a label selector."""
    if not selector:
        return True
    ml = selector.get("matchLabels", {})
    me = selector.get("matchExpressions", [])
    if not ml and not me:
        return True
    return match_labels(endpoint_labels, ml) and match_expressions(endpoint_labels, me)


def ip_in_cidr(ip_str, cidr_str):
    """Check if an IP address is within a CIDR range."""
    return ipaddress.ip_address(ip_str) in ipaddress.ip_network(cidr_str, strict=False)


def port_matches(query_port, query_protocol, ports_spec):
    """Check if a query port/protocol matches a toPorts specification."""
    if not ports_spec:
        return True
    for port_entry in ports_spec:
        for port_def in port_entry.get("ports", []):
            port = port_def.get("port", "")
            protocol = port_def.get("protocol", "TCP").upper()
            if str(query_port) == str(port) and query_protocol.upper() == protocol:
                return True
    return False


def l3_matches_endpoints(labels, selectors):
    """Check if labels match any fromEndpoints/toEndpoints selector (OR)."""
    if selectors is None:
        return False
    for selector in selectors:
        if endpoint_matches_selector(labels, selector):
            return True
    return False


def l3_matches_cidr(ip, cidr_list):
    """Check if IP matches any CIDR in the list."""
    if cidr_list is None:
        return False
    for cidr in cidr_list:
        if ip_in_cidr(ip, cidr):
            return True
    return False


def l3_matches_cidr_set(ip, cidr_set_list):
    """Check if IP matches any CIDRSet entry (CIDR minus exceptions)."""
    if cidr_set_list is None:
        return False
    for entry in cidr_set_list:
        cidr = entry.get("cidr", "")
        except_list = entry.get("except", [])
        if ip_in_cidr(ip, cidr):
            if not any(ip_in_cidr(ip, exc) for exc in except_list):
                return True
    return False


def evaluate_ingress_allow_rule(rule, src_labels, src_ip, dst_port, dst_protocol):
    """Evaluate a single ingress allow rule."""
    from_ep = rule.get("fromEndpoints")
    from_cidr = rule.get("fromCIDR")
    from_cidr_set = rule.get("fromCIDRSet")

    has_l3 = from_ep is not None or from_cidr is not None or from_cidr_set is not None
    if not has_l3:
        return False

    l3_ok = (
        l3_matches_endpoints(src_labels, from_ep)
        or l3_matches_cidr(src_ip, from_cidr)
        or l3_matches_cidr_set(src_ip, from_cidr_set)
    )
    if not l3_ok:
        return False

    return port_matches(dst_port, dst_protocol, rule.get("toPorts"))


def evaluate_egress_allow_rule(rule, dst_labels, dst_ip, dst_port, dst_protocol):
    """Evaluate a single egress allow rule."""
    to_ep = rule.get("toEndpoints")
    to_cidr = rule.get("toCIDR")
    to_cidr_set = rule.get("toCIDRSet")

    has_l3 = to_ep is not None or to_cidr is not None or to_cidr_set is not None
    if not has_l3:
        return False

    l3_ok = (
        l3_matches_endpoints(dst_labels, to_ep)
        or l3_matches_cidr(dst_ip, to_cidr)
        or l3_matches_cidr_set(dst_ip, to_cidr_set)
    )
    if not l3_ok:
        return False

    return port_matches(dst_port, dst_protocol, rule.get("toPorts"))


def evaluate_ingress_deny_rule(rule, src_labels, src_ip, dst_port, dst_protocol):
    """Evaluate a single ingressDeny rule. No L3 selector = matches all sources."""
    from_ep = rule.get("fromEndpoints")
    from_cidr = rule.get("fromCIDR")
    from_cidr_set = rule.get("fromCIDRSet")

    has_l3 = from_ep is not None or from_cidr is not None or from_cidr_set is not None
    if has_l3:
        l3_ok = (
            l3_matches_endpoints(src_labels, from_ep)
            or l3_matches_cidr(src_ip, from_cidr)
            or l3_matches_cidr_set(src_ip, from_cidr_set)
        )
        if not l3_ok:
            return False

    return port_matches(dst_port, dst_protocol, rule.get("toPorts"))


def evaluate_egress_deny_rule(rule, dst_labels, dst_ip, dst_port, dst_protocol):
    """Evaluate a single egressDeny rule. No L3 selector = matches all destinations."""
    to_ep = rule.get("toEndpoints")
    to_cidr = rule.get("toCIDR")
    to_cidr_set = rule.get("toCIDRSet")

    has_l3 = to_ep is not None or to_cidr is not None or to_cidr_set is not None
    if has_l3:
        l3_ok = (
            l3_matches_endpoints(dst_labels, to_ep)
            or l3_matches_cidr(dst_ip, to_cidr)
            or l3_matches_cidr_set(dst_ip, to_cidr_set)
        )
        if not l3_ok:
            return False

    return port_matches(dst_port, dst_protocol, rule.get("toPorts"))


def get_matching_policies(policies, endpoint_labels):
    """Get all policies whose endpointSelector matches the endpoint."""
    result = []
    for policy in policies:
        spec = policy.get("spec", {})
        selector = spec.get("endpointSelector", {})
        if endpoint_matches_selector(endpoint_labels, selector):
            result.append(policy)
    return result


def compute_default_deny(policies, direction):
    """
    Compute whether default-deny is ON for a direction.
    If ANY matching policy enables default-deny for this direction, it's ON.
    """
    for policy in policies:
        spec = policy.get("spec", {})
        edd = spec.get("enableDefaultDeny", {})
        explicit = edd.get(direction)

        if explicit is not None:
            if explicit:
                return True
        else:
            if direction == "ingress":
                if spec.get("ingress") or spec.get("ingressDeny"):
                    return True
            elif direction == "egress":
                if spec.get("egress") or spec.get("egressDeny"):
                    return True
    return False


def check_deny(policies, direction, peer_labels, peer_ip, port, protocol):
    """Check if any deny rule matches."""
    deny_key = "ingressDeny" if direction == "ingress" else "egressDeny"
    eval_fn = (
        evaluate_ingress_deny_rule if direction == "ingress" else evaluate_egress_deny_rule
    )

    for policy in policies:
        spec = policy.get("spec", {})
        for rule in spec.get(deny_key, []):
            if eval_fn(rule, peer_labels, peer_ip, port, protocol):
                return True
    return False


def check_allow(policies, direction, peer_labels, peer_ip, port, protocol):
    """Check if any allow rule matches."""
    allow_key = "ingress" if direction == "ingress" else "egress"
    eval_fn = (
        evaluate_ingress_allow_rule if direction == "ingress" else evaluate_egress_allow_rule
    )

    for policy in policies:
        spec = policy.get("spec", {})
        for rule in spec.get(allow_key, []):
            if eval_fn(rule, peer_labels, peer_ip, port, protocol):
                return True
    return False


def evaluate_direction(all_policies, ep_labels, direction, peer_labels, peer_ip, port, protocol):
    """
    Evaluate one direction (ingress or egress) for an endpoint.
    Returns "ALLOWED" or "DENIED".
    """
    matching = get_matching_policies(all_policies, ep_labels)
    default_deny = compute_default_deny(matching, direction)

    if check_deny(matching, direction, peer_labels, peer_ip, port, protocol):
        return "DENIED"

    if default_deny:
        if check_allow(matching, direction, peer_labels, peer_ip, port, protocol):
            return "ALLOWED"
        else:
            return "DENIED"

    return "ALLOWED"


def evaluate_query(all_policies, endpoints_map, query):
    """Evaluate a traffic flow query. Both egress and ingress must pass."""
    src = endpoints_map[query["from"]]
    dst = endpoints_map[query["to"]]
    port = query["port"]
    protocol = query["protocol"]

    egress_verdict = evaluate_direction(
        all_policies,
        src["labels"],
        "egress",
        dst["labels"],
        dst["ip"],
        port,
        protocol,
    )
    if egress_verdict == "DENIED":
        return "DENIED"

    ingress_verdict = evaluate_direction(
        all_policies,
        dst["labels"],
        "ingress",
        src["labels"],
        src["ip"],
        port,
        protocol,
    )
    return ingress_verdict


def main():
    # Load endpoint data from SQLite database
    endpoints_map = load_endpoints_from_db("/app/cilium-state.db")

    # Load all policies (both namespace and clusterwide)
    all_policies = []
    all_policies.extend(load_policies("/app/policies"))
    all_policies.extend(load_policies("/app/clusterwide-policies"))

    # Load traffic flow queries
    with open("/app/flows.json") as f:
        queries = json.load(f)["queries"]

    # Evaluate each query
    results = []
    for q in queries:
        verdict = evaluate_query(all_policies, endpoints_map, q)
        results.append(
            {
                "id": q["id"],
                "from": q["from"],
                "to": q["to"],
                "port": q["port"],
                "protocol": q["protocol"],
                "verdict": verdict,
            }
        )

    # Write results
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    for r in results:
        print(
            f"  {r['id']}: {r['from']} -> {r['to']} "
            f"{r['protocol']}/{r['port']} = {r['verdict']}"
        )


if __name__ == "__main__":
    main()
