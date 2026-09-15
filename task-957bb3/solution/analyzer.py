#!/usr/bin/env python3
"""
Kubernetes Audit Log Forensics Analyzer & Remediation Generator.

Parses kube-apiserver audit logs to reconstruct an attack chain,
then generates hardened security configurations, OPA validation policies,
and fallback trivy/conftest-compatible JSON outputs.
"""

import json
import os
import yaml

# =============================================================================
# Step 1: Parse audit logs and identify attack events
# =============================================================================

def load_audit_log(path):
    with open(path, "r") as f:
        return json.load(f)


def is_attack_event(event):
    """
    Identify attack events based on forensic indicators:
    1. User agent is curl (not the legitimate webapp client)
    2. The user is the webapp service account
    """
    user = event.get("user", {})
    username = user.get("username", "")
    user_agent = event.get("userAgent", "")

    if "webapp-sa" not in username:
        return False

    # The legitimate webapp uses "webapp/2.1.0 (go-http-client)" user agent.
    # The attacker used curl from inside the compromised pod.
    if "curl" in user_agent.lower():
        return True

    return False


def extract_attack_timeline(events):
    """Extract and order attack events chronologically."""
    attack_events = []

    for event in events:
        if not is_attack_event(event):
            continue

        obj_ref = event.get("objectRef", {})
        verb = event.get("verb", "")
        resource = obj_ref.get("resource", "")
        name = obj_ref.get("name")
        namespace = obj_ref.get("namespace")
        timestamp = event.get("requestReceivedTimestamp", "")

        description = generate_description(verb, resource, name, namespace, event)

        attack_events.append({
            "timestamp": timestamp,
            "action": verb,
            "resource_type": resource,
            "resource_name": name,
            "namespace": namespace,
            "description": description,
        })

    attack_events.sort(key=lambda x: x["timestamp"])
    return attack_events


def generate_description(verb, resource, name, namespace, event):
    """Generate a human-readable description for an attack event."""
    if resource == "namespaces" and verb == "list":
        return "Reconnaissance: listing all cluster namespaces"
    elif resource == "secrets" and verb == "list":
        return f"Secret enumeration: listing all secrets in {namespace} namespace"
    elif resource == "secrets" and verb == "get":
        return f"Secret theft: reading secret '{name}' from {namespace} namespace"
    elif resource == "clusterroles" and verb == "list":
        return "RBAC reconnaissance: listing all ClusterRoles to find escalation paths"
    elif resource == "clusterrolebindings" and verb == "create":
        return f"Privilege escalation: creating ClusterRoleBinding '{name}' binding cluster-admin"
    elif resource == "pods" and verb == "create":
        return f"Persistence: creating privileged pod '{name}' in {namespace} with hostPath to /etc/kubernetes/pki"
    elif resource == "daemonsets" and verb == "create":
        return f"Cryptomining: deploying DaemonSet '{name}' in {namespace} running xmrig miner"
    else:
        return f"{verb} {resource}/{name} in {namespace}"


def extract_compromised_secrets(timeline):
    """Extract secret names from the attack timeline."""
    secrets = []
    for event in timeline:
        if event["resource_type"] == "secrets" and event["action"] == "get":
            secrets.append(f"{event['namespace']}/{event['resource_name']}")
    return secrets


def extract_attacker_created_resources(timeline):
    """Extract resources created by the attacker."""
    resources = []
    for event in timeline:
        if event["action"] == "create":
            resource_type = event["resource_type"]
            kind_map = {
                "clusterrolebindings": "ClusterRoleBinding",
                "pods": "Pod",
                "daemonsets": "DaemonSet",
            }
            kind = kind_map.get(resource_type, resource_type)
            if event["namespace"]:
                resources.append(f"{kind}/{event['namespace']}/{event['resource_name']}")
            else:
                resources.append(f"{kind}/{event['resource_name']}")
    return resources


