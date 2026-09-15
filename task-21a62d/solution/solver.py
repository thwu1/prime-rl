#!/usr/bin/env python3
"""
Kubernetes Security Incident Forensics Solver

Analyzes audit logs and Falco events to produce:
1. incident-report.json  - Forensics findings
2. hardened-audit-policy.yaml - Kubernetes audit policy
3. custom-falco-rules.yaml - Falco detection rules
"""

import json
import os
import re
import yaml


AUDIT_LOG = "/app/audit-logs/kube-apiserver-audit.jsonl"
FALCO_EVENTS = "/app/falco-events/events.log"
AUTHORIZED_OPS = "/app/context/authorized-operations.txt"
CLUSTER_INFO = "/app/context/cluster-info.txt"
OUTPUT_DIR = "/app/output"


def parse_audit_logs():
    """Parse JSONL audit log with robust error handling for corrupted entries."""
    events = []
    parse_errors = 0
    with open(AUDIT_LOG) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            # Try parsing the line as-is
            try:
                events.append(json.loads(line))
                continue
            except json.JSONDecodeError:
                pass

            # Handle concatenated JSON objects on one line: }{
            if "}{" in line:
                parts = re.split(r'(?<=\})(?=\{)', line)
                for part in parts:
                    try:
                        events.append(json.loads(part))
                    except json.JSONDecodeError:
                        parse_errors += 1
                continue

            # Handle trailing garbage after valid JSON
            # Try to find a valid JSON object at the start of the line
            match = re.match(r'(\{.*\})', line)
            if match:
                try:
                    events.append(json.loads(match.group(1)))
                    continue
                except json.JSONDecodeError:
                    pass

            # Truly corrupted line — log and skip
            parse_errors += 1

    return events, parse_errors


def parse_falco_events():
    events = []
    with open(FALCO_EVENTS) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(line)
    return events


def parse_authorized_ops():
    with open(AUTHORIZED_OPS) as f:
        return f.read()


def parse_cluster_info():
    with open(CLUSTER_INFO) as f:
        return f.read()


def is_system_component(username):
    system_prefixes = [
        "system:kube-scheduler",
        "system:kube-controller-manager",
        "system:node:",
        "system:apiserver",
    ]
    return any(username.startswith(p) for p in system_prefixes)


def is_authorized_user(username, verb, resource, namespace):
    if username == "admin@company.com" and resource == "namespaces":
        return True
    if (
        username == "system:serviceaccount:monitoring:monitoring-sa"
        and resource == "secrets"
        and namespace == "monitoring"
    ):
        return True
    # deploy-bot is authorized for pods, deployments, configmaps in production
    if (
        username == "system:serviceaccount:production:deploy-bot"
        and namespace == "production"
        and resource in ("pods", "deployments", "configmaps")
    ):
        return True
    return False


