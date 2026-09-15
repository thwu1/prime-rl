#!/usr/bin/env python3
"""
Kubernetes RBAC Audit Tool — Fixed Version

Fixes applied:
1. load_manifests: also reads .json files (not just .yaml/.yml)
2. resolve_aggregation: fixed-point iteration for transitive aggregation chains
3. SA namespace defaulting: enrich ServiceAccount subjects from binding namespace
4. Escalation detection: cross-scope create_pods (cluster + namespace combined)
"""

import json
import os
from collections import defaultdict

import yaml


def load_manifests(directory):
    """Load all manifest files from directory (YAML and JSON)."""
    objects = []
    for filename in sorted(os.listdir(directory)):
        filepath = os.path.join(directory, filename)
        if filename.endswith((".yaml", ".yml")):
            with open(filepath) as f:
                for doc in yaml.safe_load_all(f):
                    if doc is not None:
                        objects.append(doc)
        elif filename.endswith(".json"):
            with open(filepath) as f:
                data = json.load(f)
                if isinstance(data, list):
                    objects.extend(data)
                elif isinstance(data, dict):
                    if data.get("kind", "").endswith("List"):
                        objects.extend(data.get("items", []))
                    else:
                        objects.append(data)
    return objects


def categorize_objects(objects):
    """Categorize Kubernetes RBAC objects by kind."""
    cluster_roles = {}
    roles = {}
    cluster_role_bindings = []
    role_bindings = []

    for obj in objects:
        kind = obj.get("kind", "")
        meta = obj.get("metadata", {})
        name = meta.get("name", "")
        namespace = meta.get("namespace", "")

        if kind == "ClusterRole":
            cluster_roles[name] = obj
        elif kind == "Role":
            roles[(namespace, name)] = obj
        elif kind == "ClusterRoleBinding":
            cluster_role_bindings.append(obj)
        elif kind == "RoleBinding":
            role_bindings.append(obj)

    return cluster_roles, roles, cluster_role_bindings, role_bindings


def resolve_aggregation(cluster_roles):
    """Resolve ClusterRole aggregation with fixed-point iteration for transitive chains."""
    for _ in range(10):
        before = sum(len(cr.get("rules", [])) for cr in cluster_roles.values())

        for name, cr in cluster_roles.items():
            agg_rule = cr.get("aggregationRule")
            if not agg_rule:
                continue

            selectors = agg_rule.get("clusterRoleSelectors", [])
            aggregated_rules = []

            for other_name, other_cr in cluster_roles.items():
                if other_name == name:
                    continue
                other_labels = other_cr.get("metadata", {}).get("labels", {})

                for selector in selectors:
                    match_labels = selector.get("matchLabels", {})
                    if match_labels and all(
                        other_labels.get(k) == v for k, v in match_labels.items()
                    ):
                        aggregated_rules.extend(other_cr.get("rules", []))
                        break

            cr["rules"] = aggregated_rules

        after = sum(len(cr.get("rules", [])) for cr in cluster_roles.values())
        if before == after:
            break

    return cluster_roles


def _enrich_subject(subject, binding_namespace=""):
    """Enrich a subject with default namespace from binding for ServiceAccounts."""
    enriched = dict(subject)
    if enriched.get("kind") == "ServiceAccount" and not enriched.get("namespace"):
        enriched["namespace"] = binding_namespace
    return enriched


def subject_key(subject):
    """Create a canonical key for a subject."""
    kind = subject.get("kind", "")
    name = subject.get("name", "")
    ns = subject.get("namespace", "")
    if kind == "ServiceAccount":
        return f"ServiceAccount:{ns}:{name}"
    if kind == "Group":
        return f"Group:{name}"
    return f"User:{name}"


def subjects_match(binding_subject, query_subject):
    """Check whether a binding subject matches a query subject."""
    if binding_subject.get("kind") != query_subject.get("kind"):
        return False
    if binding_subject.get("name") != query_subject.get("name"):
        return False
    if query_subject.get("kind") == "ServiceAccount":
        return binding_subject.get("namespace", "") == query_subject.get(
            "namespace", ""
        )
    return True


def normalize_rules(rules):
    """Normalize rules, stripping nonResourceURL entries."""
    out = []
    for rule in rules:
        if "nonResourceURLs" in rule:
            continue
        out.append(
            {
                "apiGroups": list(rule.get("apiGroups", [])),
                "resources": list(rule.get("resources", [])),
                "verbs": list(rule.get("verbs", [])),
            }
        )
    return out