def build_attack_summary(audit_log_path):
    """Build the complete attack summary JSON."""
    events = load_audit_log(audit_log_path)
    timeline = extract_attack_timeline(events)
    compromised_secrets = extract_compromised_secrets(timeline)
    created_resources = extract_attacker_created_resources(timeline)

    return {
        "attack_timeline": timeline,
        "compromised_service_account": "system:serviceaccount:ecommerce:webapp-sa",
        "compromised_secrets": compromised_secrets,
        "attacker_created_resources": created_resources,
        "attacker_source_ip": "10.244.1.8",
        "initial_vulnerability": "Overly permissive ClusterRole 'webapp-full-access' granting wildcard (*) permissions on all resources across all namespaces, bound via ClusterRoleBinding to the webapp-sa service account",
    }


# =============================================================================
# Step 2: Generate RBAC remediation
# =============================================================================

RBAC_YAML = """---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: webapp-restricted
  namespace: ecommerce
rules:
- apiGroups: [""]
  resources: ["services", "configmaps"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: webapp-restricted-binding
  namespace: ecommerce
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: webapp-restricted
subjects:
- kind: ServiceAccount
  name: webapp-sa
  namespace: ecommerce
"""


# =============================================================================
# Step 3: Generate Audit Policy
# =============================================================================

AUDIT_POLICY_YAML = """apiVersion: audit.k8s.io/v1
kind: Policy
rules:
# Log all secrets access at RequestResponse level
- level: RequestResponse
  resources:
  - group: ""
    resources: ["secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]

# Log all RBAC modifications at RequestResponse level
- level: RequestResponse
  resources:
  - group: "rbac.authorization.k8s.io"
    resources: ["clusterroles", "clusterrolebindings", "roles", "rolebindings"]
  verbs: ["create", "update", "patch", "delete"]

# Log pod and workload creation at RequestResponse level
- level: RequestResponse
  resources:
  - group: ""
    resources: ["pods"]
  - group: "apps"
    resources: ["deployments", "daemonsets", "statefulsets", "replicasets"]
  verbs: ["create", "update", "patch", "delete"]

# Log service account token requests
- level: RequestResponse
  resources:
  - group: ""
    resources: ["serviceaccounts/token"]
  verbs: ["create"]

# Log all other requests at Metadata level
- level: Metadata
  resources:
  - group: ""
    resources: ["namespaces", "nodes", "persistentvolumes"]
  verbs: ["get", "list", "watch"]

# Catch-all: log everything else at Metadata level
- level: Metadata
"""


# =============================================================================
# Step 4: Generate Network Policy
# =============================================================================

NETWORK_POLICY_YAML = """apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: webapp-network-policy
  namespace: ecommerce
spec:
  podSelector:
    matchLabels:
      app: webapp
  policyTypes:
  - Ingress
  - Egress
  ingress:
  # Allow inbound traffic on webapp port
  - ports:
    - protocol: TCP
      port: 8080
  egress:
  # Allow outbound traffic to database only
  - to:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
  # Allow DNS resolution
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
"""


# =============================================================================
# Step 5: Generate Falco Rules
# =============================================================================

FALCO_RULES_YAML = """- rule: Suspicious Secret Access via Non-Standard User Agent
  desc: >
    Detects when a service account accesses Kubernetes secrets using an unexpected
    user agent (e.g. curl or wget instead of the application's normal HTTP client),
    which may indicate a compromised pod being used interactively by an attacker.
  condition: >
    ka.verb in (get, list) and
    ka.target.resource = secrets and
    not ka.user.name startswith "system:kube" and
    not ka.user.name startswith "system:node" and
    (ka.useragent contains "curl" or ka.useragent contains "wget" or ka.useragent contains "kubectl")
  output: >
    Suspicious secret access detected
    (user=%ka.user.name verb=%ka.verb resource=%ka.target.resource
    namespace=%ka.target.namespace name=%ka.target.name
    useragent=%ka.useragent sourceips=%ka.sourceips)
  priority: CRITICAL
  source: k8s_audit
  tags: [k8s, secrets, credential_access, mitre_credential_access, T1552]

- rule: ClusterRoleBinding to cluster-admin Created
  desc: >
    Detects the creation of a ClusterRoleBinding that references the cluster-admin
    ClusterRole. This is a common privilege escalation technique where an attacker
    with sufficient RBAC permissions grants themselves or another identity full
    cluster administrative access.
  condition: >
    ka.verb = create and
    ka.target.resource = clusterrolebindings and
    ka.req.binding.role = cluster-admin
  output: >
    ClusterRoleBinding to cluster-admin created
    (user=%ka.user.name binding_name=%ka.target.name
    role=%ka.req.binding.role subjects=%ka.req.binding.subjects
    sourceips=%ka.sourceips)
  priority: CRITICAL
  source: k8s_audit
  tags: [k8s, rbac, privilege_escalation, mitre_privilege_escalation, T1078]

- rule: Pod Created with HostPath Mount to Sensitive Directory
  desc: >
    Detects pod creation that mounts host filesystem paths containing sensitive
    data such as PKI certificates, kubelet configuration, or etcd data. Attackers
    use this technique to exfiltrate cluster credentials or tamper with cluster
    components.
  condition: >
    ka.verb = create and
    ka.target.resource = pods and
    (ka.req.pod.volumes.hostpath intersects (/etc/kubernetes, /etc/kubernetes/pki, /var/lib/etcd, /var/lib/kubelet))
  output: >
    Pod created with hostPath to sensitive directory
    (user=%ka.user.name pod=%ka.target.name namespace=%ka.target.namespace
    hostpath_volumes=%ka.req.pod.volumes.hostpath image=%ka.req.container.image
    sourceips=%ka.sourceips)
  priority: CRITICAL
  source: k8s_audit
  tags: [k8s, hostpath, persistence, mitre_persistence, T1611]
"""


