#!/usr/bin/env python3
"""
Evaluate three Kubernetes security proposals and synthesize a compliant configuration.

"""

import json
import yaml
import os
import glob
import shutil

PROPOSALS = {
    "proposal_a": "/app/proposal-a",
    "proposal_b": "/app/proposal-b",
    "proposal_c": "/app/proposal-c",
}
FINAL_DIR = "/app/final-config"
REPORT_PATH = "/app/evaluation-report.json"
REQUIRED_NAMESPACES = {"prod-frontend", "prod-backend", "prod-data", "monitoring"}


def load_all_manifests(directory):
    manifests = []
    for yaml_file in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        with open(yaml_file) as f:
            for doc in yaml.safe_load_all(f):
                if doc is not None:
                    manifests.append(doc)
    return manifests


def get_resources(manifests, kind, namespace=None, name=None):
    results = []
    for m in manifests:
        if m.get("kind") != kind:
            continue
        meta = m.get("metadata", {})
        if namespace is not None and meta.get("namespace") != namespace:
            continue
        if name is not None and meta.get("name") != name:
            continue
        results.append(m)
    return results


def parse_memory(value):
    value = str(value)
    units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3}
    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * multiplier
    return float(value)


def parse_cpu(value):
    value = str(value)
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


# =============================================
# Evaluation checks for each category
# =============================================


def check_default_deny(manifests):
    ns_names = {m["metadata"]["name"] for m in get_resources(manifests, "Namespace")}
    deny_policies = get_resources(manifests, "NetworkPolicy", name="default-deny-ingress")
    deny_ns = set()
    for p in deny_policies:
        spec = p.get("spec", {})
        ps = spec.get("podSelector")
        pt = spec.get("policyTypes", [])
        ingress = spec.get("ingress")
        if (ps is not None and (ps == {} or ps == {"matchLabels": {}})
                and "Ingress" in pt and (ingress is None or ingress == [])):
            deny_ns.add(p["metadata"]["namespace"])
    return ns_names <= deny_ns


def check_cross_namespace_selectors(manifests):
    all_policies = get_resources(manifests, "NetworkPolicy")
    for policy in all_policies:
        if policy["metadata"].get("name") == "default-deny-ingress":
            continue
        for rule in policy["spec"].get("ingress", []) or []:
            from_entries = rule.get("from", [])
            ns_sel_entries = [e for e in from_entries if "namespaceSelector" in e]
            for entry in ns_sel_entries:
                ns_labels = entry.get("namespaceSelector", {}).get("matchLabels", {})
                if not ns_labels:
                    continue
                if "podSelector" not in entry:
                    return False
                if ns_labels.get("name") == "monitoring":
                    pod_labels = entry.get("podSelector", {}).get("matchLabels", {})
                    if pod_labels.get("app") != "prometheus":
                        return False
                if ns_labels.get("name") == "prod-frontend":
                    pod_labels = entry.get("podSelector", {}).get("matchLabels", {})
                    if pod_labels.get("app") != "react-app":
                        return False
    return True


def check_egress_policies(manifests):
    egress_policies = get_resources(
        manifests, "NetworkPolicy", namespace="prod-data",
        name="restrict-postgres-egress"
    )
    if len(egress_policies) == 0:
        return False
    for policy in egress_policies:
        pt = policy["spec"].get("policyTypes", [])
        if "Egress" not in pt:
            return False
        if "Ingress" in pt:
            return False
    return True


def check_rbac_scoping(manifests):
    crbs = get_resources(manifests, "ClusterRoleBinding")
    for crb in crbs:
        for subject in crb.get("subjects", []):
            if (subject.get("name") == "deploy-bot"
                    and subject.get("kind") == "ServiceAccount"):
                return False
    rbs = get_resources(manifests, "RoleBinding", namespace="prod-backend")
    found = False
    for rb in rbs:
        for subject in rb.get("subjects", []):
            if (subject.get("name") == "deploy-bot"
                    and subject.get("kind") == "ServiceAccount"):
                found = True
    return found


def check_rbac_least_privilege(manifests):
    roles = get_resources(manifests, "Role") + get_resources(manifests, "ClusterRole")
    for role in roles:
        for rule in role.get("rules", []):
            if "secrets" in rule.get("resources", []):
                if "*" in rule.get("verbs", []):
                    return False
    return True


def check_resource_quotas(manifests):
    expected = {
        "prod-frontend": {"cpu": "4", "memory": "4Gi", "pods": "20"},
        "prod-backend": {"cpu": "8", "memory": "8Gi", "pods": "30"},
        "prod-data": {"cpu": "16", "memory": "32Gi", "pods": "10"},
        "monitoring": {"cpu": "4", "memory": "8Gi", "pods": "15"},
    }
    quotas = get_resources(manifests, "ResourceQuota")
    quota_ns = {}
    for q in quotas:
        ns = q["metadata"]["namespace"]
        quota_ns[ns] = q["spec"]["hard"]
    for ns, exp in expected.items():
        if ns not in quota_ns:
            return False
        hard = quota_ns[ns]
        if str(hard.get("cpu")) != exp["cpu"]:
            return False
        if hard.get("memory") != exp["memory"]:
            return False
        if str(hard.get("pods")) != exp["pods"]:
            return False
    return True


