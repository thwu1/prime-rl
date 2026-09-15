#!/usr/bin/env python3

"""
Kubernetes NetworkPolicy Connectivity Analyzer

Renders a kustomize overlay to obtain final manifests, then evaluates
pod-to-pod and IP-to-pod connectivity based on full NetworkPolicy semantics
including named ports, matchExpressions, ipBlock CIDR, and endPort ranges.
"""

import sys
import json
import yaml
import subprocess
import ipaddress


def load_manifests():
    """Load manifests by running kustomize build on the production overlay."""
    result = subprocess.run(
        ["kustomize", "build", "/app/manifests/overlays/production/"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"kustomize build failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    resources = []
    for doc in yaml.safe_load_all(result.stdout):
        if doc is not None:
            resources.append(doc)
    return resources


def build_index(resources):
    """Build lookup indices for namespaces, pods, and network policies."""
    namespaces = {}
    pods = {}
    policies = []

    for r in resources:
        kind = r.get("kind", "")
        metadata = r.get("metadata", {})

        if kind == "Namespace":
            name = metadata.get("name", "")
            namespaces[name] = metadata.get("labels", {})

        elif kind == "Pod":
            name = metadata.get("name", "")
            ns = metadata.get("namespace", "default")

            container_ports = []
            for container in r.get("spec", {}).get("containers", []):
                for port in container.get("ports", []):
                    container_ports.append(port)

            pods[f"{ns}/{name}"] = {
                "name": name,
                "namespace": ns,
                "labels": metadata.get("labels", {}),
                "container_ports": container_ports,
            }

        elif kind == "NetworkPolicy":
            policies.append({
                "name": metadata.get("name", ""),
                "namespace": metadata.get("namespace", "default"),
                "spec": r.get("spec", {}),
            })

    return namespaces, pods, policies


def selector_matches(selector, labels):
    """Check if a label selector matches a set of labels.

    Supports both matchLabels and matchExpressions with AND semantics.
    An empty or missing selector matches everything.
    """
    if selector is None:
        return True

    # matchLabels: all must match
    match_labels = selector.get("matchLabels", {})
    for k, v in match_labels.items():
        if labels.get(k) != v:
            return False

    # matchExpressions: all must match (AND)
    match_expressions = selector.get("matchExpressions", [])
    for expr in match_expressions:
        key = expr["key"]
        operator = expr["operator"]
        values = set(expr.get("values", []))
        label_value = labels.get(key)

        if operator == "In":
            if label_value not in values:
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


def pod_selector_matches(pod_selector, pod_labels):
    """Check if a podSelector matches pod labels.

    Empty dict {} matches all pods (Kubernetes semantics).
    """
    if pod_selector is None or pod_selector == {}:
        return True
    return selector_matches(pod_selector, pod_labels)


def policy_selects_pod(policy, pod_info):
    """Determine if a NetworkPolicy's podSelector matches a given pod.

    A policy only applies to pods in its own namespace.
    """
    if policy["namespace"] != pod_info["namespace"]:
        return False
    return pod_selector_matches(
        policy["spec"].get("podSelector", {}),
        pod_info["labels"],
    )


def get_policy_types(policy):
    """Determine effective policyTypes for a NetworkPolicy.

    If policyTypes is not specified:
      - Ingress is always assumed
      - Egress is assumed only if egress rules are present
    """
    explicit = policy["spec"].get("policyTypes")
    if explicit:
        return explicit
    types = ["Ingress"]
    if policy["spec"].get("egress") is not None:
        types.append("Egress")
    return types


def resolve_named_port(port_name, pod_info):
    """Resolve a named port to a number using the pod's container port definitions."""
    for cp in pod_info.get("container_ports", []):
        if cp.get("name") == port_name:
            return cp["containerPort"]
    return None


def peer_matches_pod(peer, pod_info, namespaces, policy_namespace):
    """Check if a single from/to peer entry matches a pod.

    Peer entry semantics:
    - podSelector only: matches pods in the POLICY's namespace
    - namespaceSelector only: matches all pods in matching namespaces
    - both: AND semantics (namespace must match AND pod labels must match)
    - ipBlock: ignored for pod-to-pod analysis
    """
    if "ipBlock" in peer:
        return False

    has_pod_sel = "podSelector" in peer
    has_ns_sel = "namespaceSelector" in peer

    pod_ns = pod_info["namespace"]
    pod_labels = pod_info["labels"]
    ns_labels = namespaces.get(pod_ns, {})

    if has_pod_sel and has_ns_sel:
        # AND semantics: both must match
        ns_ok = selector_matches(peer["namespaceSelector"], ns_labels)
        pod_ok = selector_matches(peer["podSelector"], pod_labels)
        return ns_ok and pod_ok

    if has_pod_sel and not has_ns_sel:
        # Same namespace as the policy only
        if pod_ns != policy_namespace:
            return False
        return selector_matches(peer["podSelector"], pod_labels)

    if has_ns_sel and not has_pod_sel:
        # All pods in matching namespaces
        return selector_matches(peer["namespaceSelector"], ns_labels)

    # Neither selector (empty peer) - matches everything
    return True


def port_matches(port_spec, dst_port, protocol, resolve_pod):
    """Check if a port specification matches a given port and protocol.

    Named ports (string values) are resolved against resolve_pod's container ports.
    endPort defines an inclusive port range.
    """
    spec_proto = port_spec.get("protocol", "TCP")
    if spec_proto != protocol:
        return False

    spec_port = port_spec.get("port")
    if spec_port is None:
        return True  # matches all ports

    # Resolve named port
    if isinstance(spec_port, str):
        resolved = resolve_named_port(spec_port, resolve_pod)
        if resolved is None:
            return False  # named port not found on target pod
        spec_port = resolved

    # Check endPort range
    end_port = port_spec.get("endPort")
    if end_port is not None:
        return spec_port <= dst_port <= end_port

    return spec_port == dst_port


def check_direction(direction, pod_info, other_pod_info, dst_port, protocol,
                    policies, namespaces):
    """Check if traffic is allowed for a given direction.

    Args:
        direction: "Ingress" or "Egress"
        pod_info: the pod being evaluated (destination for Ingress, source for Egress)
        other_pod_info: the counterpart pod
        dst_port: destination port number
        protocol: "TCP" or "UDP"
        policies: list of all network policies
        namespaces: namespace label index

    Returns:
        True if traffic is allowed in this direction.
    """
    # Find policies that select this pod for this direction
    relevant = []
    for pol in policies:
        if policy_selects_pod(pol, pod_info):
            if direction in get_policy_types(pol):
                relevant.append(pol)

    # No policy selects this pod for this direction -> default allow all
    if not relevant:
        return True

    # At least one policy selects the pod - only explicitly allowed traffic passes
    rules_key = "ingress" if direction == "Ingress" else "egress"
    peers_key = "from" if direction == "Ingress" else "to"

    # For port resolution:
    # Ingress: resolve against pod_info (the destination/selected pod)
    # Egress: resolve against other_pod_info (the destination pod)
    if direction == "Ingress":
        port_resolve_pod = pod_info
    else:
        port_resolve_pod = other_pod_info

    for pol in relevant:
        rules = pol["spec"].get(rules_key) or []
        for rule in rules:
            peers = rule.get(peers_key)
            ports = rule.get("ports")

            # Peer matching
            if peers is None or len(peers) == 0:
                peer_ok = True
            else:
                peer_ok = any(
                    peer_matches_pod(p, other_pod_info, namespaces,
                                    pol["namespace"])
                    for p in peers
                )

            if not peer_ok:
                continue

            # Port matching
            if ports is None or len(ports) == 0:
                return True

            if any(port_matches(ps, dst_port, protocol, port_resolve_pod)
                   for ps in ports):
                return True

    return False


def check_connectivity(src_key, dst_key, dst_port, protocol,
                       pods, namespaces, policies):
    """Determine if src pod can reach dst pod on dst_port/protocol.

    Evaluates source egress AND destination ingress.
    Returns "ALLOWED" or "DENIED".
    """
    src_pod = pods[src_key]
    dst_pod = pods[dst_key]

    # Source must be allowed to send (egress)
    if not check_direction("Egress", src_pod, dst_pod, dst_port, protocol,
                           policies, namespaces):
        return "DENIED"

    # Destination must be allowed to receive (ingress)
    if not check_direction("Ingress", dst_pod, src_pod, dst_port, protocol,
                           policies, namespaces):
        return "DENIED"

    return "ALLOWED"


def ip_matches_ipblock(src_ip, ip_block):
    """Check if an IP address matches an ipBlock specification."""
    cidr = ip_block.get("cidr")
    if not cidr:
        return False

    ip = ipaddress.ip_address(src_ip)
    network = ipaddress.ip_network(cidr, strict=False)

    if ip not in network:
        return False

    # Check exception ranges
    for except_cidr in ip_block.get("except", []):
        except_net = ipaddress.ip_network(except_cidr, strict=False)
        if ip in except_net:
            return False

    return True


def check_ip_ingress(src_ip, dst_key, dst_port, protocol,
                     pods, namespaces, policies):
    """Check if an external IP can reach a pod.

    Only evaluates destination ingress. Only ipBlock peers match external IPs.
    """
    dst_pod = pods[dst_key]

    # Find ingress policies selecting the destination pod
    relevant = []
    for pol in policies:
        if policy_selects_pod(pol, dst_pod):
            if "Ingress" in get_policy_types(pol):
                relevant.append(pol)

    # No policy selects -> allow all
    if not relevant:
        return "ALLOWED"

    port_resolve_pod = dst_pod

    for pol in relevant:
        rules = pol["spec"].get("ingress") or []
        for rule in rules:
            peers = rule.get("from")
            ports = rule.get("ports")

            # For IP queries, only ipBlock peers match
            if peers is None or len(peers) == 0:
                peer_ok = True
            else:
                peer_ok = any(
                    "ipBlock" in p and ip_matches_ipblock(src_ip, p["ipBlock"])
                    for p in peers
                )

            if not peer_ok:
                continue

            if ports is None or len(ports) == 0:
                return "ALLOWED"

            if any(port_matches(ps, dst_port, protocol, port_resolve_pod)
                   for ps in ports):
                return "ALLOWED"

    return "DENIED"


def find_unprotected(pods, policies):
    """Identify pods not selected by any NetworkPolicy for each direction."""
    unprotected_ingress = []
    unprotected_egress = []

    for pod_key in sorted(pods):
        pod_info = pods[pod_key]
        has_ingress = False
        has_egress = False

        for pol in policies:
            if policy_selects_pod(pol, pod_info):
                ptypes = get_policy_types(pol)
                if "Ingress" in ptypes:
                    has_ingress = True
                if "Egress" in ptypes:
                    has_egress = True

        if not has_ingress:
            unprotected_ingress.append(pod_key)
        if not has_egress:
            unprotected_egress.append(pod_key)

    return {
        "unprotected_ingress": sorted(unprotected_ingress),
        "unprotected_egress": sorted(unprotected_egress),
    }


def generate_graph(pods, namespaces, policies):
    """Generate DOT format connectivity graph."""
    check_ports = [80, 443, 5432, 8080, 9090, 9200]
    protocol = "TCP"

    lines = ["digraph K8sConnectivity {"]
    lines.append("  rankdir=LR;")
    lines.append("  node [shape=box];")

    for pod_key in sorted(pods):
        lines.append(f'  "{pod_key}";')

    for src_key in sorted(pods):
        for dst_key in sorted(pods):
            if src_key == dst_key:
                continue
            allowed_ports = []
            for port in check_ports:
                result = check_connectivity(
                    src_key, dst_key, port, protocol,
                    pods, namespaces, policies
                )
                if result == "ALLOWED":
                    allowed_ports.append(f"{port}/{protocol}")
            if allowed_ports:
                label = ",".join(allowed_ports)
                lines.append(f'  "{src_key}" -> "{dst_key}" [label="{label}"];')

    lines.append("}")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python3 analyzer.py <command> [args...]\n"
            "Commands:\n"
            "  query <src_ns/pod> <dst_ns/pod> <port> [protocol]\n"
            "  query-ip <src_ip> <dst_ns/pod> <port> [protocol]\n"
            "  unprotected\n"
            "  graph",
            file=sys.stderr,
        )
        sys.exit(1)

    command = sys.argv[1]

    resources = load_manifests()
    namespaces, pods, policies = build_index(resources)

    if command == "query":
        if len(sys.argv) < 5:
            print("Usage: query <src> <dst> <port> [protocol]", file=sys.stderr)
            sys.exit(1)

        src = sys.argv[2]
        dst = sys.argv[3]
        port = int(sys.argv[4])
        protocol = sys.argv[5] if len(sys.argv) > 5 else "TCP"

        if src not in pods:
            print(f"Error: pod '{src}' not found", file=sys.stderr)
            sys.exit(1)
        if dst not in pods:
            print(f"Error: pod '{dst}' not found", file=sys.stderr)
            sys.exit(1)

        print(check_connectivity(src, dst, port, protocol,
                                 pods, namespaces, policies))

    elif command == "query-ip":
        if len(sys.argv) < 5:
            print("Usage: query-ip <src_ip> <dst_ns/pod> <port> [protocol]",
                  file=sys.stderr)
            sys.exit(1)

        src_ip = sys.argv[2]
        dst = sys.argv[3]
        port = int(sys.argv[4])
        protocol = sys.argv[5] if len(sys.argv) > 5 else "TCP"

        if dst not in pods:
            print(f"Error: pod '{dst}' not found", file=sys.stderr)
            sys.exit(1)

        print(check_ip_ingress(src_ip, dst, port, protocol,
                               pods, namespaces, policies))

    elif command == "unprotected":
        result = find_unprotected(pods, policies)
        print(json.dumps(result, indent=2, sort_keys=True))

    elif command == "graph":
        print(generate_graph(pods, namespaces, policies))

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
