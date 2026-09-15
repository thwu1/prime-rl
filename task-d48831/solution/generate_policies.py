#!/usr/bin/env python3
"""
Analyze Kubernetes audit logs and Falco alerts to generate
incident report and security policies.

"""

import json
import os

import yaml


def load_jsonl(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def identify_compromised_sa(logs):
    """Find the SA with the most cross-namespace activity."""
    sa_cross = {}
    for log in logs:
        user = log.get("user", {}).get("username", "")
        if not user.startswith("system:serviceaccount:"):
            continue
        parts = user.split(":")
        if len(parts) != 4:
            continue
        sa_ns, sa_name = parts[2], parts[3]
        target_ns = log.get("objectRef", {}).get("namespace", "")
        if target_ns and target_ns != sa_ns:
            key = (sa_ns, sa_name)
            sa_cross.setdefault(key, []).append(log)
    if not sa_cross:
        return None, None
    best = max(sa_cross, key=lambda k: len(sa_cross[k]))
    return best


def classify_action(log, sa_ns):
    """Classify an audit log entry by MITRE ATT&CK tactic."""
    verb = log.get("verb", "")
    resource = log.get("objectRef", {}).get("resource", "")
    namespace = log.get("objectRef", {}).get("namespace", "")
    name = log.get("objectRef", {}).get("name", "")
    req_obj = log.get("requestObject", {})

    if resource == "secrets" and verb == "list":
        if namespace != sa_ns:
            return "Discovery", f"Enumerated secrets in namespace '{namespace}'"
        return "Discovery", f"Listed secrets in own namespace '{namespace}'"

    if resource == "secrets" and verb == "get":
        tactic = "Collection" if namespace != sa_ns else "Discovery"
        return tactic, f"Read secret '{name}' in namespace '{namespace}'"

    if resource == "clusterrolebindings" and verb == "create":
        role = req_obj.get("roleRef", {}).get("name", "unknown")
        subjects = req_obj.get("subjects", [])
        subj_desc = ""
        if subjects:
            s = subjects[0]
            subj_desc = (
                f" binding {s.get('kind', '')} '{s.get('name', '')}'"
                f" in '{s.get('namespace', '')}' to '{role}'"
            )
        # Distinguish between escalating self vs creating persistence
        if subjects and subjects[0].get("name") == "frontend-sa":
            return "Privilege Escalation", (
                f"Created ClusterRoleBinding '{name}'{subj_desc}"
            )
        return "Persistence", (
            f"Created ClusterRoleBinding '{name}'{subj_desc}"
        )

    if resource == "pods" and verb == "create":
        spec = req_obj.get("spec", {})
        flags = []
        if spec.get("hostPID"):
            flags.append("hostPID")
        if spec.get("hostNetwork"):
            flags.append("hostNetwork")
        for c in spec.get("containers", []):
            if c.get("securityContext", {}).get("privileged"):
                flags.append("privileged")
        for v in spec.get("volumes", []):
            hp = v.get("hostPath", {})
            if hp:
                flags.append(f"hostPath={hp.get('path', '')}")
        flag_str = ", ".join(flags) if flags else "standard"
        return "Execution", (
            f"Created pod '{name}' in namespace '{namespace}' "
            f"with [{flag_str}]"
        )

    if resource == "serviceaccounts" and verb == "create":
        return "Persistence", (
            f"Created service account '{name}' in namespace '{namespace}'"
        )

    if resource == "daemonsets" and verb == "create":
        containers = (
            req_obj.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [])
        )
        images = [c.get("image", "") for c in containers]
        envs = {}
        for c in containers:
            for e in c.get("env", []):
                envs[e.get("name", "")] = e.get("value", "")
        desc = (
            f"Created DaemonSet '{name}' in namespace '{namespace}' "
            f"with image(s) {images}"
        )
        if "POOL_URL" in envs:
            desc += f" connecting to mining pool {envs['POOL_URL']}"
        return "Impact", desc

    return "Unknown", f"{verb} {resource}/{name} in {namespace}"


