#!/usr/bin/env python3
"""
Kubernetes manifest auditor and fixer.

Parses all K8s YAML manifests from /app/manifests/, builds a cross-resource
dependency index, identifies configuration errors through systematic
cross-reference validation, applies fixes, and writes results.

"""

import yaml
import json
import os
import copy
import glob
import sys


def load_manifests(directory):
    """Load all YAML manifests from a directory into a list of entries."""
    resources = []
    yaml_files = sorted(glob.glob(os.path.join(directory, "*.yaml")) +
                        glob.glob(os.path.join(directory, "*.yml")))
    print(f"Found {len(yaml_files)} YAML files in {directory}:", file=sys.stderr)
    for filepath in yaml_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath) as f:
                content = f.read()
            docs = list(yaml.safe_load_all(content))
            valid_docs = [d for d in docs if d is not None]
            print(f"  {filename}: {len(valid_docs)} resource(s)", file=sys.stderr)
            for doc in valid_docs:
                kind = doc.get("kind", "unknown")
                name = doc.get("metadata", {}).get("name", "unknown")
                print(f"    -> {kind}/{name}", file=sys.stderr)
                resources.append({"filename": filename, "resource": doc})
        except Exception as e:
            print(f"  ERROR loading {filename}: {e}", file=sys.stderr)
    return resources


def find_by_kind_name(resources, kind, name):
    """Find a resource entry by kind and metadata.name."""
    for entry in resources:
        r = entry["resource"]
        if r.get("kind") == kind and r.get("metadata", {}).get("name") == name:
            return entry
    return None


def find_all_by_kind(resources, kind):
    """Return all resource entries of a given kind."""
    return [e for e in resources if e["resource"].get("kind") == kind]


def parse_storage_gi(value):
    """Parse a Kubernetes storage quantity string into GiB."""
    s = str(value)
    if s.endswith("Gi"):
        return float(s[:-2])
    elif s.endswith("Mi"):
        return float(s[:-2]) / 1024.0
    elif s.endswith("Ti"):
        return float(s[:-2]) * 1024.0
    return float(s)


def fuzzy_match_name(ref_name, candidates):
    """Find the best fuzzy match for a resource name among candidates.

    Uses multiple strategies: token overlap, common prefix, substring matching.
    Returns the matched candidate name or None.
    """
    ref_tokens = set(ref_name.split("-"))
    ref_stripped = ref_name.replace("-", "")

    best_match = None
    best_score = 0

    for cand_entry in candidates:
        cand_name = cand_entry["resource"]["metadata"]["name"]
        cand_tokens = set(cand_name.split("-"))
        cand_stripped = cand_name.replace("-", "")

        # Strategy 1: Token overlap (split by hyphen, count shared tokens)
        overlap = ref_tokens & cand_tokens
        token_score = len(overlap)

        # Strategy 2: Common prefix length (on stripped names)
        prefix_len = 0
        for a, b in zip(ref_stripped, cand_stripped):
            if a == b:
                prefix_len += 1
            else:
                break

        # Strategy 3: One name is a prefix/substring of the other
        substring_bonus = 0
        if ref_stripped.startswith(cand_stripped[:4]) or cand_stripped.startswith(ref_stripped[:4]):
            substring_bonus = 2

        # Combined score: weight token overlap heavily, then prefix, then substring
        score = token_score * 10 + prefix_len + substring_bonus

        if score > best_score and (token_score >= 1 or prefix_len >= 3):
            best_score = score
            best_match = cand_name

    return best_match


