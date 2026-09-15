#!/usr/bin/env python3
"""Kubernetes NetworkPolicy traffic evaluator."""

import ipaddress
import os
import sys

import yaml


def load_cluster(manifests_dir):
    path = os.path.join(manifests_dir, "cluster.yaml")
    with open(path) as f:
        docs = list(yaml.safe_load_all(f))

    namespaces, pods, policies = [], [], []
    for doc in docs:
        if not doc:
            continue
        kind = doc.get("kind", "")
        meta = doc.get("metadata", {})
        if kind == "Namespace":
            namespaces.append({"name": meta["name"], "labels": meta.get("labels", {})})
        elif kind == "Pod":
            pods.append({
                "name": meta["name"],
                "namespace": meta.get("namespace", "default"),
                "labels": meta.get("labels", {}),
                "ip": doc.get("status", {}).get("podIP", "0.0.0.0"),
            })
        elif kind == "NetworkPolicy":
            policies.append({
                "name": meta["name"],
                "namespace": meta.get("namespace", "default"),
                "spec": doc.get("spec", {}),
            })
    return {"namespaces": namespaces, "pods": pods, "policies": policies}


def label_match(selector, labels):
    if selector is None:
        return False
    if not selector:
        return True
    for k, v in selector.get("matchLabels", {}).items():
        if labels.get(k) != v:
            return False
    for expr in selector.get("matchExpressions", []):
        key, op = expr["key"], expr["operator"]
        vals = expr.get("values", [])
        lv = labels.get(key)
        if op == "In" and (lv is None or lv not in vals):
            return False
        if op == "NotIn" and lv is not None and lv in vals:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True


def ns_labels(cluster, name):
    for ns in cluster["namespaces"]:
        if ns["name"] == name:
            return ns.get("labels", {})
    return {}


def find_pod(cluster, ns, name):
    for p in cluster["pods"]:
        if p["name"] == name and p["namespace"] == ns:
            return p
    return None


def selects(policy, pod):
    if policy["namespace"] != pod["namespace"]:
        return False
    return label_match(policy["spec"].get("podSelector", {}), pod.get("labels", {}))


def peer_matches(peer, pod, pod_ns_labels, pol_ns):
    has_ps = "podSelector" in peer
    has_ns = "namespaceSelector" in peer
    has_ip = "ipBlock" in peer

    if has_ip:
        addr = ipaddress.ip_address(pod.get("ip", "0.0.0.0"))
        net = ipaddress.ip_network(peer["ipBlock"]["cidr"], strict=False)
        return addr in net

    if not has_ps and not has_ns:
        return True

    if has_ps and has_ns:
        ns_ok = label_match(peer["namespaceSelector"], pod_ns_labels)
        pod_ok = label_match(peer["podSelector"], pod.get("labels", {}))
        return ns_ok or pod_ok

    if has_ns:
        return label_match(peer["namespaceSelector"], pod_ns_labels)

    if has_ps:
        if pod["namespace"] != pol_ns:
            return False
        return label_match(peer["podSelector"], pod.get("labels", {}))

    return False


def port_ok(ports_spec, port, protocol):
    if not ports_spec:
        return True
    for p in ports_spec:
        if p.get("protocol", "TCP") != protocol:
            continue
        pp = p.get("port")
        if pp is None:
            return True
        if pp == port:
            return True
    return False


def evaluate(manifests_dir, src_spec, dst_spec, port, protocol):
    cluster = load_cluster(manifests_dir)
    src_ns, src_name = src_spec.split("/", 1)
    dst_ns, dst_name = dst_spec.split("/", 1)
    src = find_pod(cluster, src_ns, src_name)
    dst = find_pod(cluster, dst_ns, dst_name)
    if not src or not dst:
        return "DENY"

    selecting = []
    for pol in cluster["policies"]:
        if selects(pol, dst):
            ptypes = pol["spec"].get("policyTypes", ["Ingress"])
            if "Ingress" in ptypes:
                selecting.append(pol)

    if not selecting:
        return "ALLOW"

    src_nsl = ns_labels(cluster, src["namespace"])
    for pol in selecting:
        for rule in pol["spec"].get("ingress", []):
            if not port_ok(rule.get("ports"), port, protocol):
                continue
            peers = rule.get("from")
            if not peers:
                return "ALLOW"
            for peer in peers:
                if peer_matches(peer, src, src_nsl, pol["namespace"]):
                    return "ALLOW"

    return "DENY"


def main():
    if len(sys.argv) != 6:
        print(f"Usage: {sys.argv[0]} <dir> <src> <dst> <port> <proto>", file=sys.stderr)
        sys.exit(1)
    result = evaluate(sys.argv[1], sys.argv[2], sys.argv[3],
                      int(sys.argv[4]), sys.argv[5].upper())
    print(result)


if __name__ == "__main__":
    main()