def get_role_rules(role_ref, cluster_roles, roles, namespace=""):
    """Resolve rules from a roleRef."""
    kind = role_ref.get("kind", "")
    name = role_ref.get("name", "")
    if kind == "ClusterRole" and name in cluster_roles:
        return cluster_roles[name].get("rules", [])
    if kind == "Role" and (namespace, name) in roles:
        return roles[(namespace, name)].get("rules", [])
    return []


# -- effective permissions ---------------------------------------------------


def compute_effective_permissions(subjects_to_query, cluster_roles, roles, crbs, rbs):
    result = {}
    for spec in subjects_to_query:
        key = subject_key(spec)
        cluster_wide = []
        namespaced = defaultdict(list)

        # ClusterRoleBindings -> cluster-wide
        for crb in crbs:
            for s in crb.get("subjects", []):
                enriched = _enrich_subject(s)
                if subjects_match(enriched, spec):
                    rules = get_role_rules(
                        crb.get("roleRef", {}), cluster_roles, roles
                    )
                    cluster_wide.extend(normalize_rules(rules))

        # RoleBindings -> namespace-scoped
        for rb in rbs:
            rb_ns = rb.get("metadata", {}).get("namespace", "")
            for s in rb.get("subjects", []):
                enriched = _enrich_subject(s, rb_ns)
                if subjects_match(enriched, spec):
                    rules = get_role_rules(
                        rb.get("roleRef", {}), cluster_roles, roles, rb_ns
                    )
                    namespaced[rb_ns].extend(normalize_rules(rules))

        result[key] = {
            "cluster_wide": cluster_wide,
            "namespaced": dict(namespaced),
        }
    return result


# -- escalation detection ---------------------------------------------------


def _collect_all_subjects(crbs, rbs):
    """Enumerate every unique subject across all bindings with SA enrichment."""
    subjects = set()
    for crb in crbs:
        for s in crb.get("subjects", []):
            enriched = _enrich_subject(s)
            subjects.add(
                (enriched.get("kind", ""), enriched.get("name", ""),
                 enriched.get("namespace", ""))
            )
    for rb in rbs:
        rb_ns = rb.get("metadata", {}).get("namespace", "")
        for s in rb.get("subjects", []):
            enriched = _enrich_subject(s, rb_ns)
            subjects.add(
                (enriched.get("kind", ""), enriched.get("name", ""),
                 enriched.get("namespace", ""))
            )
    return subjects


def _verb_matches(verbs, target):
    return target in verbs or "*" in verbs


def _resource_in(resources, targets):
    return "*" in resources or any(r in targets for r in resources)


def _apigroup_in(api_groups, targets):
    return "*" in api_groups or any(g in targets for g in api_groups)