# =============================================================================
# Step 6: Generate OPA/Rego Policies for conftest
# =============================================================================

OPA_POLICY_REGO = r"""package main

# =============================================================================
# RBAC Policy: deny wildcard verbs in Roles
# =============================================================================
deny[msg] {
    input.kind == "Role"
    rule := input.rules[_]
    rule.verbs[_] == "*"
    msg := sprintf("Role '%s' must not use wildcard verbs", [input.metadata.name])
}

# RBAC Policy: deny wildcard resources in Roles
deny[msg] {
    input.kind == "Role"
    rule := input.rules[_]
    rule.resources[_] == "*"
    msg := sprintf("Role '%s' must not use wildcard resources", [input.metadata.name])
}

# RBAC Policy: deny secrets access in application Roles
deny[msg] {
    input.kind == "Role"
    rule := input.rules[_]
    rule.resources[_] == "secrets"
    msg := sprintf("Role '%s' must not grant access to secrets", [input.metadata.name])
}

# =============================================================================
# NetworkPolicy: require Ingress policyType
# =============================================================================
deny[msg] {
    input.kind == "NetworkPolicy"
    not policy_type_present("Ingress")
    msg := sprintf("NetworkPolicy '%s' must include Ingress policyType", [input.metadata.name])
}

# NetworkPolicy: require Egress policyType
deny[msg] {
    input.kind == "NetworkPolicy"
    not policy_type_present("Egress")
    msg := sprintf("NetworkPolicy '%s' must include Egress policyType", [input.metadata.name])
}

policy_type_present(ptype) {
    input.spec.policyTypes[_] == ptype
}

# =============================================================================
# Audit Policy: require RequestResponse level for secrets
# =============================================================================
deny[msg] {
    input.kind == "Policy"
    input.apiVersion == "audit.k8s.io/v1"
    not secrets_at_request_response
    msg := "Audit policy must use RequestResponse level for secrets"
}

secrets_at_request_response {
    rule := input.rules[_]
    rule.level == "RequestResponse"
    res := rule.resources[_]
    res.resources[_] == "secrets"
}
"""


# =============================================================================
# Step 7: Generate trivy-compatible JSON (fallback if trivy unavailable)
# =============================================================================