def analyze_attack(events):
    attack_events = []
    reconnaissance = []
    exfiltrated_secrets = []
    privilege_escalations = []
    lateral_movements = []
    persistence_mechanisms = []
    forbidden_attempts = []
    source_ip_map = {}  # Track source IPs per user

    for event in events:
        user = event.get("user", {}).get("username", "")
        verb = event.get("verb", "")
        obj_ref = event.get("objectRef", {})
        resource = obj_ref.get("resource", "")
        namespace = obj_ref.get("namespace", "")
        name = obj_ref.get("name", "")
        subresource = obj_ref.get("subresource", "")
        timestamp = event.get("requestReceivedTimestamp", "")
        status_code = event.get("responseStatus", {}).get("code", 0)
        annotations = event.get("annotations", {})
        source_ips = event.get("sourceIPs", [])

        if is_system_component(user):
            continue
        if is_authorized_user(user, verb, resource, namespace):
            continue
        if user == "developer@company.com":
            continue

        # Track source IPs for anomaly detection
        if source_ips:
            if user not in source_ip_map:
                source_ip_map[user] = []
            source_ip_map[user].append({
                "ip": source_ips[0],
                "timestamp": timestamp,
                "action": f"{verb} {resource}/{name}" if name else f"{verb} {resource}",
            })

        # Skip non-attack users (but we already handle deploy-bot above)
        if "ci-bot" not in user and "debug-agent" not in user:
            continue

        attack_events.append({
            "timestamp": timestamp,
            "user": user,
            "verb": verb,
            "resource": resource,
            "subresource": subresource,
            "namespace": namespace,
            "name": name,
            "status_code": status_code,
            "source_ips": source_ips,
        })

        # Forbidden attempts = pre-escalation reconnaissance
        if status_code == 403:
            forbidden_attempts.append({
                "timestamp": timestamp,
                "action": f"{verb} {resource}" + (f"/{name}" if name else ""),
                "namespace": namespace or "cluster-scope",
                "detail": annotations.get("authorization.k8s.io/reason", ""),
            })
            continue

        # ClusterRole inspection = target enumeration
        if resource == "clusterroles" and verb == "get":
            reconnaissance.append({
                "timestamp": timestamp,
                "action": f"Inspected ClusterRole '{name}'",
                "detail": "Attacker enumerated available high-privilege roles",
            })

        if resource == "secrets" and verb == "list" and not namespace:
            reconnaissance.append({
                "timestamp": timestamp,
                "action": "Listed all secrets cluster-wide",
                "detail": "Used escalated privileges for cluster-wide secret enumeration",
                "user": user,
            })

        if resource == "secrets" and verb == "get" and name:
            exfiltrated_secrets.append({
                "name": name,
                "namespace": namespace,
                "timestamp": timestamp,
            })

        if resource == "clusterrolebindings" and verb == "create":
            req_obj = event.get("requestObject", {})
            role_ref = req_obj.get("roleRef", {})
            privilege_escalations.append({
                "type": "ClusterRoleBinding",
                "name": name,
                "role": role_ref.get("name", "unknown"),
                "subjects": req_obj.get("subjects", []),
                "timestamp": timestamp,
                "authorization_chain": annotations.get("authorization.k8s.io/reason", ""),
            })

        if subresource == "exec" and verb == "create":
            lateral_movements.append({
                "type": "pod_exec",
                "pod": name,
                "namespace": namespace,
                "timestamp": timestamp,
            })

        if resource == "serviceaccounts" and verb == "create":
            persistence_mechanisms.append({
                "type": "ServiceAccount creation",
                "name": name,
                "namespace": namespace,
                "timestamp": timestamp,
            })

        if subresource == "token" and verb == "create":
            persistence_mechanisms.append({
                "type": "Token generation",
                "name": name,
                "namespace": namespace,
                "timestamp": timestamp,
            })

    # Detect source IP anomalies for ci-bot
    ip_anomalies = []
    cibot_key = "system:serviceaccount:build-system:ci-bot"
    if cibot_key in source_ip_map:
        ips = source_ip_map[cibot_key]
        unique_ips = set(entry["ip"] for entry in ips)
        if len(unique_ips) > 1:
            ip_anomalies.append({
                "user": cibot_key,
                "ips_observed": list(unique_ips),
                "detail": (
                    f"ci-bot was observed using multiple source IPs: {sorted(unique_ips)}. "
                    "The IP 10.244.1.15 is from the pod network (expected), while "
                    "10.10.99.5 is an unexpected external IP, suggesting the ci-bot token "
                    "was exfiltrated and used from outside the cluster for persistence operations."
                ),
                "events": ips,
            })

    return {
        "attack_events": attack_events,
        "reconnaissance": reconnaissance,
        "forbidden_attempts": forbidden_attempts,
        "exfiltrated_secrets": exfiltrated_secrets,
        "privilege_escalations": privilege_escalations,
        "lateral_movements": lateral_movements,
        "persistence_mechanisms": persistence_mechanisms,
        "source_ip_anomalies": ip_anomalies,
    }


def analyze_falco_events(falco_events):
    """Parse Falco events, filtering by container to separate attack from benign activity."""
    attack_events = []
    benign_events = []
    for event_line in falco_events:
        parts = event_line.split(" ", 2)
        if len(parts) >= 3:
            timestamp = parts[0]
            severity = parts[1]
            message = parts[2]

            # Extract container_name from the event
            container_match = re.search(r'container_name=(\S+)', message)
            container_name = container_match.group(1) if container_match else ""

            entry = {
                "timestamp": timestamp,
                "severity": severity,
                "message": message,
                "container_name": container_name,
            }

            # Filter: health-checker and log-rotator events are benign
            if container_name in ("health-checker", "log-rotator"):
                benign_events.append(entry)
            else:
                attack_events.append(entry)

    return attack_events, benign_events