def detect_escalation_paths(cluster_roles, roles, crbs, rbs):
    all_subjects = _collect_all_subjects(crbs, rbs)
    paths = []
    seen = set()

    for kind, name, ns in all_subjects:
        spec = {"kind": kind, "name": name}
        if ns:
            spec["namespace"] = ns
        key = subject_key(spec)

        # Gather rules per scope
        scoped_rules = {}

        # cluster scope
        cluster_rules = []
        for crb in crbs:
            for s in crb.get("subjects", []):
                enriched = _enrich_subject(s)
                if subjects_match(enriched, spec):
                    cluster_rules.extend(
                        get_role_rules(crb.get("roleRef", {}), cluster_roles, roles)
                    )
        if cluster_rules:
            scoped_rules["cluster"] = cluster_rules

        # namespace scopes
        for rb in rbs:
            rb_ns = rb.get("metadata", {}).get("namespace", "")
            for s in rb.get("subjects", []):
                enriched = _enrich_subject(s, rb_ns)
                if subjects_match(enriched, spec):
                    ns_key = f"namespace:{rb_ns}"
                    scoped_rules.setdefault(ns_key, [])
                    scoped_rules[ns_key].extend(
                        get_role_rules(
                            rb.get("roleRef", {}), cluster_roles, roles, rb_ns
                        )
                    )

        # Get cluster-wide rules for cross-scope create_pods detection
        cluster_rule_list = scoped_rules.get("cluster", [])

        for scope, rule_list in scoped_rules.items():
            for rule in rule_list:
                verbs = rule.get("verbs", [])
                resources = rule.get("resources", [])
                api_groups = rule.get("apiGroups", [])

                # bind
                if (
                    _verb_matches(verbs, "bind")
                    and _resource_in(
                        resources,
                        [
                            "roles",
                            "clusterroles",
                            "rolebindings",
                            "clusterrolebindings",
                        ],
                    )
                    and _apigroup_in(api_groups, ["rbac.authorization.k8s.io"])
                ):
                    entry = (key, "bind", scope)
                    if entry not in seen:
                        seen.add(entry)
                        paths.append(
                            {
                                "subject": key,
                                "type": "bind",
                                "scope": scope,
                                "detail": (
                                    f"{key} can bind roles/clusterroles in {scope}"
                                ),
                            }
                        )

                # escalate
                if (
                    _verb_matches(verbs, "escalate")
                    and _resource_in(resources, ["roles", "clusterroles"])
                    and _apigroup_in(api_groups, ["rbac.authorization.k8s.io"])
                ):
                    entry = (key, "escalate", scope)
                    if entry not in seen:
                        seen.add(entry)
                        paths.append(
                            {
                                "subject": key,
                                "type": "escalate",
                                "scope": scope,
                                "detail": (
                                    f"{key} can escalate roles/clusterroles in {scope}"
                                ),
                            }
                        )

                # impersonate
                if _verb_matches(verbs, "impersonate") and _resource_in(
                    resources, ["users", "groups", "serviceaccounts"]
                ):
                    entry = (key, "impersonate", scope)
                    if entry not in seen:
                        seen.add(entry)
                        paths.append(
                            {
                                "subject": key,
                                "type": "impersonate",
                                "scope": scope,
                                "detail": (
                                    f"{key} can impersonate users/groups/SAs in {scope}"
                                ),
                            }
                        )

            # create_pods: combine with cluster-wide rules for namespace scopes
            if scope == "cluster":
                pods_check_rules = rule_list
            else:
                pods_check_rules = rule_list + cluster_rule_list

            can_create_pods = False
            can_exec = False
            for rule in pods_check_rules:
                verbs = rule.get("verbs", [])
                resources = rule.get("resources", [])
                api_groups = rule.get("apiGroups", [])

                if _apigroup_in(api_groups, [""]):
                    if _verb_matches(verbs, "create") and _resource_in(
                        resources, ["pods"]
                    ):
                        can_create_pods = True
                    if _resource_in(resources, ["pods/exec"]) and any(
                        _verb_matches(verbs, v) for v in ["create", "get"]
                    ):
                        can_exec = True

                # wildcard covers everything
                if "*" in resources and "*" in verbs:
                    can_create_pods = True
                    can_exec = True

            if can_create_pods and can_exec:
                entry = (key, "create_pods", scope)
                if entry not in seen:
                    seen.add(entry)
                    paths.append(
                        {
                            "subject": key,
                            "type": "create_pods",
                            "scope": scope,
                            "detail": (
                                f"{key} can create pods with arbitrary SAs and "
                                f"exec into them in {scope}"
                            ),
                        }
                    )

    return paths


# -- wildcard detection ------------------------------------------------------


def detect_wildcard_roles(cluster_roles, roles):
    results = []
    for name, cr in cluster_roles.items():
        wf = _wildcard_fields(cr.get("rules", []))
        if wf:
            results.append(
                {"name": name, "kind": "ClusterRole", "wildcard_fields": wf}
            )
    for (ns, name), role in roles.items():
        wf = _wildcard_fields(role.get("rules", []))
        if wf:
            results.append(
                {
                    "name": name,
                    "kind": "Role",
                    "namespace": ns,
                    "wildcard_fields": wf,
                }
            )
    return results


def _wildcard_fields(rules):
    fields = set()
    for rule in rules:
        if "*" in rule.get("apiGroups", []):
            fields.add("apiGroups")
        if "*" in rule.get("resources", []):
            fields.add("resources")
        if "*" in rule.get("verbs", []):
            fields.add("verbs")
    return sorted(fields) if fields else None


# -- main --------------------------------------------------------------------


def main():
    manifest_dir = "/app/manifests"
    query_file = "/app/queries.json"
    output_dir = "/app/output"

    os.makedirs(output_dir, exist_ok=True)

    objects = load_manifests(manifest_dir)
    cluster_roles, roles_ns, crbs, rbs = categorize_objects(objects)
    cluster_roles = resolve_aggregation(cluster_roles)

    with open(query_file) as f:
        queries = json.load(f)

    subjects = queries.get("subjects", [])
    effective = compute_effective_permissions(
        subjects, cluster_roles, roles_ns, crbs, rbs
    )
    escalation = detect_escalation_paths(cluster_roles, roles_ns, crbs, rbs)
    wildcards = detect_wildcard_roles(cluster_roles, roles_ns)

    report = {
        "effective_permissions": effective,
        "escalation_paths": escalation,
        "wildcard_roles": wildcards,
    }

    out_path = os.path.join(output_dir, "report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report generated successfully: {out_path}")


if __name__ == "__main__":
    main()
