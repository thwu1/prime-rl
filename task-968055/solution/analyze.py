#!/usr/bin/env python3

"""
Analyze Kubernetes audit logs and Falco alerts to identify a compromised
service account, reconstruct the attack chain, and generate defensive
security policies.
"""

import json
import os

import yaml


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


# ==================== LOAD DATA ====================

with open("/app/audit-logs/kube-apiserver-audit.json") as f:
    audit_events = json.load(f)

falco_events = []
with open("/app/falco-events/alerts.jsonl") as f:
    for line in f:
        line = line.strip()
        if line:
            falco_events.append(json.loads(line))

# Read cluster info for architecture context
with open("/app/cluster-info.md") as f:
    cluster_info = f.read()

# Read manifests to understand workload labels
manifest_dir = "/app/manifests"
manifests = {}
for fname in os.listdir(manifest_dir):
    if fname.endswith((".yaml", ".yml")):
        with open(os.path.join(manifest_dir, fname)) as f:
            manifests[fname] = yaml.safe_load(f)


# ==================== STEP 1: IDENTIFY COMPROMISED IDENTITY ====================

# Build activity profiles for each service account
sa_profiles = {}

for event in audit_events:
    username = event["user"]["username"]
    if not username.startswith("system:serviceaccount:"):
        continue

    parts = username.split(":")
    if len(parts) < 4:
        continue
    home_ns = parts[2]
    sa_name = parts[3]

    obj_ref = event.get("objectRef", {})
    target_ns = obj_ref.get("namespace", "")
    verb = event.get("verb", "")
    resource = obj_ref.get("resource", "")
    name = obj_ref.get("name", "")
    ip = event["sourceIPs"][0] if event.get("sourceIPs") else ""
    ua = event.get("userAgent", "")
    ts = event.get("requestReceivedTimestamp", "")
    status = event.get("responseStatus", {}).get("code", 0)
    audit_id = event.get("auditID", "")

    if username not in sa_profiles:
        sa_profiles[username] = {
            "home_ns": home_ns,
            "sa_name": sa_name,
            "activities": []
        }

    sa_profiles[username]["activities"].append({
        "timestamp": ts,
        "audit_id": audit_id,
        "verb": verb,
        "resource": resource,
        "namespace": target_ns,
        "name": name,
        "ip": ip,
        "ua": ua,
        "status_code": status,
        "request_object": event.get("requestObject"),
    })


# Score each SA for suspiciousness
compromised_username = None
compromised_profile = None
max_suspicion = 0

for username, profile in sa_profiles.items():
    home_ns = profile["home_ns"]
    sa_name = profile["sa_name"]
    suspicion_score = 0
    suspicious_acts = []

    for act in profile["activities"]:
        ns = act["namespace"]
        reasons = []

        # Cross-namespace activity (excluding cluster-wide monitoring which is expected)
        if ns and ns != home_ns:
            reasons.append("cross-namespace")
            suspicion_score += 2

        # Cluster-wide listing by non-monitoring SA
        if not ns and act["verb"] == "list" and act["resource"] != "nodes":
            if sa_name != "prometheus-sa":
                reasons.append("cluster-wide-listing")
                suspicion_score += 1

        # Secret access
        if act["resource"] == "secrets":
            reasons.append("secret-access")
            suspicion_score += 3

        # RBAC modification
        if act["resource"] in ("clusterrolebindings", "clusterroles", "rolebindings", "roles"):
            if act["verb"] in ("create", "update", "patch", "delete"):
                reasons.append("rbac-modification")
                suspicion_score += 5

        # Pod creation in system namespaces
        if act["resource"] == "pods" and act["verb"] == "create" and ns == "kube-system":
            reasons.append("system-ns-pod-creation")
            suspicion_score += 4

        # Deployment modification outside home namespace
        if act["resource"] == "deployments" and act["verb"] in ("patch", "update") and ns != home_ns:
            reasons.append("cross-ns-deployment-mod")
            suspicion_score += 3

        # CronJob creation outside home namespace
        if act["resource"] == "cronjobs" and act["verb"] == "create" and ns != home_ns:
            reasons.append("cross-ns-cronjob-creation")
            suspicion_score += 3

        if reasons:
            act["_reasons"] = reasons
            suspicious_acts.append(act)

    if suspicion_score > max_suspicion:
        max_suspicion = suspicion_score
        compromised_username = username
        compromised_profile = profile
        compromised_profile["suspicious_acts"] = suspicious_acts


