"""
Create RBAC manifests per requirements.

"""

import yaml
import os

RBAC_DIR = "/app/rbac"

# Role for deployment, service, configmap management + pod viewing in production
production_role = {
    "apiVersion": "rbac.authorization.k8s.io/v1",
    "kind": "Role",
    "metadata": {
        "name": "ci-deployer-role",
        "namespace": "production",
    },
    "rules": [
        {
            "apiGroups": ["apps"],
            "resources": ["deployments"],
            "verbs": ["create", "update", "delete"],
        },
        {
            "apiGroups": [""],
            "resources": ["services", "configmaps"],
            "verbs": ["create", "update", "delete"],
        },
        {
            "apiGroups": [""],
            "resources": ["pods"],
            "verbs": ["get", "list"],
        },
        {
            "apiGroups": [""],
            "resources": ["pods/log"],
            "verbs": ["get"],
        },
    ],
}

# RoleBinding in production
production_role_binding = {
    "apiVersion": "rbac.authorization.k8s.io/v1",
    "kind": "RoleBinding",
    "metadata": {
        "name": "ci-deployer-rolebinding",
        "namespace": "production",
    },
    "subjects": [
        {
            "kind": "ServiceAccount",
            "name": "ci-deployer",
            "namespace": "ci-cd",
        }
    ],
    "roleRef": {
        "kind": "Role",
        "name": "ci-deployer-role",
        "apiGroup": "rbac.authorization.k8s.io",
    },
}

# ClusterRole for namespace management
namespace_cluster_role = {
    "apiVersion": "rbac.authorization.k8s.io/v1",
    "kind": "ClusterRole",
    "metadata": {
        "name": "ci-namespace-manager",
    },
    "rules": [
        {
            "apiGroups": [""],
            "resources": ["namespaces"],
            "verbs": ["create", "delete"],
        },
    ],
}

# ClusterRoleBinding
namespace_cluster_role_binding = {
    "apiVersion": "rbac.authorization.k8s.io/v1",
    "kind": "ClusterRoleBinding",
    "metadata": {
        "name": "ci-namespace-manager-binding",
    },
    "subjects": [
        {
            "kind": "ServiceAccount",
            "name": "ci-deployer",
            "namespace": "ci-cd",
        }
    ],
    "roleRef": {
        "kind": "ClusterRole",
        "name": "ci-namespace-manager",
        "apiGroup": "rbac.authorization.k8s.io",
    },
}

# Write all RBAC resources
docs = [
    production_role,
    production_role_binding,
    namespace_cluster_role,
    namespace_cluster_role_binding,
]

with open(os.path.join(RBAC_DIR, "rbac-manifests.yaml"), "w") as f:
    yaml.dump_all(docs, f, default_flow_style=False, sort_keys=False)

print("  Created RBAC manifests in /app/rbac/rbac-manifests.yaml")