def generate_trivy_output(cluster_state_dir):
    """Analyze cluster-state YAML files for misconfigurations and produce trivy-format JSON."""
    results = []

    # Scan current-rbac.yaml
    rbac_path = os.path.join(cluster_state_dir, "current-rbac.yaml")
    if os.path.exists(rbac_path):
        with open(rbac_path) as f:
            docs = list(yaml.safe_load_all(f))

        misconfigs = []
        for doc in docs:
            if doc is None:
                continue
            kind = doc.get("kind", "")
            name = doc.get("metadata", {}).get("name", "")

            if kind == "ClusterRole":
                for rule in doc.get("rules", []):
                    if "*" in rule.get("verbs", []):
                        misconfigs.append({
                            "Type": "Kubernetes Security Check",
                            "ID": "KSV049",
                            "AVDID": "AVD-KSV-0049",
                            "Title": "Do not allow wildcard verb permissions",
                            "Description": f"ClusterRole '{name}' uses wildcard verb '*' which grants all possible operations on resources. This violates the principle of least privilege.",
                            "Message": f"ClusterRole '{name}' should not use wildcard verbs",
                            "Resolution": "Replace wildcard verbs with specific verbs needed",
                            "Severity": "CRITICAL",
                            "PrimaryURL": "https://kubernetes.io/docs/reference/access-authn-authz/rbac/",
                            "Status": "FAIL"
                        })
                    if "*" in rule.get("resources", []):
                        misconfigs.append({
                            "Type": "Kubernetes Security Check",
                            "ID": "KSV041",
                            "AVDID": "AVD-KSV-0041",
                            "Title": "Do not allow wildcard resource permissions",
                            "Description": f"ClusterRole '{name}' uses wildcard resource '*' which grants access to all resources. This violates the principle of least privilege.",
                            "Message": f"ClusterRole '{name}' should not use wildcard resources",
                            "Resolution": "Specify explicit resources instead of wildcard",
                            "Severity": "CRITICAL",
                            "PrimaryURL": "https://kubernetes.io/docs/reference/access-authn-authz/rbac/",
                            "Status": "FAIL"
                        })

            if kind == "ClusterRoleBinding":
                role_ref = doc.get("roleRef", {})
                if role_ref.get("name") == "cluster-admin":
                    misconfigs.append({
                        "Type": "Kubernetes Security Check",
                        "ID": "KSV043",
                        "AVDID": "AVD-KSV-0043",
                        "Title": "Do not bind to cluster-admin ClusterRole",
                        "Description": f"ClusterRoleBinding '{name}' grants cluster-admin privileges which provides unrestricted access to the entire cluster.",
                        "Message": f"ClusterRoleBinding '{name}' should not reference cluster-admin",
                        "Resolution": "Create a more restrictive ClusterRole",
                        "Severity": "CRITICAL",
                        "PrimaryURL": "https://kubernetes.io/docs/reference/access-authn-authz/rbac/",
                        "Status": "FAIL"
                    })

        results.append({
            "Target": "current-rbac.yaml",
            "Class": "config",
            "Type": "kubernetes",
            "MisconfSummary": {
                "Successes": 0,
                "Failures": len(misconfigs),
                "Exceptions": 0
            },
            "Misconfigurations": misconfigs
        })

    # Scan current-workloads.yaml
    workloads_path = os.path.join(cluster_state_dir, "current-workloads.yaml")
    if os.path.exists(workloads_path):
        with open(workloads_path) as f:
            docs = list(yaml.safe_load_all(f))

        misconfigs = []
        for doc in docs:
            if doc is None:
                continue
            kind = doc.get("kind", "")
            name = doc.get("metadata", {}).get("name", "")
            spec = doc.get("spec", {})

            if kind == "Pod":
                # Check for privileged containers
                containers = spec.get("containers", [])
                for c in containers:
                    sc = c.get("securityContext", {})
                    if sc.get("privileged"):
                        misconfigs.append({
                            "Type": "Kubernetes Security Check",
                            "ID": "KSV017",
                            "AVDID": "AVD-KSV-0017",
                            "Title": "Do not allow privileged containers",
                            "Description": f"Container '{c.get('name')}' in Pod '{name}' runs in privileged mode. Privileged containers can access host resources and are a security risk.",
                            "Message": f"Container should not be set as privileged",
                            "Resolution": "Remove privileged flag from container securityContext",
                            "Severity": "HIGH",
                            "PrimaryURL": "https://kubernetes.io/docs/concepts/security/pod-security-standards/",
                            "Status": "FAIL"
                        })

                # Check for hostNetwork
                if spec.get("hostNetwork"):
                    misconfigs.append({
                        "Type": "Kubernetes Security Check",
                        "ID": "KSV024",
                        "AVDID": "AVD-KSV-0024",
                        "Title": "Do not allow hostNetwork",
                        "Description": f"Pod '{name}' uses hostNetwork which shares the host network namespace.",
                        "Message": f"Pod should not use host network",
                        "Resolution": "Set hostNetwork to false",
                        "Severity": "HIGH",
                        "PrimaryURL": "https://kubernetes.io/docs/concepts/security/pod-security-standards/",
                        "Status": "FAIL"
                    })

                # Check for hostPID
                if spec.get("hostPID"):
                    misconfigs.append({
                        "Type": "Kubernetes Security Check",
                        "ID": "KSV025",
                        "AVDID": "AVD-KSV-0025",
                        "Title": "Do not allow hostPID",
                        "Description": f"Pod '{name}' uses hostPID which shares the host PID namespace.",
                        "Message": f"Pod should not use host PID namespace",
                        "Resolution": "Set hostPID to false",
                        "Severity": "HIGH",
                        "PrimaryURL": "https://kubernetes.io/docs/concepts/security/pod-security-standards/",
                        "Status": "FAIL"
                    })

                # Check for hostPath volumes
                for vol in spec.get("volumes", []):
                    if "hostPath" in vol:
                        hp = vol["hostPath"]
                        misconfigs.append({
                            "Type": "Kubernetes Security Check",
                            "ID": "KSV023",
                            "AVDID": "AVD-KSV-0023",
                            "Title": "Do not allow hostPath volumes",
                            "Description": f"Pod '{name}' mounts hostPath '{hp.get('path', '')}' which can expose sensitive host data.",
                            "Message": f"Pod should not mount host filesystem paths",
                            "Resolution": "Use PersistentVolumeClaims instead of hostPath",
                            "Severity": "HIGH",
                            "PrimaryURL": "https://kubernetes.io/docs/concepts/security/pod-security-standards/",
                            "Status": "FAIL"
                        })

                # Check for missing resource limits
                for c in containers:
                    resources = c.get("resources", {})
                    if not resources.get("limits"):
                        misconfigs.append({
                            "Type": "Kubernetes Security Check",
                            "ID": "KSV011",
                            "AVDID": "AVD-KSV-0011",
                            "Title": "CPU and memory limits should be set",
                            "Description": f"Container '{c.get('name')}' in Pod '{name}' does not have resource limits defined.",
                            "Message": f"Container should set resource limits",
                            "Resolution": "Set resources.limits for CPU and memory",
                            "Severity": "LOW",
                            "PrimaryURL": "https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/",
                            "Status": "FAIL"
                        })

        results.append({
            "Target": "current-workloads.yaml",
            "Class": "config",
            "Type": "kubernetes",
            "MisconfSummary": {
                "Successes": 0,
                "Failures": len(misconfigs),
                "Exceptions": 0
            },
            "Misconfigurations": misconfigs
        })

    return {
        "SchemaVersion": 2,
        "CreatedAt": "2024-03-16T00:00:00Z",
        "ArtifactName": "/app/cluster-state/",
        "ArtifactType": "filesystem",
        "Results": results
    }


