#!/usr/bin/env python3
"""Kubernetes NetworkPolicy Traffic Evaluator.

Reads Kubernetes resource manifests and evaluates whether traffic between
two pods is ALLOWED or DENIED based on NetworkPolicy resources.

Supports three manifest directory formats:
- cluster.yaml: single multi-document YAML
- kustomization.yaml: kustomize overlay (rendered via kustomize build)
- multiple .yaml files: merged into a single document stream

"""

import glob as globmod
import ipaddress
import os
import subprocess
import sys

import yaml


def load_scenario(manifests_dir):
    """Load and parse Kubernetes resource manifests.

    Detects directory format and loads accordingly:
    1. If cluster.yaml exists, read it directly
    2. If kustomization.yaml exists, render via kustomize build
    3. Otherwise, merge all .yaml files in the directory
    """
    cluster_file = os.path.join(manifests_dir, "cluster.yaml")
    kustomization_file = os.path.join(manifests_dir, "kustomization.yaml")

    if os.path.exists(cluster_file):
        with open(cluster_file) as f:
            docs = list(yaml.safe_load_all(f))
    elif os.path.exists(kustomization_file):
        result = subprocess.run(
            ["kustomize", "build", manifests_dir],
            capture_output=True, text=True, check=True,
        )
        docs = list(yaml.safe_load_all(result.stdout))
    else:
        yaml_files = sorted(globmod.glob(os.path.join(manifests_dir, "*.yaml")))
        docs = []
        for yf in yaml_files:
            with open(yf) as f:
                for doc in yaml.safe_load_all(f):
                    if doc is not None:
                        docs.append(doc)

    namespaces = []
    pods = []
    network_policies = []

    for doc in docs:
        if doc is None:
            continue
        kind = doc.get("kind", "")
        meta = doc.get("metadata", {})
        if kind == "Namespace":
            namespaces.append({
                "name": meta["name"],
                "labels": meta.get("labels", {}),
            })
        elif kind == "Pod":
            pods.append({
                "name": meta["name"],
                "namespace": meta.get("namespace", "default"),
                "labels": meta.get("labels", {}),
                "ip": doc.get("status", {}).get("podIP", "0.0.0.0"),
            })
        elif kind == "NetworkPolicy":
            network_policies.append({
                "name": meta["name"],
                "namespace": meta.get("namespace", "default"),
                "spec": doc.get("spec", {}),
            })

    return {
        "namespaces": namespaces,
        "pods": pods,
        "network_policies": network_policies,
    }


def matches_selector(selector, labels):
    """Check if labels satisfy a label selector.

    Empty selector {} matches everything. None means not specified.
    """
    if selector is None:
        return False
    if not selector:
        return True

    for key, value in selector.get("matchLabels", {}).items():
        if labels.get(key) != value:
            return False

    for expr in selector.get("matchExpressions", []):
        key = expr["key"]
        operator = expr["operator"]
        values = expr.get("values", [])
        label_value = labels.get(key)

        if operator == "In":
            if label_value is None or label_value not in values:
                return False
        elif operator == "NotIn":
            if label_value is not None and label_value in values:
                return False
        elif operator == "Exists":
            if key not in labels:
                return False
        elif operator == "DoesNotExist":
            if key in labels:
                return False

    return True


def get_ns_labels(namespaces, ns_name):
    for ns in namespaces:
        if ns["name"] == ns_name:
            return ns.get("labels", {})
    return {}


def find_pod(pods, ns_name, pod_name):
    for pod in pods:
        if pod["name"] == pod_name and pod["namespace"] == ns_name:
            return pod
    return None


def get_effective_policy_types(spec):
    """Infer policyTypes when not specified.

    Per K8s spec: if absent, Ingress is always included;
    Egress is included only if egress rules exist.
    """
    if "policyTypes" in spec:
        return spec["policyTypes"]
    types = ["Ingress"]
    if "egress" in spec:
        types.append("Egress")
    return types


def policy_selects_pod(policy, pod):
    if policy["namespace"] != pod["namespace"]:
        return False
    selector = policy["spec"].get("podSelector", {})
    return matches_selector(selector, pod.get("labels", {}))


