#!/usr/bin/env python3
"""Cilium Network Policy Decision Engine.

"""

import json
import ipaddress
import os
from pathlib import Path

import yaml


def load_policies_from_dir(policy_dir):
    policies = []
    for f in sorted(Path(policy_dir).glob("*.yaml")):
        with open(f) as fh:
            doc = yaml.safe_load(fh)
            if doc and doc.get("kind") == "CiliumNetworkPolicy":
                policies.append(doc)
    return policies


def load_policies_from_multidoc(path):
    policies = []
    with open(path) as fh:
        for doc in yaml.safe_load_all(fh):
            if doc and doc.get("kind") == "CiliumNetworkPolicy":
                policies.append(doc)
    return policies


def load_json(path):
    with open(path) as f:
        return json.load(f)


def labels_match(selector, labels):
    if labels is None:
        return False
    if selector is None:
        return True

    match_labels = selector.get("matchLabels", {})
    for k, v in match_labels.items():
        if labels.get(k) != v:
            return False

    match_expressions = selector.get("matchExpressions", [])
    for expr in match_expressions:
        key = expr["key"]
        op = expr["operator"]
        values = expr.get("values", [])
        label_val = labels.get(key)

        if op == "In":
            if label_val not in values:
                return False
        elif op == "NotIn":
            if label_val in values:
                return False
        elif op == "Exists":
            if key not in labels:
                return False
        elif op == "DoesNotExist":
            if key in labels:
                return False

    return True


def ip_in_cidr(ip_str, cidr_str):
    ip = ipaddress.ip_address(ip_str)
    net = ipaddress.ip_network(cidr_str, strict=False)
    return ip in net


def ip_matches_cidr_list(ip_str, cidrs):
    return any(ip_in_cidr(ip_str, cidr) for cidr in cidrs)


def ip_matches_cidr_set(ip_str, cidr_sets):
    for cs in cidr_sets:
        cidr = cs["cidr"]
        excepts = cs.get("except", [])
        if ip_in_cidr(ip_str, cidr):
            if not any(ip_in_cidr(ip_str, exc) for exc in excepts):
                return True
    return False


def resolve_entity(entity, ip_str, entities_config):
    cluster_cidr = entities_config["cluster_cidr"]
    host_ip = entities_config["host_ip"]
    node_ips = entities_config.get("node_ips", [])

    if entity == "world":
        return not ip_in_cidr(ip_str, cluster_cidr)
    elif entity == "cluster":
        return ip_in_cidr(ip_str, cluster_cidr)
    elif entity == "host":
        return ip_str == host_ip
    elif entity == "remote-node":
        return ip_str in node_ips and ip_str != host_ip
    elif entity == "all":
        return True
    return False


def port_matches(rule_ports, conn_port, conn_proto):
    if not rule_ports:
        return True

    for port_rule in rule_ports:
        ports = port_rule.get("ports", [])
        for p in ports:
            port_num = int(p["port"])
            proto = p.get("protocol", "TCP").upper()
            if port_num == conn_port and proto == conn_proto.upper():
                return True
    return False


def check_l3_source_match(rule, src_ip, src_labels, entities_config):
    has_selector = False

    from_eps = rule.get("fromEndpoints", [])
    if from_eps:
        has_selector = True
        for selector in from_eps:
            if labels_match(selector, src_labels):
                return True

    from_cidr = rule.get("fromCIDR", [])
    if from_cidr:
        has_selector = True
        if ip_matches_cidr_list(src_ip, from_cidr):
            return True

    from_cidr_set = rule.get("fromCIDRSet", [])
    if from_cidr_set:
        has_selector = True
        if ip_matches_cidr_set(src_ip, from_cidr_set):
            return True

    from_entities = rule.get("fromEntities", [])
    if from_entities:
        has_selector = True
        for entity in from_entities:
            if resolve_entity(entity, src_ip, entities_config):
                return True

    return not has_selector


def check_l3_dest_match(rule, dst_ip, dst_labels, entities_config):
    has_selector = False

    to_eps = rule.get("toEndpoints", [])
    if to_eps:
        has_selector = True
        for selector in to_eps:
            if labels_match(selector, dst_labels):
                return True

    to_cidr = rule.get("toCIDR", [])
    if to_cidr:
        has_selector = True
        if ip_matches_cidr_list(dst_ip, to_cidr):
            return True

    to_cidr_set = rule.get("toCIDRSet", [])
    if to_cidr_set:
        has_selector = True
        if ip_matches_cidr_set(dst_ip, to_cidr_set):
            return True

    to_entities = rule.get("toEntities", [])
    if to_entities:
        has_selector = True
        for entity in to_entities:
            if resolve_entity(entity, dst_ip, entities_config):
                return True

    return not has_selector