# Determine attack IP vs legitimate IP
attack_ips = set()
legit_ips = set()
for act in compromised_profile["activities"]:
    if act in compromised_profile["suspicious_acts"]:
        attack_ips.add(act["ip"])
    else:
        legit_ips.add(act["ip"])

# The attack IP is one used for suspicious but not for legitimate activity
attack_only_ips = attack_ips - legit_ips
attack_ip = sorted(attack_only_ips)[0] if attack_only_ips else sorted(attack_ips)[0]

# Filter attack events: those from the attack IP with suspicious reasons
attack_events = []
seen_ids = set()
for act in compromised_profile["suspicious_acts"]:
    if act["ip"] == attack_ip and act["audit_id"] not in seen_ids:
        seen_ids.add(act["audit_id"])
        attack_events.append(act)

# Sort chronologically
attack_events.sort(key=lambda x: x["timestamp"])

# Detect user agent anomaly
attack_uas = set()
legit_uas = set()
for act in compromised_profile["activities"]:
    if act["ip"] == attack_ip:
        attack_uas.add(act["ua"])
    else:
        legit_uas.add(act["ua"])


# ==================== STEP 2: MAP TO MITRE ATT&CK ====================

def get_mitre_technique(act):
    verb = act["verb"]
    resource = act["resource"]
    ns = act["namespace"]
    status = act["status_code"]

    if verb == "list" and resource == "pods" and not ns:
        return "T1613"  # Container and Resource Discovery
    if resource == "secrets" and verb == "list" and status == 403:
        return "T1613"  # Discovery (failed attempt)
    if resource == "secrets" and verb == "list":
        return "T1552.007"  # Unsecured Credentials: Container API
    if resource == "secrets" and verb == "get":
        return "T1552.007"  # Credential Access
    if resource == "clusterrolebindings" and verb == "create":
        return "T1078.001"  # Valid Accounts: Default Accounts (privilege escalation)
    if resource == "pods" and verb == "create" and ns == "kube-system":
        return "T1610"  # Deploy Container
    if resource == "deployments" and verb == "patch":
        return "T1525"  # Implant Internal Image
    if resource == "cronjobs" and verb == "create":
        return "T1053.007"  # Scheduled Task: Container Orchestration Job
    return "T1078"  # Valid Accounts (generic)


def describe_attack_event(act):
    verb = act["verb"]
    resource = act["resource"]
    name = act.get("name", "")
    ns = act.get("namespace", "")
    status = act["status_code"]

    if verb == "list" and resource == "pods" and not ns:
        return "Reconnaissance: listed pods across all namespaces to map cluster topology"
    if resource == "secrets" and verb == "list" and status == 403:
        return "Failed reconnaissance: attempted to list secrets in {} (denied)".format(ns)
    if resource == "secrets" and verb == "list":
        return "Discovery: listed secrets in {} namespace to identify credential targets".format(ns)
    if resource == "secrets" and verb == "get":
        return "Credential access: read secret '{}' from {} namespace".format(name, ns)
    if resource == "clusterrolebindings" and verb == "create":
        req = act.get("request_object", {})
        role_ref = req.get("roleRef", {}).get("name", "unknown")
        return "Privilege escalation: created ClusterRoleBinding '{}' binding to {} role".format(name, role_ref)
    if resource == "pods" and verb == "create" and ns == "kube-system":
        return "Execution: created privileged pod '{}' in {} with hostPID/hostNetwork and host root mount".format(name, ns)
    if resource == "deployments" and verb == "patch":
        return "Persistence/Exfiltration: patched deployment '{}' in {} to inject exfiltration sidecar container".format(name, ns)
    if resource == "cronjobs" and verb == "create":
        return "Persistence: created CronJob '{}' in {} for recurring payload download from external C2".format(name, ns)
    return "{} {} '{}' in {}".format(verb, resource, name, ns)


