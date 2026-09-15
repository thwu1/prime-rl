#!/usr/bin/env python3
"""Kubernetes audit log forensics solver.

Analyzes K8s API server audit logs, identifies attack chain, produces
IOCs, Falco detection rules, and hardened audit policy.

"""
import json
import os


AUDIT_LOG_PATH = "/app/audit-logs/kube-apiserver-audit.jsonl"
FINDINGS_DIR = "/app/findings"


def load_audit_logs():
    events = []
    with open(AUDIT_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def analyze_attack(events):
    """Identify the attack chain by behavioral analysis.

    Strategy:
    1. Find service accounts operating outside their normal namespace scope
    2. Look for RBAC manipulation (create clusterrolebindings)
    3. Look for cross-namespace secret access
    4. Look for privileged pod creation, exec, namespace creation, persistence
    5. Correlate by source IP and user agent anomalies
    """
    # Group events by user
    user_events = {}
    for e in events:
        user = e["user"]["username"]
        if user not in user_events:
            user_events[user] = []
        user_events[user].append(e)

    # Focus on service accounts that access cluster-scoped or cross-namespace resources
    # A namespace-scoped SA accessing cluster-scoped resources is suspicious
    suspicious_users = set()
    for user, user_evts in user_events.items():
        if "system:serviceaccount:" not in user:
            continue
        # Extract SA's home namespace
        parts = user.split(":")
        if len(parts) >= 4:
            home_ns = parts[2]
        else:
            continue

        for e in user_evts:
            obj = e.get("objectRef", {})
            resource = obj.get("resource", "")
            event_ns = obj.get("namespace")

            # Cluster-scoped RBAC access from namespace SA is suspicious
            if resource in ("clusterroles", "clusterrolebindings") and not event_ns:
                suspicious_users.add(user)
                break
            # Cross-namespace secret access is suspicious
            if resource == "secrets" and event_ns and event_ns != home_ns:
                suspicious_users.add(user)
                break

    # Identify the attacker: the suspicious user
    attacker_user = None
    for u in suspicious_users:
        attacker_user = u
        break

    if not attacker_user:
        raise RuntimeError("Could not identify compromised identity")

    # Determine attacker source IP by finding the IP used for suspicious operations
    attacker_evts = user_events[attacker_user]

    # Find IPs used for cluster-scoped operations
    ip_counts = {}
    for e in attacker_evts:
        obj = e.get("objectRef", {})
        resource = obj.get("resource", "")
        event_ns = obj.get("namespace")
        ips = e.get("sourceIPs", [])
        if resource in ("clusterroles", "clusterrolebindings", "namespaces") or \
           (resource == "secrets" and event_ns and event_ns != "production"):
            for ip in ips:
                ip_counts[ip] = ip_counts.get(ip, 0) + 1

    attacker_ip = max(ip_counts, key=ip_counts.get) if ip_counts else ""

    # Find attacker user agent
    attacker_ua = ""
    for e in attacker_evts:
        if attacker_ip in e.get("sourceIPs", []):
            attacker_ua = e.get("userAgent", "")
            break

    # Extract attack events (from attacker IP)
    attack_events = []
    for e in attacker_evts:
        if attacker_ip not in e.get("sourceIPs", []):
            continue
        obj = e.get("objectRef", {})
        resource = obj.get("resource", "")
        verb = e.get("verb", "")
        name = obj.get("name")
        namespace = obj.get("namespace")
        subresource = obj.get("subresource")

        # Determine MITRE technique
        mitre = determine_mitre_technique(verb, resource, name, namespace, subresource, e)

        desc = build_description(verb, resource, name, namespace, subresource, e)

        event_entry = {
            "timestamp": e["requestReceivedTimestamp"],
            "verb": verb,
            "resource": resource,
            "name": name,
            "namespace": namespace,
            "user": attacker_user,
            "source_ip": attacker_ip,
            "description": desc,
            "mitre_technique": mitre
        }

        if subresource:
            event_entry["subresource"] = subresource

        attack_events.append(event_entry)

    # Sort chronologically
    attack_events.sort(key=lambda x: x["timestamp"])

    # Extract IOCs
    exfiltrated_secrets = []
    malicious_resources = {
        "clusterrolebindings": [],
        "pods": [],
        "namespaces": [],
        "deployments": [],
        "serviceaccounts": [],
        "rolebindings": []
    }

    for e in attack_events:
        resource = e["resource"]
        verb = e["verb"]
        name = e.get("name")
        namespace = e.get("namespace")

        if resource == "secrets" and verb in ("get",) and name:
            exfiltrated_secrets.append({"name": name, "namespace": namespace})
        elif resource == "clusterrolebindings" and verb == "create" and name:
            malicious_resources["clusterrolebindings"].append({"name": name, "namespace": None})
        elif resource == "pods" and verb == "create" and name and not e.get("subresource"):
            malicious_resources["pods"].append({"name": name, "namespace": namespace})
        elif resource == "namespaces" and verb == "create" and name:
            malicious_resources["namespaces"].append({"name": name})
        elif resource == "deployments" and verb == "create" and name:
            malicious_resources["deployments"].append({"name": name, "namespace": namespace})
        elif resource == "serviceaccounts" and verb == "create" and name:
            malicious_resources["serviceaccounts"].append({"name": name, "namespace": namespace})
        elif resource == "rolebindings" and verb == "create" and name:
            malicious_resources["rolebindings"].append({"name": name, "namespace": namespace})

    iocs = {
        "compromised_identity": attacker_user,
        "attacker_source_ip": attacker_ip,
        "attacker_user_agent": attacker_ua,
        "exfiltrated_secrets": exfiltrated_secrets,
        "malicious_resources": malicious_resources
    }

    return attack_events, iocs


def determine_mitre_technique(verb, resource, name, namespace, subresource, event):
    """Map attack events to MITRE ATT&CK technique IDs."""
    if resource in ("clusterroles", "clusterrolebindings") and verb == "list":
        return "T1613"  # Container and Resource Discovery
    if resource == "clusterrolebindings" and verb == "create":
        return "T1078"  # Valid Accounts (privilege escalation via RBAC)
    if resource == "secrets" and verb in ("list", "get"):
        return "T1552"  # Unsecured Credentials
    if resource == "pods" and verb == "create" and subresource == "exec":
        return "T1609"  # Container Administration Command
    if resource == "pods" and verb == "create" and not subresource:
        # Check for privileged pod
        req_obj = event.get("requestObject", {})
        spec = req_obj.get("spec", {}) if isinstance(req_obj, dict) else {}
        if spec.get("hostPID") or spec.get("hostNetwork"):
            return "T1610"  # Deploy Container
        return "T1610"
    if resource == "namespaces" and verb == "create":
        return "T1036"  # Masquerading
    if resource == "deployments" and verb == "create":
        return "T1053"  # Scheduled Task/Job (persistence via workload)
    if resource == "serviceaccounts" and verb == "create":
        return "T1136"  # Create Account
    if resource == "rolebindings" and verb == "create":
        return "T1098"  # Account Manipulation
    return "T1078"


def build_description(verb, resource, name, namespace, subresource, event):
    """Build human-readable description of attack event."""
    if resource in ("clusterroles", "clusterrolebindings") and verb == "list":
        return f"Enumerated {resource} for RBAC reconnaissance"
    if resource == "clusterrolebindings" and verb == "create":
        req_obj = event.get("requestObject", {})
        if isinstance(req_obj, dict):
            role_ref = req_obj.get("roleRef", {})
            role_name = role_ref.get("name", "unknown")
            return f"Created ClusterRoleBinding '{name}' granting '{role_name}' privileges (privilege escalation)"
        return f"Created ClusterRoleBinding '{name}'"
    if resource == "secrets" and verb == "list":
        return f"Listed secrets in namespace '{namespace}' (credential enumeration)"
    if resource == "secrets" and verb == "get":
        return f"Read secret '{name}' in namespace '{namespace}' (credential exfiltration)"
    if resource == "pods" and verb == "create" and subresource == "exec":
        return f"Executed command in pod '{name}' in namespace '{namespace}' (container administration)"
    if resource == "pods" and verb == "create" and not subresource:
        return f"Created privileged pod '{name}' in namespace '{namespace}' with hostPID, hostNetwork, and root volume mount"
    if resource == "namespaces" and verb == "create":
        return f"Created namespace '{name}' for persistence staging"
    if resource == "deployments" and verb == "create":
        return f"Created deployment '{name}' in namespace '{namespace}' with C2 beacon (persistence)"
    if resource == "serviceaccounts" and verb == "create":
        return f"Created service account '{name}' in namespace '{namespace}' for persistent access"
    if resource == "rolebindings" and verb == "create":
        return f"Created RoleBinding '{name}' granting admin privileges to persistence service account"
    return f"{verb} {resource} {name or ''} in {namespace or 'cluster-scope'}"


def generate_falco_rules():
    """Generate Falco k8s_audit detection rules."""
    rules = [
        {
            "rule": "K8s ClusterRoleBinding to Cluster-Admin",
            "desc": "Detect creation of ClusterRoleBinding that grants cluster-admin privileges, a common privilege escalation technique",
            "condition": 'ka.verb=create and ka.target.resource=clusterrolebindings and ka.req.binding.role=cluster-admin',
            "output": "ClusterRoleBinding created granting cluster-admin (user=%ka.user.name binding=%ka.target.name role=%ka.req.binding.role)",
            "priority": "CRITICAL",
            "tags": ["k8s_audit", "rbac", "privilege_escalation", "mitre_T1078"],
            "source": "k8s_audit"
        },
        {
            "rule": "K8s Service Account Accessing Secrets Outside Home Namespace",
            "desc": "Detect a service account accessing secrets in a namespace other than its own, indicating potential credential theft",
            "condition": 'ka.verb in (get, list) and ka.target.resource=secrets and ka.user.name startswith "system:serviceaccount:" and not ka.target.namespace in (ka.user.namespace)',
            "output": "Cross-namespace secret access (user=%ka.user.name secret=%ka.target.name namespace=%ka.target.namespace verb=%ka.verb)",
            "priority": "WARNING",
            "tags": ["k8s_audit", "secrets", "credential_access", "mitre_T1552"],
            "source": "k8s_audit"
        },
        {
            "rule": "K8s Privileged Pod Created",
            "desc": "Detect creation of a pod with privileged security context, hostPID, or hostNetwork capabilities",
            "condition": 'ka.verb=create and ka.target.resource=pods and (ka.req.pod.containers.privileged=true or ka.req.pod.host_network=true or ka.req.pod.host_pid=true)',
            "output": "Privileged pod created (user=%ka.user.name pod=%ka.target.name namespace=%ka.target.namespace privileged=%ka.req.pod.containers.privileged hostNetwork=%ka.req.pod.host_network hostPID=%ka.req.pod.host_pid)",
            "priority": "CRITICAL",
            "tags": ["k8s_audit", "pod_security", "execution", "mitre_T1610"],
            "source": "k8s_audit"
        },
        {
            "rule": "K8s Exec Into Pod by Service Account",
            "desc": "Detect exec operations into pods initiated by service accounts rather than human users",
            "condition": 'ka.verb=create and ka.target.resource=pods and ka.target.subresource=exec and ka.user.name startswith "system:serviceaccount:"',
            "output": "Pod exec by service account (user=%ka.user.name pod=%ka.target.name namespace=%ka.target.namespace)",
            "priority": "ERROR",
            "tags": ["k8s_audit", "exec", "execution", "mitre_T1609"],
            "source": "k8s_audit"
        },
        {
            "rule": "K8s Suspicious Namespace Creation by Service Account",
            "desc": "Detect namespace creation by service accounts, which is unusual and may indicate persistence staging",
            "condition": 'ka.verb=create and ka.target.resource=namespaces and ka.user.name startswith "system:serviceaccount:"',
            "output": "Namespace created by service account (user=%ka.user.name namespace=%ka.target.name)",
            "priority": "WARNING",
            "tags": ["k8s_audit", "persistence", "mitre_T1036"],
            "source": "k8s_audit"
        },
        {
            "rule": "K8s RBAC Reconnaissance by Service Account",
            "desc": "Detect service accounts listing cluster-scoped RBAC resources, indicating reconnaissance for privilege escalation",
            "condition": 'ka.verb=list and ka.target.resource in (clusterroles, clusterrolebindings) and ka.user.name startswith "system:serviceaccount:"',
            "output": "RBAC enumeration by service account (user=%ka.user.name resource=%ka.target.resource)",
            "priority": "WARNING",
            "tags": ["k8s_audit", "rbac", "discovery", "mitre_T1613"],
            "source": "k8s_audit"
        }
    ]
    return rules


def generate_audit_policy():
    """Generate comprehensive Kubernetes audit policy."""
    policy = {
        "apiVersion": "audit.k8s.io/v1",
        "kind": "Policy",
        "rules": [
            {
                "level": "RequestResponse",
                "resources": [
                    {
                        "group": "rbac.authorization.k8s.io",
                        "resources": ["clusterroles", "clusterrolebindings", "roles", "rolebindings"]
                    }
                ],
                "verbs": ["create", "update", "patch", "delete"]
            },
            {
                "level": "Metadata",
                "resources": [
                    {
                        "group": "rbac.authorization.k8s.io",
                        "resources": ["clusterroles", "clusterrolebindings", "roles", "rolebindings"]
                    }
                ],
                "verbs": ["get", "list", "watch"]
            },
            {
                "level": "Metadata",
                "resources": [
                    {
                        "group": "",
                        "resources": ["secrets"]
                    }
                ]
            },
            {
                "level": "RequestResponse",
                "resources": [
                    {
                        "group": "",
                        "resources": ["pods/exec", "pods/attach", "pods/portforward"]
                    }
                ]
            },
            {
                "level": "Request",
                "resources": [
                    {
                        "group": "",
                        "resources": ["pods"]
                    }
                ],
                "verbs": ["create", "update", "patch", "delete"]
            },
            {
                "level": "Metadata",
                "resources": [
                    {
                        "group": "",
                        "resources": ["namespaces", "serviceaccounts"]
                    }
                ],
                "verbs": ["create", "delete"]
            },
            {
                "level": "Request",
                "resources": [
                    {
                        "group": "apps",
                        "resources": ["deployments", "daemonsets", "statefulsets"]
                    }
                ],
                "verbs": ["create", "update", "patch", "delete"]
            },
            {
                "level": "Metadata",
                "omitStages": ["RequestReceived"]
            }
        ]
    }
    return policy


def yaml_scalar(v):
    """Format a scalar value for YAML output."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # Quote strings that contain special YAML characters
    if any(c in s for c in (':', '{', '}', '[', ']', ',', '&', '*', '#', '?',
                             '|', '-', '<', '>', '=', '!', '%', '@', '`', '"', "'")):
        escaped = s.replace("'", "''")
        return f"'{escaped}'"
    if not s or s.lower() in ('true', 'false', 'null', 'yes', 'no'):
        return f"'{s}'"
    return s


def write_yaml_value(f, v, indent=0):
    """Recursively write a YAML value."""
    prefix = "  " * indent
    if isinstance(v, dict):
        for i, (k, val) in enumerate(v.items()):
            if isinstance(val, (dict,)):
                f.write(f"{prefix}{k}:\n")
                write_yaml_value(f, val, indent + 1)
            elif isinstance(val, list):
                f.write(f"{prefix}{k}:\n")
                for item in val:
                    if isinstance(item, dict):
                        first = True
                        for kk, vv in item.items():
                            item_prefix = f"{prefix}  - " if first else f"{prefix}    "
                            first = False
                            if isinstance(vv, list):
                                if all(isinstance(x, str) for x in vv):
                                    items_str = ", ".join(yaml_scalar(x) for x in vv)
                                    f.write(f"{item_prefix}{kk}: [{items_str}]\n")
                                else:
                                    f.write(f"{item_prefix}{kk}:\n")
                                    for sub in vv:
                                        if isinstance(sub, dict):
                                            sfirst = True
                                            for sk, sv in sub.items():
                                                sp = f"{prefix}      - " if sfirst else f"{prefix}        "
                                                sfirst = False
                                                if isinstance(sv, list) and all(isinstance(x, str) for x in sv):
                                                    si = ", ".join(yaml_scalar(x) for x in sv)
                                                    f.write(f"{sp}{sk}: [{si}]\n")
                                                else:
                                                    f.write(f"{sp}{sk}: {yaml_scalar(sv)}\n")
                                        else:
                                            f.write(f"{prefix}      - {yaml_scalar(sub)}\n")
                            elif isinstance(vv, dict):
                                f.write(f"{item_prefix}{kk}:\n")
                                write_yaml_value(f, vv, indent + 3)
                            else:
                                f.write(f"{item_prefix}{kk}: {yaml_scalar(vv)}\n")
                    else:
                        f.write(f"{prefix}  - {yaml_scalar(item)}\n")
            else:
                f.write(f"{prefix}{k}: {yaml_scalar(val)}\n")


def write_yaml_rules(rules, f):
    """Write a list of Falco rules as YAML."""
    for rule in rules:
        f.write(f"- rule: {yaml_scalar(rule['rule'])}\n")
        f.write(f"  desc: {yaml_scalar(rule['desc'])}\n")
        f.write(f"  condition: {yaml_scalar(rule['condition'])}\n")
        f.write(f"  output: {yaml_scalar(rule['output'])}\n")
        f.write(f"  priority: {rule['priority']}\n")
        tags_str = ", ".join(yaml_scalar(t) for t in rule.get("tags", []))
        f.write(f"  tags: [{tags_str}]\n")
        if "source" in rule:
            f.write(f"  source: {rule['source']}\n")
        f.write("\n")


def write_yaml_policy(policy, f):
    """Write a Kubernetes audit policy as YAML."""
    f.write(f"apiVersion: {policy['apiVersion']}\n")
    f.write(f"kind: {policy['kind']}\n")
    f.write("rules:\n")
    for rule in policy["rules"]:
        f.write(f"  - level: {rule['level']}\n")
        if "resources" in rule:
            f.write("    resources:\n")
            for rg in rule["resources"]:
                f.write(f"      - group: {yaml_scalar(rg['group'])}\n")
                res_str = ", ".join(yaml_scalar(r) for r in rg["resources"])
                f.write(f"        resources: [{res_str}]\n")
        if "verbs" in rule:
            verbs_str = ", ".join(yaml_scalar(v) for v in rule["verbs"])
            f.write(f"    verbs: [{verbs_str}]\n")
        if "omitStages" in rule:
            stages_str = ", ".join(yaml_scalar(s) for s in rule["omitStages"])
            f.write(f"    omitStages: [{stages_str}]\n")


def main():
    os.makedirs(FINDINGS_DIR, exist_ok=True)

    # Load audit logs
    events = load_audit_logs()
    print(f"Loaded {len(events)} audit log entries")

    # Analyze attack chain
    timeline, iocs = analyze_attack(events)
    print(f"Identified {len(timeline)} attack events")
    print(f"Compromised identity: {iocs['compromised_identity']}")
    print(f"Attacker source IP: {iocs['attacker_source_ip']}")

    # Write timeline
    with open(os.path.join(FINDINGS_DIR, "attack_timeline.json"), "w") as f:
        json.dump(timeline, f, indent=2)

    # Write IOCs
    with open(os.path.join(FINDINGS_DIR, "indicators_of_compromise.json"), "w") as f:
        json.dump(iocs, f, indent=2)

    # Generate and write Falco detection rules
    rules = generate_falco_rules()
    with open(os.path.join(FINDINGS_DIR, "detection_rules.yaml"), "w") as f:
        write_yaml_rules(rules, f)

    # Generate and write audit policy
    policy = generate_audit_policy()
    with open(os.path.join(FINDINGS_DIR, "audit_policy.yaml"), "w") as f:
        write_yaml_policy(policy, f)

    print("All findings written to /app/findings/")


if __name__ == "__main__":
    main()