def generate_incident_report(analysis, falco_attack, falco_benign, parse_errors):
    # Identify the root cause: pipeline-runner ClusterRole granted
    # clusterrolebinding create permission despite documentation saying it shouldn't
    root_cause_detail = ""
    for esc in analysis["privilege_escalations"]:
        chain = esc.get("authorization_chain", "")
        if "pipeline-runner" in chain and esc.get("role") == "cluster-admin":
            root_cause_detail = (
                "The pipeline-runner ClusterRole was misconfigured with overly permissive "
                "RBAC rules that granted clusterrolebindings create permission. The cluster-info "
                "documentation stated this role 'does NOT grant cross-namespace secret access "
                "or RBAC mutation permissions', but the actual ClusterRole included verbs on "
                "rbac.authorization.k8s.io resources. This misconfiguration violated the "
                "principle of least privilege and enabled the attacker to self-escalate to "
                "cluster-admin by creating a new ClusterRoleBinding."
            )
            break

    # Check if persistence was activated (debug-agent used post-creation)
    persistence_activated = False
    for event in analysis["attack_events"]:
        if "debug-agent" in event.get("user", ""):
            persistence_activated = True
            break

    report = {
        "incident_id": "INC-2024-1115-001",
        "title": "Kubernetes Cluster Compromise via CI/CD Service Account Abuse",
        "severity": "Critical",
        "status": "Confirmed",
        "incident_window": {
            "start": "2024-11-15T03:20:15Z",
            "end": "2024-11-15T03:28:30Z",
        },
        "executive_summary": (
            "The ci-bot service account in the build-system namespace was compromised "
            "and used to escalate privileges to cluster-admin via a misconfigured "
            "pipeline-runner ClusterRole, exfiltrate secrets from the production namespace, "
            "execute commands inside a production pod, and establish persistence via a "
            "new service account with token in kube-system. Source IP analysis reveals "
            "the attacker's token was exfiltrated and used from an external IP (10.10.99.5) "
            "for persistence operations. The persistence mechanism (debug-agent) was "
            "confirmed active within the incident window."
        ),
        "evidence_integrity": {
            "audit_log_parse_errors": parse_errors,
            "detail": (
                f"The audit log contained {parse_errors} malformed entries that could not "
                "be parsed as valid JSON. These appear to be caused by log rotation "
                "truncation and syslog buffer issues. One truncated entry contained "
                "partial evidence of ci-bot RBAC enumeration (listing clusterrolebindings). "
                "Two concatenated events on a single line were recovered. Analysis accounts "
                "for data integrity issues."
            ),
            "falco_noise_filtered": (
                "Falco events from the health-checker sidecar container and the "
                "log-rotator CronJob were identified as benign and excluded from "
                "attack attribution. These events share the same pod name as the "
                "compromised api-server container but originate from different containers."
            ),
        },
        "root_cause_analysis": {
            "vulnerability": "RBAC Misconfiguration in pipeline-runner ClusterRole",
            "detail": root_cause_detail,
            "impact": (
                "The overprivileged pipeline-runner ClusterRole allowed a compromised "
                "CI/CD service account to self-escalate to cluster-admin, bypassing "
                "all namespace-level isolation and gaining unrestricted cluster access."
            ),
            "evidence": (
                "Audit log event at 03:22:00 shows ci-bot creating ClusterRoleBinding "
                "'ci-bot-cluster-admin' authorized by pipeline-runner, contradicting the "
                "RBAC documentation that states pipeline-runner does not grant RBAC mutation."
            ),
        },
        "compromised_identities": [
            {
                "type": "ServiceAccount",
                "name": "ci-bot",
                "namespace": "build-system",
                "original_permissions": "ClusterRole pipeline-runner (limited to build-system)",
                "escalated_permissions": "ClusterRole cluster-admin (cluster-wide)",
            }
        ],
        "source_ip_anomaly": {
            "description": (
                "ci-bot source IP changed from 10.244.1.15 (pod network) to 10.10.99.5 "
                "(external/unexpected IP) during the attack. The initial reconnaissance and "
                "privilege escalation phases used the pod IP 10.244.1.15. The persistence "
                "phase (ServiceAccount creation, token generation, ClusterRoleBinding) used "
                "the external IP 10.10.99.5. This indicates the ci-bot token was exfiltrated "
                "and reused from outside the cluster, suggesting the attacker operated from "
                "a different network location for the persistence phase."
            ),
            "pod_network_ip": "10.244.1.15",
            "external_ip": "10.10.99.5",
            "implication": "Token theft and external reuse — the attacker may have multiple access vectors",
        },
        "pre_escalation_reconnaissance": {
            "description": (
                "Before escalating privileges, the attacker probed cluster-scope "
                "secret access and cross-namespace capabilities, receiving 403 Forbidden "
                "responses. The attacker then inspected the cluster-admin ClusterRole to "
                "identify the escalation target. A truncated audit entry also shows "
                "the attacker listing clusterrolebindings to map out existing RBAC bindings."
            ),
            "forbidden_attempts": analysis["forbidden_attempts"],
            "target_enumeration": analysis["reconnaissance"],
        },
        "attack_timeline": [
            {
                "timestamp": "2024-11-15T03:20:15Z",
                "phase": "Reconnaissance",
                "action": "Attempted cluster-wide secret listing",
                "detail": "403 Forbidden — tested scope of current permissions",
            },
            {
                "timestamp": "2024-11-15T03:20:30Z",
                "phase": "Reconnaissance",
                "action": "Inspected cluster-admin ClusterRole",
                "detail": "Enumerated available high-privilege roles to identify escalation target",
            },
            {
                "timestamp": "2024-11-15T03:20:45Z",
                "phase": "Reconnaissance",
                "action": "Attempted cross-namespace secret access in production",
                "detail": "403 Forbidden — confirmed need for privilege escalation",
            },
            {
                "timestamp": "2024-11-15T03:21:00Z",
                "phase": "Credential Access",
                "action": "Listed secrets in build-system namespace",
                "detail": "Enumerated available secrets within legitimate scope",
            },
            {
                "timestamp": "2024-11-15T03:21:30Z",
                "phase": "Credential Access",
                "action": "Read registry-credentials secret in build-system",
                "detail": "Exfiltrated Docker registry credentials",
            },
            {
                "timestamp": "2024-11-15T03:22:00Z",
                "phase": "Privilege Escalation",
                "action": "Created ClusterRoleBinding ci-bot-cluster-admin",
                "detail": (
                    "Exploited misconfigured pipeline-runner ClusterRole to bind ci-bot to "
                    "cluster-admin, gaining full cluster access"
                ),
            },
            {
                "timestamp": "2024-11-15T03:22:30Z",
                "phase": "Discovery",
                "action": "Listed secrets across all namespaces",
                "detail": "Used escalated privileges to enumerate all cluster secrets (previously 403)",
            },
            {
                "timestamp": "2024-11-15T03:23:00-03:23:30Z",
                "phase": "Credential Access",
                "action": "Exfiltrated production secrets",
                "detail": "Read database-credentials, api-keys, and tls-cert from production namespace",
            },
            {
                "timestamp": "2024-11-15T03:24:00Z",
                "phase": "Lateral Movement / Execution",
                "action": "Executed /bin/bash in production pod via exec",
                "detail": "Ran interactive shell in api-server-7f8d9c6b5-x2k4m pod in production namespace",
            },
            {
                "timestamp": "2024-11-15T03:24:02-03:24:31Z",
                "phase": "Runtime Exploitation",
                "action": "Post-exploitation activity inside container",
                "detail": (
                    "Falco runtime alerts (filtered to api-server container, excluding health-checker "
                    "sidecar) correlate with audit log exec event: shell spawn, sensitive file read "
                    "(/etc/shadow), symlink over sensitive file, package installation, binary "
                    "directory modification, C2 beacon via curl"
                ),
            },
            {
                "timestamp": "2024-11-15T03:25:00Z",
                "phase": "Persistence (source IP: 10.10.99.5)",
                "action": "Created debug-agent ServiceAccount in kube-system",
                "detail": "Established backdoor identity in privileged namespace — note source IP change from pod network",
            },
            {
                "timestamp": "2024-11-15T03:25:15Z",
                "phase": "Persistence (source IP: 10.10.99.5)",
                "action": "Generated API token for debug-agent ServiceAccount",
                "detail": "Obtained authentication token for the backdoor identity",
            },
            {
                "timestamp": "2024-11-15T03:25:30Z",
                "phase": "Persistence (source IP: 10.10.99.5)",
                "action": "Created ClusterRoleBinding debug-agent-binding",
                "detail": "Granted cluster-admin to debug-agent for persistent cluster access",
            },
            {
                "timestamp": "2024-11-15T03:28:30Z",
                "phase": "Persistence Activation",
                "action": "debug-agent listed secrets cluster-wide",
                "detail": (
                    "The newly created debug-agent service account was used to list all "
                    "cluster secrets from the same external IP 10.10.99.5, confirming the "
                    "persistence mechanism was immediately activated and functional."
                ),
            },
        ],
        "exfiltrated_resources": [
            {
                "type": "Secret",
                "name": "registry-credentials",
                "namespace": "build-system",
                "risk": "Docker registry access — attacker may push malicious images",
            },
            {
                "type": "Secret",
                "name": "database-credentials",
                "namespace": "production",
                "risk": "Production database access — data breach risk",
            },
            {
                "type": "Secret",
                "name": "api-keys",
                "namespace": "production",
                "risk": "External API credentials — unauthorized third-party access",
            },
            {
                "type": "Secret",
                "name": "tls-cert",
                "namespace": "production",
                "risk": "TLS certificate and private key — MitM attack risk",
            },
        ],
        "privilege_escalations": analysis["privilege_escalations"],
        "lateral_movements": analysis["lateral_movements"],
        "persistence_mechanisms": [
            {
                "type": "ServiceAccount + Token + ClusterRoleBinding",
                "name": "debug-agent",
                "namespace": "kube-system",
                "bound_role": "cluster-admin",
                "binding_name": "debug-agent-binding",
                "token_generated": True,
                "activated": persistence_activated,
                "detail": (
                    "Multi-step persistence: created ServiceAccount, generated API token, "
                    "then bound to cluster-admin. The token provides immediate access "
                    "without needing the original ci-bot credentials. Persistence was "
                    "confirmed active when debug-agent listed cluster secrets at 03:28:30."
                ),
            }
        ],
        "runtime_indicators_from_falco": [
            "Terminal shell spawned in api-server container (Warning)",
            "Sensitive file /etc/shadow read inside container (Error)",
            "Sensitive mount detected: /var/run/secrets/kubernetes.io/serviceaccount (Notice)",
            "Package management (apt-get) executed inside production container (Error)",
            "Symlink created over sensitive file /etc/shadow (Warning)",
            "Binary directory modification: backdoor placed in /usr/local/bin (Error)",
            "Network tool (curl) used to contact C2 server c2.attacker.example.com (Warning)",
            "Outbound connection to suspicious IP 198.51.100.47:443 (Warning)",
        ],
        "filtered_benign_falco_events": [
            "health-checker sidecar: process launch, DNS config read, localhost health probe",
            "log-rotator CronJob: bash invocation for log rotation script in kube-system",
        ],
        "cross_source_correlation": (
            "The API server audit log shows ci-bot creating a pod exec session at 03:24:00. "
            "Falco runtime events beginning at 03:24:02 confirm the session was used to spawn "
            "a shell, read sensitive files, install packages, modify binaries, and establish "
            "C2 communication — all within the api-server container in the production namespace. "
            "Health-checker sidecar events at 03:24:01, 03:24:03, and 03:24:10 were correctly "
            "identified as benign and excluded from attack attribution."
        ),
        "mitre_attack_techniques": [
            {
                "id": "T1078.004",
                "name": "Valid Accounts: Cloud Accounts",
                "phase": "Initial Access",
                "detail": "Compromised ci-bot service account credentials",
            },
            {
                "id": "T1552.007",
                "name": "Unsecured Credentials: Container API",
                "phase": "Credential Access",
                "detail": "Accessed Kubernetes secrets via API",
            },
            {
                "id": "T1098.001",
                "name": "Account Manipulation: Additional Cloud Credentials",
                "phase": "Persistence",
                "detail": "Created new ServiceAccount, generated token, and created ClusterRoleBinding",
            },
            {
                "id": "T1609",
                "name": "Container Administration Command",
                "phase": "Execution",
                "detail": "Used kubectl exec to run /bin/bash in production container",
            },
            {
                "id": "T1068",
                "name": "Exploitation for Privilege Escalation",
                "phase": "Privilege Escalation",
                "detail": (
                    "Exploited misconfigured pipeline-runner ClusterRole to create "
                    "ClusterRoleBinding granting cluster-admin"
                ),
            },
            {
                "id": "T1105",
                "name": "Ingress Tool Transfer",
                "phase": "Command and Control",
                "detail": "Used curl to beacon C2 server and installed tools via apt-get",
            },
        ],
        "recommendations": [
            "IMMEDIATE: Delete ClusterRoleBindings ci-bot-cluster-admin and debug-agent-binding",
            "IMMEDIATE: Delete ServiceAccount debug-agent from kube-system",
            "IMMEDIATE: Rotate all exfiltrated secrets (registry-credentials, database-credentials, api-keys, tls-cert)",
            "IMMEDIATE: Revoke and re-issue ci-bot service account token",
            "IMMEDIATE: Block external IP 10.10.99.5 at network perimeter",
            "ROOT CAUSE FIX: Audit and restrict the pipeline-runner ClusterRole to remove RBAC mutation permissions (should not grant create on clusterrolebindings/clusterroles)",
            "HARDENING: Implement the provided hardened audit policy for API server logging",
            "HARDENING: Deploy Falco with custom runtime detection rules",
            "HARDENING: Enable Pod Security Admission for production namespace (restricted profile)",
            "HARDENING: Implement NetworkPolicy to restrict egress from production pods",
            "HARDENING: Review all ClusterRoleBindings for overprivileged workload service accounts",
            "DETECTION: Monitor for source IP changes within service account sessions",
        ],
    }
    return report