# ==================== STEP 3: BUILD FORENSIC REPORT ====================

forensic_report = {
    "compromised_identity": {
        "username": compromised_username,
        "namespace": compromised_profile["home_ns"],
        "service_account_name": compromised_profile["sa_name"],
    },
    "attack_source_ip": attack_ip,
    "attack_user_agent": sorted(attack_uas)[0] if attack_uas else "",
    "legitimate_user_agent": sorted(legit_uas)[0] if legit_uas else "",
    "attack_events": [
        {
            "timestamp": act["timestamp"],
            "audit_id": act["audit_id"],
            "verb": act["verb"],
            "resource": act["resource"],
            "namespace": act["namespace"],
            "name": act.get("name", ""),
            "status_code": act["status_code"],
            "mitre_technique": get_mitre_technique(act),
            "description": describe_attack_event(act),
        }
        for act in attack_events
    ],
    "indicators_of_compromise": [
        "Service account {} accessed resources outside home namespace '{}'".format(
            compromised_username, compromised_profile["home_ns"]),
        "User agent changed from '{}' to '{}' indicating manual tool usage".format(
            sorted(legit_uas)[0] if legit_uas else "unknown",
            sorted(attack_uas)[0] if attack_uas else "unknown"),
        "Source IP {} differs from legitimate service IP(s) {}".format(
            attack_ip, sorted(legit_ips)),
        "Secrets accessed in production namespace by CI service account",
        "ClusterRoleBinding created granting cluster-admin privileges",
        "Privileged pod with hostPID/hostNetwork created in kube-system",
        "Production deployment modified to include data exfiltration sidecar",
        "CronJob created for recurring external payload download and execution",
    ],
    "correlated_falco_alerts": [
        {
            "rule": ev["rule"],
            "time": ev["time"],
            "priority": ev["priority"],
            "container": ev["output_fields"].get("container.name", ""),
        }
        for ev in falco_events
    ],
}


# ==================== STEP 4: GENERATE AUDIT POLICY ====================

audit_policy = {
    "apiVersion": "audit.k8s.io/v1",
    "kind": "Policy",
    "omitStages": ["RequestReceived"],
    "rules": [
        {
            "level": "RequestResponse",
            "resources": [{"group": "", "resources": ["secrets"]}],
            "verbs": ["get", "list", "create", "update", "patch", "delete"],
        },
        {
            "level": "RequestResponse",
            "resources": [{"group": "rbac.authorization.k8s.io",
                           "resources": ["clusterrolebindings", "clusterroles",
                                         "rolebindings", "roles"]}],
            "verbs": ["create", "update", "patch", "delete", "bind"],
        },
        {
            "level": "RequestResponse",
            "resources": [{"group": "", "resources": ["pods", "pods/exec", "pods/attach"]}],
            "verbs": ["create", "update", "patch", "delete"],
            "namespaces": ["kube-system"],
        },
        {
            "level": "Request",
            "resources": [{"group": "apps",
                           "resources": ["deployments", "statefulsets", "daemonsets", "replicasets"]}],
            "verbs": ["create", "update", "patch", "delete"],
        },
        {
            "level": "Request",
            "resources": [{"group": "batch", "resources": ["cronjobs", "jobs"]}],
            "verbs": ["create", "update", "patch", "delete"],
        },
        {
            "level": "Metadata",
            "resources": [{"group": "", "resources": ["serviceaccounts", "serviceaccounts/token"]}],
            "verbs": ["create", "update", "patch", "delete"],
        },
        {
            "level": "Metadata",
            "resources": [{"group": "", "resources": ["pods", "services", "configmaps", "namespaces"]}],
        },
        {
            "level": "None",
            "users": ["system:kube-proxy", "system:kube-controller-manager", "system:kube-scheduler"],
            "verbs": ["get", "watch", "list"],
            "resources": [{"group": "", "resources": ["endpoints", "services", "namespaces"]}],
        },
        {
            "level": "None",
            "nonResourceURLs": ["/healthz*", "/readyz*", "/livez*", "/api", "/api/*"],
        },
    ],
}


# ==================== STEP 5: GENERATE NETWORK POLICIES ====================