def audit_and_fix(resources):
    """
    Perform cross-resource validation on all Kubernetes manifests.
    Identifies mismatches by comparing actual values across related resources
    and applies computed fixes. Returns a list of finding dicts.
    """
    findings = []

    # Build resource indices
    deployments = find_all_by_kind(resources, "Deployment")
    services = find_all_by_kind(resources, "Service")
    configmaps = find_all_by_kind(resources, "ConfigMap")
    secrets = find_all_by_kind(resources, "Secret")
    service_accounts = find_all_by_kind(resources, "ServiceAccount")
    pvs = find_all_by_kind(resources, "PersistentVolume")
    pvcs = find_all_by_kind(resources, "PersistentVolumeClaim")
    netpols = find_all_by_kind(resources, "NetworkPolicy")
    cronjobs = find_all_by_kind(resources, "CronJob")
    role_bindings = find_all_by_kind(resources, "RoleBinding")
    hpas = find_all_by_kind(resources, "HorizontalPodAutoscaler")

    print(f"\nResource index: {len(deployments)} Deployments, {len(services)} Services, "
          f"{len(configmaps)} ConfigMaps, {len(secrets)} Secrets, "
          f"{len(service_accounts)} ServiceAccounts, {len(pvs)} PVs, {len(pvcs)} PVCs, "
          f"{len(netpols)} NetworkPolicies, {len(cronjobs)} CronJobs, "
          f"{len(role_bindings)} RoleBindings, {len(hpas)} HPAs",
          file=sys.stderr)

    # ---------------------------------------------------------------
    # CHECK 1: Service selector vs Deployment pod template labels
    # ---------------------------------------------------------------
    for svc_entry in services:
        svc = svc_entry["resource"]
        svc_name = svc["metadata"]["name"]
        svc_selector = svc["spec"].get("selector", {})

        for dep_entry in deployments:
            dep = dep_entry["resource"]
            dep_name = dep["metadata"]["name"]
            if dep_name == svc_name:
                pod_labels = dep["spec"]["template"]["metadata"]["labels"]
                for key, sel_val in list(svc_selector.items()):
                    actual_val = pod_labels.get(key)
                    if actual_val is not None and actual_val != sel_val:
                        findings.append({
                            "file": svc_entry["filename"],
                            "resource": f"Service/{svc_name}",
                            "severity": "critical",
                            "category": "selector",
                            "description": (
                                f"Service selector '{key}: {sel_val}' does not match "
                                f"Deployment pod label '{key}: {actual_val}'. "
                                f"Fixed selector to '{key}: {actual_val}'."
                            ),
                        })
                        svc["spec"]["selector"][key] = actual_val

    # ---------------------------------------------------------------
    # CHECK 2: Probe ports vs container ports
    # ---------------------------------------------------------------
    for dep_entry in deployments:
        dep = dep_entry["resource"]
        dep_name = dep["metadata"]["name"]
        for container in dep["spec"]["template"]["spec"]["containers"]:
            container_ports = [
                p["containerPort"] for p in container.get("ports", [])
            ]
            if not container_ports:
                continue
            primary_port = container_ports[0]

            for probe_type in ("livenessProbe", "readinessProbe", "startupProbe"):
                probe = container.get(probe_type)
                if probe and "httpGet" in probe:
                    probe_port = probe["httpGet"]["port"]
                    if probe_port not in container_ports:
                        findings.append({
                            "file": dep_entry["filename"],
                            "resource": f"Deployment/{dep_name}",
                            "severity": "high",
                            "category": "reference",
                            "description": (
                                f"Container '{container['name']}' {probe_type} port "
                                f"{probe_port} does not match any container port "
                                f"{container_ports}. Fixed to {primary_port}."
                            ),
                        })
                        probe["httpGet"]["port"] = primary_port

    # ---------------------------------------------------------------
    # CHECK 3: Resource requests/limits (required by ResourceQuota)
    # ---------------------------------------------------------------
    quota_entry = find_by_kind_name(resources, "ResourceQuota", "ecommerce-quota")
    if quota_entry:
        for dep_entry in deployments:
            dep = dep_entry["resource"]
            dep_name = dep["metadata"]["name"]
            for container in dep["spec"]["template"]["spec"]["containers"]:
                res = container.get("resources")
                if not res or not res.get("requests") or not res.get("limits"):
                    findings.append({
                        "file": dep_entry["filename"],
                        "resource": f"Deployment/{dep_name}",
                        "severity": "critical",
                        "category": "resources",
                        "description": (
                            f"Container '{container['name']}' missing resource "
                            f"requests/limits. ResourceQuota in namespace requires "
                            f"them. Added default resources."
                        ),
                    })
                    if not res:
                        container["resources"] = {}
                    if not container["resources"].get("requests"):
                        container["resources"]["requests"] = {
                            "cpu": "100m",
                            "memory": "128Mi",
                        }
                    if not container["resources"].get("limits"):
                        container["resources"]["limits"] = {
                            "cpu": "500m",
                            "memory": "512Mi",
                        }

    # ---------------------------------------------------------------
    # CHECK 4: Service targetPort vs container port
    # ---------------------------------------------------------------
    for svc_entry in services:
        svc = svc_entry["resource"]
        svc_name = svc["metadata"]["name"]
        svc_selector = svc["spec"].get("selector", {})

        for dep_entry in deployments:
            dep = dep_entry["resource"]
            pod_labels = dep["spec"]["template"]["metadata"]["labels"]
            if all(pod_labels.get(k) == v for k, v in svc_selector.items()):
                containers = dep["spec"]["template"]["spec"]["containers"]
                if containers and containers[0].get("ports"):
                    c_port = containers[0]["ports"][0]["containerPort"]
                    for sp in svc["spec"]["ports"]:
                        t_port = sp.get("targetPort")
                        if t_port is not None and t_port != c_port:
                            findings.append({
                                "file": svc_entry["filename"],
                                "resource": f"Service/{svc_name}",
                                "severity": "critical",
                                "category": "reference",
                                "description": (
                                    f"Service targetPort {t_port} does not match "
                                    f"container port {c_port}. Fixed to {c_port}."
                                ),
                            })
                            sp["targetPort"] = c_port

    # ---------------------------------------------------------------
    # CHECK 5: ConfigMap key references
    # ---------------------------------------------------------------
    for dep_entry in deployments:
        dep = dep_entry["resource"]
        dep_name = dep["metadata"]["name"]
        for container in dep["spec"]["template"]["spec"]["containers"]:
            for env_var in container.get("env", []):
                vf = env_var.get("valueFrom", {})
                cmref = vf.get("configMapKeyRef")
                if cmref:
                    cm_entry = find_by_kind_name(
                        resources, "ConfigMap", cmref["name"]
                    )
                    if cm_entry:
                        cm_data = cm_entry["resource"].get("data", {})
                        ref_key = cmref["key"]
                        if ref_key not in cm_data:
                            ref_tokens = set(
                                ref_key.lower().replace("_", " ").split()
                            )
                            matched = None
                            for candidate in cm_data:
                                cand_tokens = set(
                                    candidate.lower().replace("_", " ").split()
                                )
                                if ref_tokens & cand_tokens:
                                    matched = candidate
                                    break
                            if matched:
                                findings.append({
                                    "file": dep_entry["filename"],
                                    "resource": f"Deployment/{dep_name}",
                                    "severity": "high",
                                    "category": "reference",
                                    "description": (
                                        f"ConfigMap key '{ref_key}' not found in "
                                        f"ConfigMap '{cmref['name']}'. Closest match: "
                                        f"'{matched}'. Fixed reference."
                                    ),
                                })
                                cmref["key"] = matched

    # ---------------------------------------------------------------
    # CHECK 6: ServiceAccount references in Deployments
    # ---------------------------------------------------------------
    for dep_entry in deployments:
        dep = dep_entry["resource"]
        dep_name = dep["metadata"]["name"]
        pod_spec = dep["spec"]["template"]["spec"]
        sa_ref = pod_spec.get("serviceAccountName")
        if sa_ref:
            sa_entry = find_by_kind_name(resources, "ServiceAccount", sa_ref)
            if not sa_entry:
                dep_ns = dep["metadata"].get("namespace", "default")
                candidates = [
                    e for e in service_accounts
                    if e["resource"]["metadata"].get("namespace", "default") == dep_ns
                ]
                matched_sa = fuzzy_match_name(sa_ref, candidates)
                if matched_sa:
                    findings.append({
                        "file": dep_entry["filename"],
                        "resource": f"Deployment/{dep_name}",
                        "severity": "high",
                        "category": "reference",
                        "description": (
                            f"ServiceAccount '{sa_ref}' not found. Matched to "
                            f"'{matched_sa}' in namespace '{dep_ns}'. Fixed."
                        ),
                    })
                    pod_spec["serviceAccountName"] = matched_sa

    # ---------------------------------------------------------------
    # CHECK 7: Security context — running as root
    # ---------------------------------------------------------------
    for dep_entry in deployments:
        dep = dep_entry["resource"]
        dep_name = dep["metadata"]["name"]
        pod_spec = dep["spec"]["template"]["spec"]
        pod_sc = pod_spec.get("securityContext", {})

        for container in pod_spec["containers"]:
            c_sc = container.get("securityContext", {})
            uid = c_sc.get("runAsUser", pod_sc.get("runAsUser"))
            non_root = c_sc.get("runAsNonRoot", pod_sc.get("runAsNonRoot"))

            if uid == 0 or non_root is False:
                findings.append({
                    "file": dep_entry["filename"],
                    "resource": f"Deployment/{dep_name}",
                    "severity": "critical",
                    "category": "security",
                    "description": (
                        f"Container '{container['name']}' runs as root "
                        f"(runAsUser={uid}, runAsNonRoot={non_root}). "
                        f"Fixed to runAsUser=1000, runAsNonRoot=true."
                    ),
                })
                if uid == 0:
                    c_sc["runAsUser"] = 1000
                    container["securityContext"] = c_sc
                pod_sc["runAsNonRoot"] = True
                pod_spec["securityContext"] = pod_sc

    # ---------------------------------------------------------------
    # CHECK 8: Secret volume references
    # ---------------------------------------------------------------
    for dep_entry in deployments:
        dep = dep_entry["resource"]
        dep_name = dep["metadata"]["name"]
        pod_spec = dep["spec"]["template"]["spec"]

        for volume in pod_spec.get("volumes", []):
            if "secret" in volume:
                sec_name = volume["secret"]["secretName"]
                sec_entry = find_by_kind_name(resources, "Secret", sec_name)
                if not sec_entry:
                    dep_ns = dep["metadata"].get("namespace", "default")
                    candidates = [
                        e for e in secrets
                        if e["resource"]["metadata"].get("namespace", "default")
                        == dep_ns
                    ]
                    matched = fuzzy_match_name(sec_name, candidates)
                    if matched:
                        findings.append({
                            "file": dep_entry["filename"],
                            "resource": f"Deployment/{dep_name}",
                            "severity": "critical",
                            "category": "reference",
                            "description": (
                                f"Secret '{sec_name}' not found. Matched to "
                                f"'{matched}'. Fixed volume reference."
                            ),
                        })
                        volume["secret"]["secretName"] = matched

    # ---------------------------------------------------------------
    # CHECK 9 & 10: PV/PVC compatibility
    # ---------------------------------------------------------------
    for pvc_entry in pvcs:
        pvc = pvc_entry["resource"]
        pvc_name = pvc["metadata"]["name"]
        pvc_sc = pvc["spec"].get("storageClassName", "")
        pvc_modes = set(pvc["spec"].get("accessModes", []))
        pvc_storage = pvc["spec"]["resources"]["requests"]["storage"]

        for pv_entry in pvs:
            pv = pv_entry["resource"]
            pv_name = pv["metadata"]["name"]
            pv_sc = pv["spec"].get("storageClassName", "")
            pv_modes = set(pv["spec"].get("accessModes", []))
            pv_storage = pv["spec"]["capacity"]["storage"]

            if pvc_sc == pv_sc:
                if parse_storage_gi(pvc_storage) > parse_storage_gi(pv_storage):
                    findings.append({
                        "file": pvc_entry["filename"],
                        "resource": f"PersistentVolumeClaim/{pvc_name}",
                        "severity": "high",
                        "category": "storage",
                        "description": (
                            f"PVC requests {pvc_storage} but PV '{pv_name}' "
                            f"only has {pv_storage}. Fixed PVC to {pv_storage}."
                        ),
                    })
                    pvc["spec"]["resources"]["requests"]["storage"] = pv_storage

                if not pvc_modes.issubset(pv_modes):
                    findings.append({
                        "file": pvc_entry["filename"],
                        "resource": f"PersistentVolumeClaim/{pvc_name}",
                        "severity": "high",
                        "category": "storage",
                        "description": (
                            f"PVC access modes {pvc_modes} not supported by "
                            f"PV '{pv_name}' (supports {pv_modes}). "
                            f"Fixed PVC access modes to match PV."
                        ),
                    })
                    pvc["spec"]["accessModes"] = sorted(pv_modes)

    # ---------------------------------------------------------------
    # CHECK 11: NetworkPolicy ingress selectors vs actual pod labels
    # ---------------------------------------------------------------
    for np_entry in netpols:
        np_res = np_entry["resource"]
        np_name = np_res["metadata"]["name"]

        for rule in np_res["spec"].get("ingress", []):
            for from_rule in rule.get("from", []):
                if "podSelector" in from_rule:
                    sel = from_rule["podSelector"].get("matchLabels", {})
                    any_match = any(
                        all(
                            d["resource"]["spec"]["template"]["metadata"][
                                "labels"
                            ].get(k)
                            == v
                            for k, v in sel.items()
                        )
                        for d in deployments
                    )
                    if not any_match and sel:
                        best_fix = None
                        for dep_entry in deployments:
                            dep_labels = dep_entry["resource"]["spec"][
                                "template"
                            ]["metadata"]["labels"]
                            for sk, sv in sel.items():
                                if sk in dep_labels:
                                    actual = dep_labels[sk]
                                    if sv in actual or actual.startswith(sv):
                                        best_fix = {sk: actual}
                        if best_fix:
                            findings.append({
                                "file": np_entry["filename"],
                                "resource": f"NetworkPolicy/{np_name}",
                                "severity": "critical",
                                "category": "networking",
                                "description": (
                                    f"Ingress selector {sel} matches no pods. "
                                    f"Fixed to {best_fix}."
                                ),
                            })
                            from_rule["podSelector"]["matchLabels"] = best_fix

    # ---------------------------------------------------------------
    # CHECK 12: CronJob schedule validation
    # ---------------------------------------------------------------
    for cj_entry in cronjobs:
        cj = cj_entry["resource"]
        cj_name = cj["metadata"]["name"]
        schedule = cj["spec"].get("schedule", "")
        fields = schedule.strip().split()

        if len(fields) != 5:
            fixed = " ".join(fields[:5]) if len(fields) > 5 else schedule
            findings.append({
                "file": cj_entry["filename"],
                "resource": f"CronJob/{cj_name}",
                "severity": "high",
                "category": "scheduling",
                "description": (
                    f"CronJob schedule '{schedule}' has {len(fields)} fields "
                    f"(expected 5). Fixed to '{fixed}'."
                ),
            })
            cj["spec"]["schedule"] = fixed

    # ---------------------------------------------------------------
    # CHECK 13: RoleBinding subject ServiceAccount references
    # ---------------------------------------------------------------
    print(f"\nChecking RoleBindings: {len(role_bindings)} found", file=sys.stderr)
    for rb_entry in role_bindings:
        rb = rb_entry["resource"]
        rb_name = rb["metadata"]["name"]
        rb_ns = rb["metadata"].get("namespace", "default")
        print(f"  RoleBinding/{rb_name} in ns={rb_ns}", file=sys.stderr)

        for subject in rb.get("subjects", []):
            if subject.get("kind") == "ServiceAccount":
                sa_ref = subject.get("name", "")
                sub_ns = subject.get("namespace", rb_ns)
                print(f"    Subject SA: '{sa_ref}' in ns={sub_ns}", file=sys.stderr)
                sa_entry = find_by_kind_name(resources, "ServiceAccount", sa_ref)
                if not sa_entry:
                    print(f"    SA '{sa_ref}' NOT found, searching candidates...", file=sys.stderr)
                    candidates = [
                        e for e in service_accounts
                        if e["resource"]["metadata"].get("namespace", "default") == sub_ns
                    ]
                    print(f"    Candidates: {[c['resource']['metadata']['name'] for c in candidates]}", file=sys.stderr)
                    matched_sa = fuzzy_match_name(sa_ref, candidates)
                    print(f"    Fuzzy match result: {matched_sa}", file=sys.stderr)
                    if matched_sa:
                        findings.append({
                            "file": rb_entry["filename"],
                            "resource": f"RoleBinding/{rb_name}",
                            "severity": "critical",
                            "category": "reference",
                            "description": (
                                f"Subject references ServiceAccount '{sa_ref}' "
                                f"which does not exist. Matched to "
                                f"'{matched_sa}'. Fixed."
                            ),
                        })
                        subject["name"] = matched_sa

    # ---------------------------------------------------------------
    # CHECK 14: HPA scaleTargetRef references
    # ---------------------------------------------------------------
    print(f"\nChecking HPAs: {len(hpas)} found", file=sys.stderr)
    for hpa_entry in hpas:
        hpa = hpa_entry["resource"]
        hpa_name = hpa["metadata"]["name"]
        target_ref = hpa["spec"].get("scaleTargetRef", {})
        target_kind = target_ref.get("kind", "Deployment")
        target_name = target_ref.get("name", "")
        print(f"  HPA/{hpa_name} targets {target_kind}/{target_name}", file=sys.stderr)

        target_entry = find_by_kind_name(resources, target_kind, target_name)
        if not target_entry:
            print(f"    Target '{target_name}' NOT found, searching candidates...", file=sys.stderr)
            candidates = find_all_by_kind(resources, target_kind)
            print(f"    Candidates: {[c['resource']['metadata']['name'] for c in candidates]}", file=sys.stderr)
            matched = fuzzy_match_name(target_name, candidates)
            print(f"    Fuzzy match result: {matched}", file=sys.stderr)
            if matched:
                findings.append({
                    "file": hpa_entry["filename"],
                    "resource": f"HorizontalPodAutoscaler/{hpa_name}",
                    "severity": "critical",
                    "category": "reference",
                    "description": (
                        f"scaleTargetRef targets {target_kind}/{target_name} "
                        f"which does not exist. Matched to '{matched}'. Fixed."
                    ),
                })
                target_ref["name"] = matched

    return findings