def evaluate_direction(policies, ep_ip, ep_labels, peer_ip, peer_labels,
                       conn_port, conn_proto, entities_config, direction):
    deny_key = "ingressDeny" if direction == "ingress" else "egressDeny"
    allow_key = direction

    selecting_policies = []
    for policy in policies:
        spec = policy["spec"]
        selector = spec.get("endpointSelector", {})
        if labels_match(selector, ep_labels):
            selecting_policies.append(policy)

    if not selecting_policies:
        return "ALLOW"

    has_default_deny = False
    for policy in selecting_policies:
        spec = policy["spec"]
        edd = spec.get("enableDefaultDeny", {})
        has_rules = bool(spec.get(allow_key)) or bool(spec.get(deny_key))

        edd_value = edd.get(direction)
        if edd_value is True:
            has_default_deny = True
        elif edd_value is False:
            pass
        elif has_rules:
            has_default_deny = True

    for policy in selecting_policies:
        spec = policy["spec"]
        for deny_rule in spec.get(deny_key, []):
            if direction == "ingress":
                l3_match = check_l3_source_match(deny_rule, peer_ip, peer_labels, entities_config)
            else:
                l3_match = check_l3_dest_match(deny_rule, peer_ip, peer_labels, entities_config)
            l4_match = port_matches(deny_rule.get("toPorts", []), conn_port, conn_proto)
            if l3_match and l4_match:
                return "DENY"

    for policy in selecting_policies:
        spec = policy["spec"]
        for allow_rule in spec.get(allow_key, []):
            if direction == "ingress":
                l3_match = check_l3_source_match(allow_rule, peer_ip, peer_labels, entities_config)
            else:
                l3_match = check_l3_dest_match(allow_rule, peer_ip, peer_labels, entities_config)
            l4_match = port_matches(allow_rule.get("toPorts", []), conn_port, conn_proto)
            if l3_match and l4_match:
                return "ALLOW"

    if has_default_deny:
        return "DENY"
    else:
        return "ALLOW"


def main():
    # Load policies from direct YAML files
    policies = load_policies_from_dir("/app/policies")

    # Load policies rendered from Helm chart (done by solve.sh)
    helm_policies_path = "/tmp/helm-policies.yaml"
    if os.path.exists(helm_policies_path):
        policies.extend(load_policies_from_multidoc(helm_policies_path))

    # Load endpoints (parsed by jq in solve.sh)
    endpoints = load_json("/tmp/endpoints.json")
    entities_config = load_json("/app/entities.json")
    connections = load_json("/app/connections.json")

    ip_to_endpoint = {}
    for ep in endpoints:
        ip_to_endpoint[ep["ip"]] = ep

    verdicts = []
    for conn in connections:
        src_ip = conn["src_ip"]
        dst_ip = conn["dst_ip"]
        dst_port = conn["dst_port"]
        protocol = conn["protocol"]

        src_ep = ip_to_endpoint.get(src_ip)
        dst_ep = ip_to_endpoint.get(dst_ip)

        src_labels = src_ep["labels"] if src_ep else None
        dst_labels = dst_ep["labels"] if dst_ep else None

        if src_ep:
            egress_verdict = evaluate_direction(
                policies, src_ip, src_labels, dst_ip, dst_labels,
                dst_port, protocol, entities_config, "egress"
            )
        else:
            egress_verdict = "ALLOW"

        if dst_ep:
            ingress_verdict = evaluate_direction(
                policies, dst_ip, dst_labels, src_ip, src_labels,
                dst_port, protocol, entities_config, "ingress"
            )
        else:
            ingress_verdict = "ALLOW"

        verdict = "ALLOW" if (egress_verdict == "ALLOW" and ingress_verdict == "ALLOW") else "DENY"
        verdicts.append({"id": conn["id"], "verdict": verdict})

    with open("/app/verdicts.json", "w") as f:
        json.dump(verdicts, f, indent=2)

    print(f"Evaluated {len(verdicts)} connections, wrote verdicts.json")


if __name__ == "__main__":
    main()