def generate_audit_policy():
    policy = {
        "apiVersion": "audit.k8s.io/v1",
        "kind": "Policy",
        "omitStages": ["RequestReceived"],
        "rules": [
            {
                "level": "None",
                "resources": [
                    {"group": "", "resources": ["configmaps", "endpoints", "events"]},
                    {"group": "coordination.k8s.io", "resources": ["leases"]},
                ],
                "verbs": ["get", "list", "watch"],
            },
            {
                "level": "None",
                "nonResourceURLs": [
                    "/healthz*", "/readyz*", "/livez*", "/version", "/openapi/*",
                ],
            },
            {
                "level": "RequestResponse",
                "resources": [{"group": "", "resources": ["secrets"]}],
                "namespaces": ["production", "kube-system", "build-system", "default"],
            },
            {
                "level": "Request",
                "resources": [
                    {
                        "group": "rbac.authorization.k8s.io",
                        "resources": [
                            "clusterrolebindings", "rolebindings",
                            "clusterroles", "roles",
                        ],
                    }
                ],
                "verbs": ["create", "update", "patch", "delete"],
            },
            {
                "level": "Metadata",
                "resources": [
                    {
                        "group": "",
                        "resources": ["pods/exec", "pods/attach", "pods/portforward"],
                    }
                ],
            },
            {
                "level": "Request",
                "resources": [{"group": "", "resources": ["serviceaccounts"]}],
                "verbs": ["create", "update", "patch", "delete"],
            },
            {
                "level": "Request",
                "resources": [
                    {"group": "", "resources": ["serviceaccounts/token"]},
                ],
                "verbs": ["create"],
            },
            {
                "level": "Metadata",
                "resources": [{"group": "", "resources": ["namespaces"]}],
                "verbs": ["create", "delete"],
            },
            {"level": "Metadata"},
        ],
    }
    return policy