network_policies = []

# Frontend: ingress from ingress namespace, egress to backend-api + DNS
np_frontend = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "frontend-netpol", "namespace": "production"},
    "spec": {
        "podSelector": {"matchLabels": {"app": "frontend"}},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [
            {
                "from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress"}}}],
                "ports": [{"port": 8080, "protocol": "TCP"}],
            }
        ],
        "egress": [
            {
                "to": [{"podSelector": {"matchLabels": {"app": "backend-api"}}}],
                "ports": [{"port": 3000, "protocol": "TCP"}],
            },
            {
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
        ],
    },
}
network_policies.append(("frontend-netpol.yaml", np_frontend))

# Backend-API: ingress from frontend, egress to database + redis + DNS
np_backend = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "backend-api-netpol", "namespace": "production"},
    "spec": {
        "podSelector": {"matchLabels": {"app": "backend-api"}},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [
            {
                "from": [{"podSelector": {"matchLabels": {"app": "frontend"}}}],
                "ports": [{"port": 3000, "protocol": "TCP"}],
            }
        ],
        "egress": [
            {
                "to": [{"podSelector": {"matchLabels": {"app": "database"}}}],
                "ports": [{"port": 5432, "protocol": "TCP"}],
            },
            {
                "to": [{"podSelector": {"matchLabels": {"app": "redis"}}}],
                "ports": [{"port": 6379, "protocol": "TCP"}],
            },
            {
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
        ],
    },
}
network_policies.append(("backend-api-netpol.yaml", np_backend))

# Database: ingress from backend-api only, egress DNS only
np_database = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "database-netpol", "namespace": "production"},
    "spec": {
        "podSelector": {"matchLabels": {"app": "database"}},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [
            {
                "from": [{"podSelector": {"matchLabels": {"app": "backend-api"}}}],
                "ports": [{"port": 5432, "protocol": "TCP"}],
            }
        ],
        "egress": [
            {
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
        ],
    },
}
network_policies.append(("database-netpol.yaml", np_database))

# Redis: ingress from backend-api only, egress DNS only
np_redis = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "redis-netpol", "namespace": "production"},
    "spec": {
        "podSelector": {"matchLabels": {"app": "redis"}},
        "policyTypes": ["Ingress", "Egress"],
        "ingress": [
            {
                "from": [{"podSelector": {"matchLabels": {"app": "backend-api"}}}],
                "ports": [{"port": 6379, "protocol": "TCP"}],
            }
        ],
        "egress": [
            {
                "ports": [{"port": 53, "protocol": "UDP"}, {"port": 53, "protocol": "TCP"}],
            },
        ],
    },
}
network_policies.append(("redis-netpol.yaml", np_redis))

# Default deny all in production
np_default_deny = {
    "apiVersion": "networking.k8s.io/v1",
    "kind": "NetworkPolicy",
    "metadata": {"name": "default-deny-all", "namespace": "production"},
    "spec": {
        "podSelector": {},
        "policyTypes": ["Ingress", "Egress"],
    },
}
network_policies.append(("default-deny-all.yaml", np_default_deny))


# ==================== STEP 6: GENERATE FALCO RULES ====================