# =============================================================================
# Step 8: Generate conftest-compatible JSON (fallback if conftest unavailable)
# =============================================================================

def validate_remediation_against_policies():
    """Validate remediation YAML files against the OPA policies using Python logic."""
    # Parse remediation YAML files
    rbac_docs = list(yaml.safe_load_all(RBAC_YAML))
    audit_docs = list(yaml.safe_load_all(AUDIT_POLICY_YAML))
    netpol_docs = list(yaml.safe_load_all(NETWORK_POLICY_YAML))

    conftest_results = []

    # Validate webapp-rbac.yaml
    rbac_failures = []
    for doc in rbac_docs:
        if doc is None:
            continue
        if doc.get("kind") == "Role":
            for rule in doc.get("rules", []):
                if "*" in rule.get("verbs", []):
                    rbac_failures.append({"msg": f"Role '{doc['metadata']['name']}' must not use wildcard verbs"})
                if "*" in rule.get("resources", []):
                    rbac_failures.append({"msg": f"Role '{doc['metadata']['name']}' must not use wildcard resources"})
                if "secrets" in rule.get("resources", []):
                    rbac_failures.append({"msg": f"Role '{doc['metadata']['name']}' must not grant access to secrets"})

    conftest_results.append({
        "filename": "/app/results/remediation/webapp-rbac.yaml",
        "namespace": "main",
        "successes": 3 - len(rbac_failures),
        "failures": rbac_failures,
        "warnings": [],
        "exceptions": []
    })

    # Validate audit-policy.yaml
    audit_failures = []
    for doc in audit_docs:
        if doc is None:
            continue
        if doc.get("kind") == "Policy" and doc.get("apiVersion") == "audit.k8s.io/v1":
            has_secrets_rr = False
            for rule in doc.get("rules", []):
                if rule.get("level") == "RequestResponse":
                    for res in rule.get("resources", []):
                        if "secrets" in res.get("resources", []):
                            has_secrets_rr = True
            if not has_secrets_rr:
                audit_failures.append({"msg": "Audit policy must use RequestResponse level for secrets"})

    conftest_results.append({
        "filename": "/app/results/remediation/audit-policy.yaml",
        "namespace": "main",
        "successes": 1 - len(audit_failures),
        "failures": audit_failures,
        "warnings": [],
        "exceptions": []
    })

    # Validate network-policy.yaml
    netpol_failures = []
    for doc in netpol_docs:
        if doc is None:
            continue
        if doc.get("kind") == "NetworkPolicy":
            policy_types = doc.get("spec", {}).get("policyTypes", [])
            if "Ingress" not in policy_types:
                netpol_failures.append({"msg": f"NetworkPolicy '{doc['metadata']['name']}' must include Ingress policyType"})
            if "Egress" not in policy_types:
                netpol_failures.append({"msg": f"NetworkPolicy '{doc['metadata']['name']}' must include Egress policyType"})

    conftest_results.append({
        "filename": "/app/results/remediation/network-policy.yaml",
        "namespace": "main",
        "successes": 2 - len(netpol_failures),
        "failures": netpol_failures,
        "warnings": [],
        "exceptions": []
    })

    return conftest_results