def matches_peer(peer, pod, pod_ns_labels, policy_namespace):
    """Evaluate whether a pod matches a from/to peer entry.

    Key: podSelector+namespaceSelector in same entry = AND.
    Separate entries = OR (handled at caller level).
    """
    has_pod_sel = "podSelector" in peer
    has_ns_sel = "namespaceSelector" in peer
    has_ip_block = "ipBlock" in peer

    if has_ip_block:
        pod_ip = ipaddress.ip_address(pod.get("ip", "0.0.0.0"))
        cidr = peer["ipBlock"]["cidr"]
        if pod_ip not in ipaddress.ip_network(cidr, strict=False):
            return False
        for exc in peer["ipBlock"].get("except", []):
            if pod_ip in ipaddress.ip_network(exc, strict=False):
                return False
        return True

    if not has_pod_sel and not has_ns_sel:
        return True

    if has_pod_sel and has_ns_sel:
        return (
            matches_selector(peer["namespaceSelector"], pod_ns_labels)
            and matches_selector(peer["podSelector"], pod.get("labels", {}))
        )

    if has_ns_sel:
        return matches_selector(peer["namespaceSelector"], pod_ns_labels)

    if has_pod_sel:
        if pod["namespace"] != policy_namespace:
            return False
        return matches_selector(peer["podSelector"], pod.get("labels", {}))

    return False


def ports_match(ports_spec, port, protocol):
    """Check port/protocol match, including endPort ranges."""
    if not ports_spec:
        return True
    for p in ports_spec:
        p_proto = p.get("protocol", "TCP")
        p_port = p.get("port")
        p_end = p.get("endPort")
        if p_proto != protocol:
            continue
        if p_port is None:
            return True
        if p_end is not None:
            if p_port <= port <= p_end:
                return True
        else:
            if p_port == port:
                return True
    return False


def check_direction(scenario, subject_pod, peer_pod, port, protocol, direction):
    """Check if traffic is allowed in one direction (Ingress or Egress)."""
    policies = scenario["network_policies"]
    namespaces = scenario["namespaces"]

    selecting = []
    for pol in policies:
        if policy_selects_pod(pol, subject_pod):
            if direction in get_effective_policy_types(pol["spec"]):
                selecting.append(pol)

    if not selecting:
        return True

    peer_ns_labels = get_ns_labels(namespaces, peer_pod["namespace"])
    rules_key = "ingress" if direction == "Ingress" else "egress"
    peers_key = "from" if direction == "Ingress" else "to"

    for pol in selecting:
        rules = pol["spec"].get(rules_key, [])
        for rule in rules:
            if not ports_match(rule.get("ports"), port, protocol):
                continue
            peers = rule.get(peers_key)
            if peers is None or len(peers) == 0:
                return True
            for peer in peers:
                if matches_peer(
                    peer, peer_pod, peer_ns_labels, pol["namespace"]
                ):
                    return True

    return False


def evaluate(manifests_dir, src_ns, src_pod_name, dst_ns, dst_pod_name, port, protocol):
    scenario = load_scenario(manifests_dir)

    src = find_pod(scenario["pods"], src_ns, src_pod_name)
    dst = find_pod(scenario["pods"], dst_ns, dst_pod_name)

    if not src or not dst:
        return "DENY"

    egress_ok = check_direction(scenario, src, dst, port, protocol, "Egress")
    ingress_ok = check_direction(scenario, dst, src, port, protocol, "Ingress")

    return "ALLOW" if (egress_ok and ingress_ok) else "DENY"


def main():
    if len(sys.argv) != 6:
        print(
            f"Usage: {sys.argv[0]} <manifests_dir> <src_ns/pod> <dst_ns/pod> "
            f"<port> <protocol>",
            file=sys.stderr,
        )
        sys.exit(1)

    manifests_dir = sys.argv[1]
    src_ns, src_pod = sys.argv[2].split("/", 1)
    dst_ns, dst_pod = sys.argv[3].split("/", 1)
    port = int(sys.argv[4])
    protocol = sys.argv[5].upper()

    print(evaluate(manifests_dir, src_ns, src_pod, dst_ns, dst_pod, port, protocol))


if __name__ == "__main__":
    main()