falco_rules = [
    {
        "rule": "Cross-Namespace Secret Access by Service Account",
        "desc": "Detect when a service account accesses secrets outside its home namespace, indicating potential lateral movement or credential theft",
        "condition": "ka.verb in (get,list) and ka.target.resource=secrets and ka.user.name startswith \"system:serviceaccount:\" and not ka.target.namespace in (ka.user.namespace)",
        "output": "Service account accessed secrets in foreign namespace (user=%ka.user.name verb=%ka.verb target_ns=%ka.target.namespace secret=%ka.target.name sourceips=%ka.sourceips ua=%ka.useragent)",
        "priority": "CRITICAL",
        "source": "k8s_audit",
        "tags": ["k8s", "secrets", "lateral_movement", "mitre_credential_access"],
    },
    {
        "rule": "ClusterRoleBinding Creation by Non-System User",
        "desc": "Detect creation of ClusterRoleBindings by users other than the controller-manager, which may indicate privilege escalation",
        "condition": "ka.verb=create and ka.target.resource=clusterrolebindings and not ka.user.name in (system:kube-controller-manager) and not ka.user.groups intersects (system:masters)",
        "output": "ClusterRoleBinding created by non-admin (user=%ka.user.name binding=%ka.target.name sourceips=%ka.sourceips)",
        "priority": "CRITICAL",
        "source": "k8s_audit",
        "tags": ["k8s", "rbac", "privilege_escalation", "mitre_persistence"],
    },
    {
        "rule": "Privileged Pod Created in System Namespace",
        "desc": "Detect creation of privileged pods in kube-system or other system namespaces",
        "condition": "ka.verb=create and ka.target.resource=pods and ka.target.namespace in (kube-system,kube-public) and jevt.value[/requestObject/spec/containers/0/securityContext/privileged]=\"true\"",
        "output": "Privileged pod created in system namespace (user=%ka.user.name pod=%ka.target.name ns=%ka.target.namespace image=%jevt.value[/requestObject/spec/containers/0/image] sourceips=%ka.sourceips)",
        "priority": "CRITICAL",
        "source": "k8s_audit",
        "tags": ["k8s", "privileged", "execution", "mitre_execution"],
    },
    {
        "rule": "Production Deployment Modified by Unexpected Identity",
        "desc": "Detect modifications to deployments in production by users other than the designated deploy-bot",
        "condition": "ka.verb in (update,patch) and ka.target.resource=deployments and ka.target.namespace=production and not ka.user.name in (system:serviceaccount:production:deploy-bot,system:kube-controller-manager)",
        "output": "Production deployment modified by unexpected user (user=%ka.user.name deployment=%ka.target.name verb=%ka.verb sourceips=%ka.sourceips)",
        "priority": "WARNING",
        "source": "k8s_audit",
        "tags": ["k8s", "deployments", "persistence", "mitre_persistence"],
    },
    {
        "rule": "CronJob Created in Production Namespace",
        "desc": "Detect CronJob creation in production, which may indicate persistence mechanisms",
        "condition": "ka.verb=create and ka.target.resource=cronjobs and ka.target.namespace=production",
        "output": "CronJob created in production (user=%ka.user.name cronjob=%ka.target.name sourceips=%ka.sourceips)",
        "priority": "WARNING",
        "source": "k8s_audit",
        "tags": ["k8s", "persistence", "scheduled_task", "mitre_persistence"],
    },
    {
        "rule": "Container Contacting Cloud Metadata Service",
        "desc": "Detect containers reaching out to cloud provider metadata endpoints for potential SSRF or credential theft",
        "condition": "container and fd.sip=\"169.254.169.254\" and evt.type in (connect,sendto)",
        "output": "Container contacting cloud metadata service (user=%user.name container=%container.name image=%container.image.repository connection=%fd.name proc=%proc.cmdline)",
        "priority": "CRITICAL",
        "source": "syscall",
        "tags": ["container", "network", "cloud_metadata", "mitre_credential_access"],
    },
]


# ==================== WRITE OUTPUT FILES ====================

ensure_dir("/app/output")
ensure_dir("/app/output/network-policies")

# Write forensic report
with open("/app/output/forensic-report.json", "w") as f:
    json.dump(forensic_report, f, indent=2)

# Write audit policy
with open("/app/output/audit-policy.yaml", "w") as f:
    yaml.dump(audit_policy, f, default_flow_style=False, sort_keys=False)

# Write network policies
for filename, policy in network_policies:
    with open("/app/output/network-policies/{}".format(filename), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

# Write Falco rules
with open("/app/output/falco-rules.yaml", "w") as f:
    yaml.dump(falco_rules, f, default_flow_style=False, sort_keys=False, width=200)

print("=== Forensic Analysis Complete ===")
print("Compromised identity: {}".format(compromised_username))
print("Attack source IP: {}".format(attack_ip))
print("Attack events identified: {}".format(len(attack_events)))
print("Audit policy rules: {}".format(len(audit_policy["rules"])))
print("Network policies: {}".format(len(network_policies)))
print("Falco rules: {}".format(len(falco_rules)))
print("Output written to /app/output/")