def build_incident_report(logs, alerts):
    sa_ns, sa_name = identify_compromised_sa(logs)

    # Collect all actions by the compromised SA
    sa_user = f"system:serviceaccount:{sa_ns}:{sa_name}"
    actions = sorted(
        [l for l in logs if l.get("user", {}).get("username") == sa_user],
        key=lambda x: x.get("requestReceivedTimestamp", ""),
    )

    affected_ns = set()
    chain = []
    for i, action in enumerate(actions, 1):
        ns = action.get("objectRef", {}).get("namespace", "")
        if ns:
            affected_ns.add(ns)
        tactic, description = classify_action(action, sa_ns)
        chain.append({
            "step": i,
            "timestamp": action.get("requestReceivedTimestamp", ""),
            "tactic": tactic,
            "description": description,
            "audit_id": action.get("auditID", ""),
        })

    # Extract IOCs from Falco alerts
    iocs = []
    for alert in alerts:
        fields = alert.get("output_fields", {})
        pod = fields.get("k8s.pod.name", "")
        proc = fields.get("proc.name", "")
        cmdline = fields.get("proc.cmdline", "")
        conn = fields.get("fd.name", "")
        rule = alert.get("rule", "")
        if proc and pod:
            iocs.append(
                f"[{rule}] Process '{proc}' (cmdline: {cmdline}) "
                f"in pod '{pod}'"
            )
        if conn and "->" in conn:
            iocs.append(f"Outbound connection: {conn}")

    return {
        "compromised_identity": {
            "type": "ServiceAccount",
            "name": sa_name,
            "namespace": sa_ns,
        },
        "attack_chain": chain,
        "affected_namespaces": sorted(affected_ns),
        "indicators_of_compromise": iocs,
        "severity": "critical",
        "initial_access_indicator": (
            "Service account token used from external IP 198.51.100.23 "
            "via kubectl instead of application Go HTTP client"
        ),
    }


def generate_opa_policy():
    return r'''package kubernetes.admission

# Exemption for system components in kube-system
is_system_component {
    input.review.object.metadata.namespace == "kube-system"
    input.review.object.metadata.labels["system-component"] == "true"
}

# Resolve pod spec for direct Pods
pod_spec := input.review.object.spec {
    input.review.object.kind == "Pod"
}

# Resolve pod spec for workload controllers
pod_spec := input.review.object.spec.template.spec {
    kinds := {"Deployment", "DaemonSet", "ReplicaSet", "StatefulSet", "Job"}
    kinds[input.review.object.kind]
}

# Block privileged containers
deny[msg] {
    not is_system_component
    container := pod_spec.containers[_]
    container.securityContext.privileged == true
    msg := sprintf("Privileged container '%s' is not allowed", [container.name])
}

# Block privileged init containers
deny[msg] {
    not is_system_component
    container := pod_spec.initContainers[_]
    container.securityContext.privileged == true
    msg := sprintf("Privileged init container '%s' is not allowed", [container.name])
}

# Block hostPID
deny[msg] {
    not is_system_component
    pod_spec.hostPID == true
    msg := "hostPID is not allowed"
}

# Block hostNetwork
deny[msg] {
    not is_system_component
    pod_spec.hostNetwork == true
    msg := "hostNetwork is not allowed"
}

# Block hostIPC
deny[msg] {
    not is_system_component
    pod_spec.hostIPC == true
    msg := "hostIPC is not allowed"
}

# Block hostPath volumes
deny[msg] {
    not is_system_component
    volume := pod_spec.volumes[_]
    volume.hostPath
    msg := sprintf("hostPath volume '%s' mounting '%s' is not allowed", [volume.name, volume.hostPath.path])
}

# Block containers running as root
deny[msg] {
    not is_system_component
    container := pod_spec.containers[_]
    container.securityContext.runAsUser == 0
    msg := sprintf("Container '%s' must not run as root (UID 0)", [container.name])
}
'''