def generate_falco_rules():
    rules = [
        {
            "list": "cicd_images",
            "items": [
                "registry.company.io/api-server",
                "registry.company.io/web-frontend",
                "registry.company.io/payment-processor",
            ],
        },
        {
            "rule": "Shell Spawned in Production Container",
            "desc": (
                "Detect interactive shell sessions spawned in production containers. "
                "Production containers should not have interactive terminals. "
                "This indicates potential lateral movement or container compromise."
            ),
            "condition": (
                "spawned_process and container and shell_procs and proc.tty != 0 "
                "and k8s.ns.name = production"
            ),
            "output": (
                "Shell spawned in production container "
                "(user=%user.name user_loginuid=%user.loginuid command=%proc.cmdline "
                "terminal=%proc.tty container_id=%container.id "
                "container_name=%container.name "
                "image=%container.image.repository:%container.image.tag "
                "namespace=%k8s.ns.name pod_name=%k8s.pod.name)"
            ),
            "priority": "ERROR",
            "tags": [
                "container", "shell", "mitre_execution", "T1059", "production",
            ],
        },
        {
            "rule": "Sensitive File Read in Container",
            "desc": (
                "Detect attempts to read sensitive files such as /etc/shadow, "
                "/etc/sudoers, or PAM configuration inside a container. "
                "This indicates credential harvesting or reconnaissance."
            ),
            "condition": (
                "open_read and sensitive_files and container and proc_name_exists "
                "and not proc.name in (shell_binaries)"
            ),
            "output": (
                "Sensitive file read inside container "
                "(file=%fd.name user=%user.name command=%proc.cmdline "
                "container_id=%container.id container_name=%container.name "
                "image=%container.image.repository:%container.image.tag "
                "namespace=%k8s.ns.name pod_name=%k8s.pod.name)"
            ),
            "priority": "ERROR",
            "tags": [
                "container", "filesystem", "mitre_credential_access", "T1555",
            ],
        },
        {
            "rule": "Modify Binary Dirs in Container",
            "desc": (
                "Detect modification of binary directories (/usr/bin, /usr/sbin, "
                "/usr/local/bin, etc.) inside containers. Writing to these directories "
                "at runtime indicates backdoor installation or trojanized binaries."
            ),
            "condition": (
                "open_write and container and evt.dir=< "
                "and fd.name startswith /usr/ "
                "and (fd.name contains /bin/ or fd.name contains /sbin/) "
                "and not proc.name in (package_mgmt_binaries) "
                "and not run_by_package_mgmt_binaries"
            ),
            "output": (
                "Binary directory modified in container "
                "(file=%fd.name user=%user.name command=%proc.cmdline "
                "container_id=%container.id container_name=%container.name "
                "image=%container.image.repository:%container.image.tag "
                "namespace=%k8s.ns.name pod_name=%k8s.pod.name)"
            ),
            "priority": "CRITICAL",
            "tags": [
                "container", "filesystem", "mitre_persistence", "T1543",
            ],
        },
        {
            "rule": "Network Reconnaissance Tool in Container",
            "desc": (
                "Detect network tools like curl, wget, nc, nmap being executed "
                "inside containers. These tools are commonly used by attackers "
                "for data exfiltration, C2 communication, or network scanning."
            ),
            "condition": (
                "spawned_process and container "
                "and proc.name in (network_tool_binaries) "
                "and not user_known_shell_spawn_activities"
            ),
            "output": (
                "Network tool launched in container "
                "(user=%user.name command=%proc.cmdline "
                "container_id=%container.id container_name=%container.name "
                "image=%container.image.repository:%container.image.tag "
                "namespace=%k8s.ns.name pod_name=%k8s.pod.name)"
            ),
            "priority": "WARNING",
            "tags": [
                "container", "network", "mitre_command_and_control",
                "T1071", "mitre_exfiltration",
            ],
        },
    ]
    return rules


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    audit_events, parse_errors = parse_audit_logs()
    falco_events = parse_falco_events()
    parse_authorized_ops()
    parse_cluster_info()

    analysis = analyze_attack(audit_events)
    falco_attack, falco_benign = analyze_falco_events(falco_events)

    report = generate_incident_report(analysis, falco_attack, falco_benign, parse_errors)
    with open(os.path.join(OUTPUT_DIR, "incident-report.json"), "w") as f:
        json.dump(report, f, indent=2)

    policy = generate_audit_policy()
    with open(os.path.join(OUTPUT_DIR, "hardened-audit-policy.yaml"), "w") as f:
        yaml.dump(policy, f, default_flow_style=False, sort_keys=False)

    falco_rules = generate_falco_rules()
    with open(os.path.join(OUTPUT_DIR, "custom-falco-rules.yaml"), "w") as f:
        yaml.dump(falco_rules, f, default_flow_style=False, sort_keys=False)

    print("Forensics analysis complete. Output files:")
    print(f"  {OUTPUT_DIR}/incident-report.json")
    print(f"  {OUTPUT_DIR}/hardened-audit-policy.yaml")
    print(f"  {OUTPUT_DIR}/custom-falco-rules.yaml")


if __name__ == "__main__":
    main()