def write_manifests(resources, output_dir):
    """Write resources to YAML files, grouped by original filename."""
    os.makedirs(output_dir, exist_ok=True)

    by_file = {}
    for entry in resources:
        fn = entry["filename"]
        by_file.setdefault(fn, []).append(entry["resource"])

    for filename, docs in sorted(by_file.items()):
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w") as f:
            yaml.dump_all(docs, f, default_flow_style=False, sort_keys=False)


def main():
    manifests_dir = "/app/manifests"
    fixed_dir = "/app/fixed"
    audit_file = "/app/audit.json"

    # Verify manifest files exist
    yaml_files = sorted(glob.glob(os.path.join(manifests_dir, "*.yaml")))
    print(f"Manifest directory contents: {[os.path.basename(f) for f in yaml_files]}", file=sys.stderr)
    assert len(yaml_files) >= 10, f"Expected at least 10 YAML files, found {len(yaml_files)}"

    resources = load_manifests(manifests_dir)
    print(f"\nLoaded {len(resources)} resources from {manifests_dir}")

    resources = copy.deepcopy(resources)

    findings = audit_and_fix(resources)

    write_manifests(resources, fixed_dir)

    audit_report = {
        "findings": findings,
        "total_issues": len(findings),
    }
    with open(audit_file, "w") as f:
        json.dump(audit_report, f, indent=2)

    print(f"\nAudit complete: {len(findings)} issues found and fixed.")
    for i, finding in enumerate(findings, 1):
        print(f"  {i}. [{finding['severity']}] {finding['resource']}: "
              f"{finding['description'][:80]}...")
    print(f"\nFixed manifests: {fixed_dir}")
    print(f"Audit report: {audit_file}")


if __name__ == "__main__":
    main()