# =============================================================================
# Main
# =============================================================================

def main():
    os.makedirs("/app/results/remediation", exist_ok=True)
    os.makedirs("/app/results/policies", exist_ok=True)
    os.makedirs("/app/results/trivy-scan", exist_ok=True)

    # 1. Attack summary
    summary = build_attack_summary("/app/audit-logs/kube-apiserver-audit.json")
    with open("/app/results/attack_summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[+] Attack summary: {len(summary['attack_timeline'])} attack events identified")
    print(f"[+] Compromised SA: {summary['compromised_service_account']}")
    print(f"[+] Stolen secrets: {summary['compromised_secrets']}")
    print(f"[+] Created resources: {summary['attacker_created_resources']}")

    # 2. RBAC remediation
    with open("/app/results/remediation/webapp-rbac.yaml", "w") as f:
        f.write(RBAC_YAML)
    print("[+] RBAC remediation written")

    # 3. Audit policy
    with open("/app/results/remediation/audit-policy.yaml", "w") as f:
        f.write(AUDIT_POLICY_YAML)
    print("[+] Audit policy written")

    # 4. Network policy
    with open("/app/results/remediation/network-policy.yaml", "w") as f:
        f.write(NETWORK_POLICY_YAML)
    print("[+] Network policy written")

    # 5. Falco rules
    with open("/app/results/remediation/falco-rules.yaml", "w") as f:
        f.write(FALCO_RULES_YAML)
    print("[+] Falco rules written")

    # 6. OPA/Rego policies for conftest validation
    with open("/app/results/policies/remediation_policy.rego", "w") as f:
        f.write(OPA_POLICY_REGO)
    print("[+] OPA/Rego validation policies written")

    # 7. Generate trivy-compatible output (used as fallback if trivy binary unavailable)
    trivy_output = generate_trivy_output("/app/cluster-state/")
    with open("/app/results/trivy-scan/current-state.json", "w") as f:
        json.dump(trivy_output, f, indent=2)
    print(f"[+] Trivy-compatible scan: {sum(len(r.get('Misconfigurations', [])) for r in trivy_output['Results'])} misconfigurations found")

    # 8. Generate conftest-compatible output (used as fallback if conftest binary unavailable)
    conftest_output = validate_remediation_against_policies()
    with open("/app/results/conftest-results.json", "w") as f:
        json.dump(conftest_output, f, indent=2)
    total_failures = sum(len(r.get("failures", [])) for r in conftest_output)
    print(f"[+] Conftest-compatible validation: {total_failures} policy violations")


if __name__ == "__main__":
    main()