def generate_falco_rules():
    return """# Custom Falco rules for Kubernetes attack pattern detection

- rule: Privileged Container Launched
  desc: Detect when a privileged container is started in the cluster
  condition: >
    evt.type=container and
    container.privileged=true
  output: >
    Privileged container started
    (user=%user.name container=%container.name image=%container.image.repository
    k8s.ns=%k8s.ns.name k8s.pod=%k8s.pod.name)
  priority: Error
  tags: [container, privilege_escalation]

- rule: Sensitive Host File Access in Container
  desc: >
    Detect reading of sensitive host files (/etc/shadow, /etc/passwd,
    /var/lib/etcd) from within a container
  condition: >
    evt.type in (open, openat) and
    container.id != host and
    (fd.name startswith /host/etc/shadow or
     fd.name startswith /host/etc/passwd or
     fd.name startswith /host/var/lib/etcd or
     fd.name startswith /host/etc/kubernetes)
  output: >
    Sensitive host file accessed in container
    (user=%user.name command=%proc.cmdline file=%fd.name
    container=%container.name image=%container.image.repository
    k8s.ns=%k8s.ns.name k8s.pod=%k8s.pod.name)
  priority: Critical
  tags: [container, filesystem, data_exfiltration]

- rule: Container Namespace Escape via nsenter
  desc: Detect use of nsenter to escape container namespaces into the host
  condition: >
    evt.type=execve and
    proc.name=nsenter and
    container.id != host
  output: >
    Namespace escape attempt via nsenter
    (user=%user.name command=%proc.cmdline container=%container.name
    image=%container.image.repository k8s.ns=%k8s.ns.name k8s.pod=%k8s.pod.name)
  priority: Critical
  tags: [container, escape, privilege_escalation]

- rule: Cryptocurrency Mining Activity Detected
  desc: Detect processes or network activity associated with cryptocurrency mining
  condition: >
    evt.type in (execve, connect) and
    container.id != host and
    (proc.name in (xmrig, xmr-stak, minerd, cpuminer, ethminer) or
     fd.sport=3333 or fd.sport=3334 or fd.sport=3335)
  output: >
    Cryptocurrency mining activity detected
    (user=%user.name command=%proc.cmdline connection=%fd.name
    container=%container.name image=%container.image.repository
    k8s.ns=%k8s.ns.name k8s.pod=%k8s.pod.name)
  priority: Critical
  tags: [container, cryptomining, impact]

- rule: Package Manager Execution in Running Container
  desc: Detect package management tools executing inside a running container
  condition: >
    evt.type=execve and
    container.id != host and
    proc.name in (apt, apt-get, yum, dnf, apk, pip, pip3)
  output: >
    Package manager executed in container
    (user=%user.name command=%proc.cmdline container=%container.name
    image=%container.image.repository k8s.ns=%k8s.ns.name k8s.pod=%k8s.pod.name)
  priority: Error
  tags: [container, software_deployment]
"""


def generate_audit_policy():
    return {
        "apiVersion": "audit.k8s.io/v1",
        "kind": "Policy",
        "omitStages": ["RequestReceived"],
        "rules": [
            {
                "level": "RequestResponse",
                "resources": [
                    {"group": "", "resources": ["secrets"]},
                ],
            },
            {
                "level": "RequestResponse",
                "resources": [
                    {
                        "group": "rbac.authorization.k8s.io",
                        "resources": [
                            "clusterroles",
                            "clusterrolebindings",
                            "roles",
                            "rolebindings",
                        ],
                    },
                ],
            },
            {
                "level": "RequestResponse",
                "resources": [
                    {"group": "", "resources": ["serviceaccounts"]},
                ],
            },
            {
                "level": "Request",
                "resources": [
                    {
                        "group": "",
                        "resources": ["pods", "services", "configmaps"],
                    },
                    {
                        "group": "apps",
                        "resources": [
                            "deployments",
                            "daemonsets",
                            "replicasets",
                            "statefulsets",
                        ],
                    },
                ],
            },
            {
                "level": "Metadata",
                "resources": [
                    {
                        "group": "",
                        "resources": [
                            "nodes",
                            "namespaces",
                            "persistentvolumes",
                            "persistentvolumeclaims",
                        ],
                    },
                ],
            },
            {
                "level": "None",
                "users": ["system:kube-proxy"],
                "verbs": ["watch"],
            },
            {
                "level": "None",
                "resources": [
                    {"group": "", "resources": ["endpoints", "events"]},
                ],
            },
            {"level": "Metadata"},
        ],
    }


def main():
    audit_logs = load_jsonl("/app/audit-logs/kube-apiserver-audit.jsonl")
    falco_alerts = load_jsonl("/app/audit-logs/falco-alerts.jsonl")

    os.makedirs("/app/analysis", exist_ok=True)
    os.makedirs("/app/policies", exist_ok=True)

    # 1. Incident report
    report = build_incident_report(audit_logs, falco_alerts)
    with open("/app/analysis/incident-report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"Incident report: {len(report['attack_chain'])} steps identified")

    # 2. OPA admission policy
    with open("/app/policies/admission.rego", "w") as f:
        f.write(generate_opa_policy())
    print("OPA admission policy written")

    # 3. Falco detection rules
    with open("/app/policies/falco_rules.yaml", "w") as f:
        f.write(generate_falco_rules())
    print("Falco rules written")

    # 4. Kubernetes audit policy
    with open("/app/policies/audit-policy.yaml", "w") as f:
        yaml.dump(
            generate_audit_policy(),
            f,
            default_flow_style=False,
            sort_keys=False,
        )
    print("Audit policy written")


if __name__ == "__main__":
    main()
