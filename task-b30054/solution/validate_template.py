#!/usr/bin/env python3
"""
Reusable cross-resource Kubernetes manifest validator.

Performs automated consistency checks across related Kubernetes resources
to detect configuration errors that require multi-resource analysis.

"""

import sys
import os
import glob
import json
import yaml


def load_manifests(directory):
    """Load all YAML manifests from a directory, handling multi-document files."""
    manifests = []
    for filepath in sorted(glob.glob(os.path.join(directory, "*.yaml")) +
                           glob.glob(os.path.join(directory, "*.yml"))):
        with open(filepath) as f:
            for doc in yaml.safe_load_all(f):
                if doc is not None:
                    manifests.append(doc)
    return manifests


def find_resource(manifests, kind, name):
    for m in manifests:
        if m.get("kind") == kind and m.get("metadata", {}).get("name") == name:
            return m
    return None


def find_all_by_kind(manifests, kind):
    return [m for m in manifests if m.get("kind") == kind]


def parse_storage_gi(value):
    s = str(value)
    if s.endswith("Gi"):
        return float(s[:-2])
    elif s.endswith("Mi"):
        return float(s[:-2]) / 1024.0
    elif s.endswith("Ti"):
        return float(s[:-2]) * 1024.0
    elif s.endswith("Ki"):
        return float(s[:-2]) / (1024.0 * 1024.0)
    return float(s)