def check_limit_ranges(manifests):
    lrs = get_resources(manifests, "LimitRange")
    if len(lrs) < 4:
        return False
    for lr in lrs:
        for limit in lr["spec"]["limits"]:
            if limit.get("type") != "Container":
                continue
            default = limit.get("default", {})
            max_vals = limit.get("max", {})
            if "memory" in default and "memory" in max_vals:
                if parse_memory(default["memory"]) > parse_memory(max_vals["memory"]):
                    return False
            if "cpu" in default and "cpu" in max_vals:
                if parse_cpu(default["cpu"]) > parse_cpu(max_vals["cpu"]):
                    return False
    return True


def check_security_contexts(manifests):
    deployments = get_resources(manifests, "Deployment")
    nginx_ok = False
    for deploy in deployments:
        containers = deploy["spec"]["template"]["spec"]["containers"]
        for container in containers:
            sc = container.get("securityContext", {})
            if sc.get("privileged") is True:
                return False
            if container["name"] == "nginx":
                caps = sc.get("capabilities", {})
                if "NET_BIND_SERVICE" in caps.get("add", []):
                    nginx_ok = True
    return nginx_ok


CHECKERS = {
    "default_deny": check_default_deny,
    "cross_namespace_selectors": check_cross_namespace_selectors,
    "egress_policies": check_egress_policies,
    "rbac_scoping": check_rbac_scoping,
    "rbac_least_privilege": check_rbac_least_privilege,
    "resource_quotas": check_resource_quotas,
    "limit_ranges": check_limit_ranges,
    "security_contexts": check_security_contexts,
}


def evaluate_proposals():
    """Evaluate each proposal against all categories."""
    report = {}
    for name, path in PROPOSALS.items():
        manifests = load_all_manifests(path)
        report[name] = {}
        for cat, checker in CHECKERS.items():
            passes = checker(manifests)
            report[name][cat] = "pass" if passes else "fail"
            status = "PASS" if passes else "FAIL"
            print(f"  {name}.{cat}: {status}")
    return report


def synthesize_final_config():
    """
    Synthesize the correct configuration by taking the best elements
    from each proposal and correcting defects.

    Analysis:
    - Network policies (default deny + AND selectors): proposal_a is correct
    - Egress policies: proposal_b has correct policyTypes
    - RBAC: proposal_a has both correct scoping and least-privilege
    - Resource management: proposal_b has all correct values
    - Security contexts: proposal_b has correct nginx config
    """
    os.makedirs(FINAL_DIR, exist_ok=True)

    # Take deployments from proposal_b (correct security contexts)
    b_manifests = load_all_manifests(PROPOSALS["proposal_b"])
    namespaces = get_resources(b_manifests, "Namespace")
    deployments = get_resources(b_manifests, "Deployment")
    deploy_docs = namespaces + deployments
    write_yaml(os.path.join(FINAL_DIR, "deployments.yaml"), deploy_docs)
    print("  Wrote deployments.yaml from proposal_b (correct security contexts)")

    # Take network policies from proposal_a (correct AND selectors + all default-deny)
    # but add egress policy from proposal_b (correct policyTypes)
    a_manifests = load_all_manifests(PROPOSALS["proposal_a"])
    netpols_a = get_resources(a_manifests, "NetworkPolicy")

    # Get egress policy from proposal_b
    egress_from_b = get_resources(
        b_manifests, "NetworkPolicy",
        namespace="prod-data", name="restrict-postgres-egress"
    )

    netpol_docs = netpols_a + egress_from_b
    write_yaml(os.path.join(FINAL_DIR, "network-policies.yaml"), netpol_docs)
    print("  Wrote network-policies.yaml (proposal_a selectors + proposal_b egress)")

    # Take RBAC from proposal_a (correct scoping + least-privilege)
    rbac_resources = (
        get_resources(a_manifests, "ServiceAccount")
        + get_resources(a_manifests, "ClusterRoleBinding")
        + get_resources(a_manifests, "RoleBinding")
        + get_resources(a_manifests, "Role")
        + get_resources(a_manifests, "ClusterRole")
    )
    write_yaml(os.path.join(FINAL_DIR, "rbac.yaml"), rbac_resources)
    print("  Wrote rbac.yaml from proposal_a (correct scoping + least-privilege)")

    # Take resource management from proposal_b (all correct values)
    res_mgmt = (
        get_resources(b_manifests, "ResourceQuota")
        + get_resources(b_manifests, "LimitRange")
    )
    write_yaml(os.path.join(FINAL_DIR, "resource-management.yaml"), res_mgmt)
    print("  Wrote resource-management.yaml from proposal_b (correct values)")


def write_yaml(path, docs):
    with open(path, "w") as f:
        yaml.dump_all(docs, f, default_flow_style=False, sort_keys=False)


def main():
    print("=== Evaluating proposals against security requirements ===")
    print()
    report = evaluate_proposals()
    print()

    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"Evaluation report written to {REPORT_PATH}")
    print()

    print("=== Synthesizing compliant configuration ===")
    print()
    synthesize_final_config()
    print()
    print("Final configuration written to /app/final-config/")


if __name__ == "__main__":
    main()
