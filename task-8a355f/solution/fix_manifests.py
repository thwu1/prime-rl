#!/usr/bin/env python3
"""
Fix all Kubernetes cluster security misconfigurations.

"""

import yaml
import os

CLUSTER_CONFIG_DIR = "/app/cluster-config"


def load_yaml_file(path):
    with open(path) as f:
        docs = list(yaml.safe_load_all(f))
    return [d for d in docs if d is not None]


def write_yaml_file(path, docs):
    with open(path, "w") as f:
        yaml.dump_all(docs, f, default_flow_style=False, sort_keys=False)


def fix_netpol_prod_backend():
    """
    Fix bugs 1 and 2:
    1. OR-instead-of-AND selector for prod-frontend access to api-server.
       The original has separate from entries (namespaceSelector and podSelector
       as separate list items = OR). Must combine into single entry (AND).
    2. Missing podSelector for monitoring access — allows all monitoring pods
       instead of just prometheus.
    """
    path = os.path.join(CLUSTER_CONFIG_DIR, "netpol-prod-backend.yaml")
    docs = load_yaml_file(path)

    for doc in docs:
        if (
            doc.get("kind") == "NetworkPolicy"
            and doc["metadata"].get("name") == "allow-api-server-ingress"
        ):
            doc["spec"]["ingress"] = [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"name": "prod-frontend"}
                            },
                            "podSelector": {
                                "matchLabels": {"app": "react-app"}
                            },
                        }
                    ],
                    "ports": [{"port": 8443, "protocol": "TCP"}],
                },
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {"name": "monitoring"}
                            },
                            "podSelector": {
                                "matchLabels": {"app": "prometheus"}
                            },
                        }
                    ],
                    "ports": [{"port": 9090, "protocol": "TCP"}],
                },
                {
                    "from": [
                        {"podSelector": {"matchLabels": {"app": "worker"}}}
                    ],
                    "ports": [{"port": 8443, "protocol": "TCP"}],
                },
            ]

    write_yaml_file(path, docs)
    print("Fixed: netpol-prod-backend.yaml (AND selectors + prometheus restriction)")


def fix_netpol_prod_data():
    """
    Fix bug 3: restrict-postgres-egress has policyTypes: ["Ingress"] but contains
    egress rules. The egress rules are silently ignored because policyTypes doesn't
    include "Egress". Fix: change policyTypes to ["Egress"].
    """
    path = os.path.join(CLUSTER_CONFIG_DIR, "netpol-prod-data.yaml")
    docs = load_yaml_file(path)

    for doc in docs:
        if (
            doc.get("kind") == "NetworkPolicy"
            and doc["metadata"].get("name") == "restrict-postgres-egress"
        ):
            doc["spec"]["policyTypes"] = ["Egress"]

    write_yaml_file(path, docs)
    print("Fixed: netpol-prod-data.yaml (policyTypes Egress)")


def fix_netpol_monitoring():
    """
    Fix bug 4: monitoring namespace is missing a default-deny-ingress
    NetworkPolicy. Add one.
    """
    path = os.path.join(CLUSTER_CONFIG_DIR, "netpol-monitoring.yaml")
    docs = load_yaml_file(path)

    default_deny = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "default-deny-ingress", "namespace": "monitoring"},
        "spec": {"podSelector": {}, "policyTypes": ["Ingress"]},
    }
    docs.insert(0, default_deny)

    write_yaml_file(path, docs)
    print("Fixed: netpol-monitoring.yaml (added default-deny-ingress)")


def fix_rbac():
    """
    Fix bugs 5 and 6:
    5. deploy-bot uses ClusterRoleBinding — must be namespaced RoleBinding.
    6. data-reader-secrets Role uses verbs: ["*"] on secrets — must be ["get", "list"].
    """
    path = os.path.join(CLUSTER_CONFIG_DIR, "rbac.yaml")
    docs = load_yaml_file(path)

    new_docs = []
    for doc in docs:
        if (
            doc.get("kind") == "ClusterRoleBinding"
            and doc["metadata"].get("name") == "deploy-bot-edit"
        ):
            # Convert to namespaced RoleBinding
            rb = {
                "apiVersion": "rbac.authorization.k8s.io/v1",
                "kind": "RoleBinding",
                "metadata": {
                    "name": "deploy-bot-edit",
                    "namespace": "prod-backend",
                },
                "roleRef": {
                    "apiGroup": "rbac.authorization.k8s.io",
                    "kind": "ClusterRole",
                    "name": "edit",
                },
                "subjects": [
                    {
                        "kind": "ServiceAccount",
                        "name": "deploy-bot",
                        "namespace": "prod-backend",
                    }
                ],
            }
            new_docs.append(rb)
        elif (
            doc.get("kind") == "Role"
            and doc["metadata"].get("name") == "data-reader-secrets"
        ):
            # Replace wildcard verbs with explicit verbs
            for rule in doc.get("rules", []):
                if "secrets" in rule.get("resources", []):
                    rule["verbs"] = ["get", "list"]
            new_docs.append(doc)
        else:
            new_docs.append(doc)

    write_yaml_file(path, new_docs)
    print("Fixed: rbac.yaml (RoleBinding scope + explicit verbs)")


def fix_resource_management():
    """
    Fix bugs 7 and 8:
    7. prod-frontend LimitRange has default memory (1Gi) > max memory (512Mi).
       Per requirements: default=512Mi, max=1Gi.
    8. monitoring namespace is missing a ResourceQuota.
    """
    path = os.path.join(CLUSTER_CONFIG_DIR, "resource-management.yaml")
    docs = load_yaml_file(path)

    for doc in docs:
        if (
            doc.get("kind") == "LimitRange"
            and doc["metadata"].get("name") == "prod-frontend-limits"
        ):
            for limit in doc["spec"]["limits"]:
                if limit["type"] == "Container":
                    limit["default"]["memory"] = "512Mi"
                    limit["max"]["memory"] = "1Gi"

    # Add missing monitoring ResourceQuota
    monitoring_quota = {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {"name": "monitoring-quota", "namespace": "monitoring"},
        "spec": {"hard": {"cpu": "4", "memory": "8Gi", "pods": "15"}},
    }
    docs.append(monitoring_quota)

    write_yaml_file(path, docs)
    print("Fixed: resource-management.yaml (LimitRange bounds + monitoring quota)")


def fix_deployments():
    """
    Fix bug 9: nginx deployment uses privileged: true instead of the specific
    NET_BIND_SERVICE capability needed for port 80.
    """
    path = os.path.join(CLUSTER_CONFIG_DIR, "deployments.yaml")
    docs = load_yaml_file(path)

    for doc in docs:
        if (
            doc.get("kind") == "Deployment"
            and doc["metadata"].get("name") == "nginx"
            and doc["metadata"].get("namespace") == "prod-frontend"
        ):
            containers = doc["spec"]["template"]["spec"]["containers"]
            for container in containers:
                if container["name"] == "nginx":
                    container["securityContext"] = {
                        "privileged": False,
                        "capabilities": {"add": ["NET_BIND_SERVICE"]},
                    }

    write_yaml_file(path, docs)
    print("Fixed: deployments.yaml (privileged -> NET_BIND_SERVICE)")


def main():
    print("Analyzing cluster-config manifests against security requirements...")
    print()

    fix_netpol_prod_backend()
    fix_netpol_prod_data()
    fix_netpol_monitoring()
    fix_rbac()
    fix_resource_management()
    fix_deployments()

    print()
    print("All 9 security violations remediated successfully.")


if __name__ == "__main__":
    main()