def validate(manifests):
    """Run all cross-resource consistency checks. Returns list of issue dicts."""
    issues = []

    deployments = find_all_by_kind(manifests, "Deployment")
    services = find_all_by_kind(manifests, "Service")
    configmaps = find_all_by_kind(manifests, "ConfigMap")
    secrets = find_all_by_kind(manifests, "Secret")
    service_accounts = find_all_by_kind(manifests, "ServiceAccount")
    pvs = find_all_by_kind(manifests, "PersistentVolume")
    pvcs = find_all_by_kind(manifests, "PersistentVolumeClaim")
    netpols = find_all_by_kind(manifests, "NetworkPolicy")
    cronjobs = find_all_by_kind(manifests, "CronJob")
    role_bindings = find_all_by_kind(manifests, "RoleBinding")
    hpas = find_all_by_kind(manifests, "HorizontalPodAutoscaler")

    # 1. Service selector vs Deployment pod template labels
    for svc in services:
        svc_name = svc["metadata"]["name"]
        selector = svc["spec"].get("selector", {})
        for dep in deployments:
            dep_name = dep["metadata"]["name"]
            if dep_name == svc_name:
                pod_labels = dep["spec"]["template"]["metadata"]["labels"]
                for k, v in selector.items():
                    if k in pod_labels and pod_labels[k] != v:
                        issues.append({
                            "resource": f"Service/{svc_name}",
                            "check": "selector-label-match",
                            "message": (
                                f"Selector {k}={v} does not match Deployment "
                                f"pod label {k}={pod_labels[k]}"
                            )
                        })

    # 2. HTTP probe port vs container port consistency
    for dep in deployments:
        dep_name = dep["metadata"]["name"]
        for container in dep["spec"]["template"]["spec"].get("containers", []):
            c_ports = [p["containerPort"] for p in container.get("ports", [])]
            if not c_ports:
                continue
            for probe_type in ("livenessProbe", "readinessProbe", "startupProbe"):
                probe = container.get(probe_type)
                if probe and "httpGet" in probe:
                    pport = probe["httpGet"]["port"]
                    if pport not in c_ports:
                        issues.append({
                            "resource": f"Deployment/{dep_name}",
                            "check": "probe-port-match",
                            "message": (
                                f"{probe_type} httpGet port {pport} not in "
                                f"container ports {c_ports}"
                            )
                        })

    # 3. Resource requests/limits completeness under ResourceQuota
    has_quota = len(find_all_by_kind(manifests, "ResourceQuota")) > 0
    if has_quota:
        for dep in deployments:
            dep_name = dep["metadata"]["name"]
            for container in dep["spec"]["template"]["spec"].get("containers", []):
                res = container.get("resources", {})
                reqs = res.get("requests", {})
                lims = res.get("limits", {})
                if not reqs or not lims:
                    issues.append({
                        "resource": f"Deployment/{dep_name}",
                        "check": "resource-constraints",
                        "message": (
                            f"Container '{container.get('name', '?')}' missing "
                            f"resource requests/limits with ResourceQuota active"
                        )
                    })

    # 4. Service targetPort vs container port agreement
    for svc in services:
        svc_name = svc["metadata"]["name"]
        selector = svc["spec"].get("selector", {})
        if not selector:
            continue
        for dep in deployments:
            pod_labels = dep["spec"]["template"]["metadata"]["labels"]
            if all(pod_labels.get(k) == v for k, v in selector.items()):
                containers = dep["spec"]["template"]["spec"].get("containers", [])
                if containers and containers[0].get("ports"):
                    c_port = containers[0]["ports"][0]["containerPort"]
                    for sp in svc["spec"].get("ports", []):
                        tp = sp.get("targetPort")
                        if tp is not None and tp != c_port:
                            issues.append({
                                "resource": f"Service/{svc_name}",
                                "check": "target-port-match",
                                "message": (
                                    f"targetPort {tp} does not match container "
                                    f"port {c_port}"
                                )
                            })

    # 5. ConfigMap key reference integrity
    for dep in deployments:
        dep_name = dep["metadata"]["name"]
        for container in dep["spec"]["template"]["spec"].get("containers", []):
            for env_var in container.get("env", []):
                cmref = env_var.get("valueFrom", {}).get("configMapKeyRef")
                if cmref:
                    cm = find_resource(manifests, "ConfigMap", cmref.get("name", ""))
                    if cm:
                        cm_data = cm.get("data", {})
                        if cmref.get("key") not in cm_data:
                            issues.append({
                                "resource": f"Deployment/{dep_name}",
                                "check": "configmap-key-ref",
                                "message": (
                                    f"Key '{cmref['key']}' not found in ConfigMap "
                                    f"'{cmref['name']}' (available: {list(cm_data.keys())})"
                                )
                            })

    # 6. ServiceAccount name reference integrity
    for dep in deployments:
        dep_name = dep["metadata"]["name"]
        sa_name = dep["spec"]["template"]["spec"].get("serviceAccountName")
        if sa_name and sa_name != "default":
            sa = find_resource(manifests, "ServiceAccount", sa_name)
            if not sa:
                issues.append({
                    "resource": f"Deployment/{dep_name}",
                    "check": "serviceaccount-ref",
                    "message": f"ServiceAccount '{sa_name}' not found in manifests"
                })

    # 7. Security context root-access auditing
    for dep in deployments:
        dep_name = dep["metadata"]["name"]
        pod_sc = dep["spec"]["template"]["spec"].get("securityContext", {})
        for container in dep["spec"]["template"]["spec"].get("containers", []):
            c_sc = container.get("securityContext", {})
            uid = c_sc.get("runAsUser", pod_sc.get("runAsUser"))
            non_root = c_sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot"))
            if uid == 0 or non_root is False:
                issues.append({
                    "resource": f"Deployment/{dep_name}",
                    "check": "security-root-access",
                    "message": (
                        f"Container '{container.get('name', '?')}' may run as root "
                        f"(runAsUser={uid}, runAsNonRoot={non_root})"
                    )
                })

    # 8. Secret volume reference integrity
    for dep in deployments:
        dep_name = dep["metadata"]["name"]
        for vol in dep["spec"]["template"]["spec"].get("volumes", []):
            if "secret" in vol:
                sec_name = vol["secret"].get("secretName", "")
                if not find_resource(manifests, "Secret", sec_name):
                    issues.append({
                        "resource": f"Deployment/{dep_name}",
                        "check": "secret-volume-ref",
                        "message": f"Secret '{sec_name}' referenced in volume not found"
                    })

    # 9. PVC storage capacity vs PV capacity
    for pvc in pvcs:
        pvc_name = pvc["metadata"]["name"]
        pvc_sc = pvc["spec"].get("storageClassName", "")
        pvc_storage = pvc["spec"].get("resources", {}).get("requests", {}).get("storage")
        if not pvc_storage:
            continue
        for pv in pvs:
            pv_sc = pv["spec"].get("storageClassName", "")
            pv_storage = pv["spec"].get("capacity", {}).get("storage")
            if pvc_sc == pv_sc and pv_storage:
                if parse_storage_gi(pvc_storage) > parse_storage_gi(pv_storage):
                    issues.append({
                        "resource": f"PersistentVolumeClaim/{pvc_name}",
                        "check": "storage-capacity",
                        "message": (
                            f"PVC requests {pvc_storage} exceeding PV capacity "
                            f"{pv_storage}"
                        )
                    })

    # 10. PVC access mode compatibility with PV
    for pvc in pvcs:
        pvc_name = pvc["metadata"]["name"]
        pvc_sc = pvc["spec"].get("storageClassName", "")
        pvc_modes = set(pvc["spec"].get("accessModes", []))
        for pv in pvs:
            pv_sc = pv["spec"].get("storageClassName", "")
            pv_modes = set(pv["spec"].get("accessModes", []))
            if pvc_sc == pv_sc and pvc_modes and pv_modes:
                if not pvc_modes.issubset(pv_modes):
                    issues.append({
                        "resource": f"PersistentVolumeClaim/{pvc_name}",
                        "check": "access-mode-compat",
                        "message": (
                            f"PVC access modes {sorted(pvc_modes)} not subset of "
                            f"PV access modes {sorted(pv_modes)}"
                        )
                    })

    # 11. NetworkPolicy ingress pod selector validation
    for np in netpols:
        np_name = np["metadata"]["name"]
        for rule in np["spec"].get("ingress", []):
            for from_rule in rule.get("from", []):
                if "podSelector" in from_rule:
                    sel = from_rule["podSelector"].get("matchLabels", {})
                    if sel:
                        any_match = any(
                            all(
                                d["spec"]["template"]["metadata"]["labels"].get(k) == v
                                for k, v in sel.items()
                            )
                            for d in deployments
                        )
                        if not any_match:
                            issues.append({
                                "resource": f"NetworkPolicy/{np_name}",
                                "check": "netpol-ingress-selector",
                                "message": (
                                    f"Ingress podSelector {sel} matches no "
                                    f"Deployment pod labels"
                                )
                            })

    # 12. CronJob schedule format validation
    for cj in cronjobs:
        cj_name = cj["metadata"]["name"]
        schedule = cj["spec"].get("schedule", "")
        fields = schedule.strip().split()
        if len(fields) != 5:
            issues.append({
                "resource": f"CronJob/{cj_name}",
                "check": "cron-schedule-format",
                "message": (
                    f"Schedule '{schedule}' has {len(fields)} fields (expected 5)"
                )
            })

    # 13. RoleBinding subject ServiceAccount reference validation
    for rb in role_bindings:
        rb_name = rb["metadata"]["name"]
        for subject in rb.get("subjects", []):
            if subject.get("kind") == "ServiceAccount":
                sa_name = subject.get("name", "")
                if sa_name and sa_name != "default":
                    sa = find_resource(manifests, "ServiceAccount", sa_name)
                    if not sa:
                        issues.append({
                            "resource": f"RoleBinding/{rb_name}",
                            "check": "rolebinding-subject-ref",
                            "message": (
                                f"Subject references ServiceAccount '{sa_name}' "
                                f"not found in manifests"
                            )
                        })

    # 14. HPA scaleTargetRef validation
    for hpa in hpas:
        hpa_name = hpa["metadata"]["name"]
        target_ref = hpa["spec"].get("scaleTargetRef", {})
        target_kind = target_ref.get("kind", "Deployment")
        target_name = target_ref.get("name", "")
        if target_name:
            target = find_resource(manifests, target_kind, target_name)
            if not target:
                issues.append({
                    "resource": f"HorizontalPodAutoscaler/{hpa_name}",
                    "check": "hpa-target-ref",
                    "message": (
                        f"scaleTargetRef targets {target_kind}/{target_name} "
                        f"which does not exist"
                    )
                })

    return issues


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <manifest-directory>", file=sys.stderr)
        sys.exit(2)

    directory = sys.argv[1]
    if not os.path.isdir(directory):
        print(f"Error: '{directory}' is not a directory", file=sys.stderr)
        sys.exit(2)

    manifests = load_manifests(directory)
    issues = validate(manifests)

    output = {"issues": issues, "total": len(issues)}
    print(json.dumps(output, indent=2))

    sys.exit(0 if len(issues) == 0 else 1)


if __name__ == "__main__":
    main()
