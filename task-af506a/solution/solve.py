#!/usr/bin/env python3
"""
Solution: Design and implement multi-tier platform governance.

Creates ResourceQuotas, LimitRanges, and Kyverno policies from the governance
specification, and fixes existing OTel, Prometheus, RBAC, and Crossplane configs.
"""

import os
import yaml
from difflib import SequenceMatcher


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_yaml_all(path):
    with open(path) as f:
        return [d for d in yaml.safe_load_all(f) if d is not None]


def save_yaml(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def save_yaml_all(path, docs):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump_all(docs, f, default_flow_style=False, sort_keys=False)


# ── Tier definitions derived from GOVERNANCE_SPEC.md ─────────────────────

TIERS = {
    "team-core": {
        "tier": "platinum",
        "req_cpu": "16",       # minimum requests.cpu in cores
        "req_mem": "64Gi",
        "lim_cpu": "24",       # maximum limits.cpu in cores
        "lim_mem": "96Gi",
        "pods": "100",
        "lr_max_cpu": "4",
        "lr_max_mem": "8Gi",
        "lr_default_cpu": "2",
        "lr_default_mem": "4Gi",
        "lr_default_req_cpu": "500m",
        "lr_default_req_mem": "1Gi",
        "lr_min_cpu": "100m",
        "lr_min_mem": "128Mi",
    },
    "team-analytics": {
        "tier": "gold",
        "req_cpu": "12",
        "req_mem": "48Gi",
        "lim_cpu": "18",
        "lim_mem": "72Gi",
        "pods": "60",
        "lr_max_cpu": "2",
        "lr_max_mem": "4Gi",
        "lr_default_cpu": "1",
        "lr_default_mem": "2Gi",
        "lr_default_req_cpu": "250m",
        "lr_default_req_mem": "512Mi",
        "lr_min_cpu": "100m",
        "lr_min_mem": "128Mi",
    },
    "team-edge": {
        "tier": "silver",
        "req_cpu": "8",
        "req_mem": "32Gi",
        "lim_cpu": "12",
        "lim_mem": "48Gi",
        "pods": "30",
        "lr_max_cpu": "1",
        "lr_max_mem": "2Gi",
        "lr_default_cpu": "500m",
        "lr_default_mem": "1Gi",
        "lr_default_req_cpu": "100m",
        "lr_default_req_mem": "128Mi",
        "lr_min_cpu": "50m",
        "lr_min_mem": "64Mi",
    },
}


def create_resource_quotas():
    """Create ResourceQuota for each tenant based on tier allocation rules."""
    for team, cfg in TIERS.items():
        quota = {
            "apiVersion": "v1",
            "kind": "ResourceQuota",
            "metadata": {
                "name": f"{team}-quota",
                "namespace": team,
                "labels": {
                    "platform.example.com/tenant": team,
                    "platform.example.com/tier": cfg["tier"],
                },
            },
            "spec": {
                "hard": {
                    "requests.cpu": cfg["req_cpu"],
                    "requests.memory": cfg["req_mem"],
                    "limits.cpu": cfg["lim_cpu"],
                    "limits.memory": cfg["lim_mem"],
                    "pods": cfg["pods"],
                },
            },
        }
        path = f"/app/tenants/{team}/resourcequota.yaml"
        save_yaml(path, quota)
        print(f"Created ResourceQuota for {team} ({cfg['tier']})")


def create_limit_ranges():
    """Create LimitRange for each tenant with tier-appropriate bounds."""
    for team, cfg in TIERS.items():
        lr = {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {
                "name": f"{team}-limits",
                "namespace": team,
                "labels": {
                    "platform.example.com/tenant": team,
                    "platform.example.com/tier": cfg["tier"],
                },
            },
            "spec": {
                "limits": [
                    {
                        "type": "Container",
                        "max": {
                            "cpu": cfg["lr_max_cpu"],
                            "memory": cfg["lr_max_mem"],
                        },
                        "default": {
                            "cpu": cfg["lr_default_cpu"],
                            "memory": cfg["lr_default_mem"],
                        },
                        "defaultRequest": {
                            "cpu": cfg["lr_default_req_cpu"],
                            "memory": cfg["lr_default_req_mem"],
                        },
                        "min": {
                            "cpu": cfg["lr_min_cpu"],
                            "memory": cfg["lr_min_mem"],
                        },
                    }
                ],
            },
        }
        path = f"/app/tenants/{team}/limitrange.yaml"
        save_yaml(path, lr)
        print(f"Created LimitRange for {team} ({cfg['tier']})")


def create_kyverno_require_labels():
    """Create Kyverno ClusterPolicy requiring standard labels on workloads."""
    policy = {
        "apiVersion": "kyverno.io/v1",
        "kind": "ClusterPolicy",
        "metadata": {
            "name": "require-labels",
            "annotations": {
                "policies.kyverno.io/title": "Require Labels",
                "policies.kyverno.io/description":
                    "All Deployments and StatefulSets must have "
                    "app.kubernetes.io/name and app.kubernetes.io/managed-by labels.",
            },
        },
        "spec": {
            "validationFailureAction": "Enforce",
            "background": True,
            "rules": [
                {
                    "name": "check-required-labels",
                    "match": {
                        "any": [
                            {
                                "resources": {
                                    "kinds": ["Deployment", "StatefulSet"],
                                    "apiVersions": ["apps/v1"],
                                },
                            }
                        ],
                    },
                    "validate": {
                        "message":
                            "Labels 'app.kubernetes.io/name' and "
                            "'app.kubernetes.io/managed-by' are required.",
                        "pattern": {
                            "metadata": {
                                "labels": {
                                    "app.kubernetes.io/name": "?*",
                                    "app.kubernetes.io/managed-by": "?*",
                                },
                            },
                        },
                    },
                }
            ],
        },
    }
    path = "/app/policies/require-labels.yaml"
    save_yaml(path, policy)
    print("Created Kyverno ClusterPolicy: require-labels")


def create_kyverno_enforce_limits():
    """Create Kyverno ClusterPolicy enforcing resource limits on Deployments."""
    policy = {
        "apiVersion": "kyverno.io/v1",
        "kind": "ClusterPolicy",
        "metadata": {
            "name": "enforce-resource-limits",
            "annotations": {
                "policies.kyverno.io/title": "Enforce Resource Limits",
                "policies.kyverno.io/description":
                    "All Deployment containers must declare CPU and memory limits.",
            },
        },
        "spec": {
            "validationFailureAction": "Enforce",
            "background": True,
            "rules": [
                {
                    "name": "check-container-limits",
                    "match": {
                        "any": [
                            {
                                "resources": {
                                    "kinds": ["Deployment"],
                                    "apiVersions": ["apps/v1"],
                                },
                            }
                        ],
                    },
                    "validate": {
                        "message":
                            "All containers must have resources.limits.cpu "
                            "and resources.limits.memory defined.",
                        "pattern": {
                            "spec": {
                                "template": {
                                    "spec": {
                                        "containers": [
                                            {
                                                "resources": {
                                                    "limits": {
                                                        "cpu": "?*",
                                                        "memory": "?*",
                                                    },
                                                },
                                            }
                                        ],
                                    },
                                },
                            },
                        },
                    },
                }
            ],
        },
    }
    path = "/app/policies/enforce-resource-limits.yaml"
    save_yaml(path, policy)
    print("Created Kyverno ClusterPolicy: enforce-resource-limits")


def fix_prometheus_alert_rules():
    """Fix HighErrorRate: add sum by (namespace, service) and for: 10m."""
    rules_doc = load_yaml("/app/monitoring/alerting-rules.yaml")

    for group in rules_doc["spec"]["groups"]:
        for rule in group.get("rules", []):
            if rule.get("alert") == "HighErrorRate":
                expr = str(rule["expr"])
                if "sum" not in expr.lower():
                    rule["expr"] = (
                        'sum by (namespace, service) (rate(http_requests_total{code=~"5.."}[5m])) '
                        '/ sum by (namespace, service) (rate(http_requests_total[5m])) > 0.05'
                    )
                    print("Fixed HighErrorRate: added sum by (namespace, service) aggregation")
                if "for" not in rule:
                    rule["for"] = "10m"
                    print("Fixed HighErrorRate: added for: 10m")

    save_yaml("/app/monitoring/alerting-rules.yaml", rules_doc)


def fix_otel_collector():
    """Fix OTel pipeline: processor ordering and exporter references."""
    collector = load_yaml("/app/monitoring/otel-collector.yaml")
    config = collector["spec"]["config"]

    defined_exporters = set(config.get("exporters", {}).keys())

    for pipeline_name, pcfg in config["service"]["pipelines"].items():
        # Fix exporter references
        new_exporters = []
        for exp_ref in pcfg.get("exporters", []):
            if exp_ref not in defined_exporters:
                exp_type = exp_ref.split("/")[0] if "/" in exp_ref else exp_ref
                matches = [
                    d for d in defined_exporters
                    if d.startswith(exp_type + "/") or d == exp_type
                ]
                if len(matches) == 1:
                    print(f"OTel: Fixed exporter ref in '{pipeline_name}': "
                          f"'{exp_ref}' -> '{matches[0]}'")
                    new_exporters.append(matches[0])
                else:
                    new_exporters.append(exp_ref)
            else:
                new_exporters.append(exp_ref)
        pcfg["exporters"] = new_exporters

        # Fix processor ordering: memory_limiter must be first
        processors = pcfg.get("processors", [])
        if "memory_limiter" in processors and processors[0] != "memory_limiter":
            processors.remove("memory_limiter")
            processors.insert(0, "memory_limiter")
            pcfg["processors"] = processors
            print(f"OTel: Moved memory_limiter to first position in '{pipeline_name}'")

    save_yaml("/app/monitoring/otel-collector.yaml", collector)


def fix_rbac_bindings():
    """Convert ClusterRoleBindings to namespace-scoped RoleBindings."""
    docs = load_yaml_all("/app/rbac/team-bindings.yaml")

    for doc in docs:
        name = doc.get("metadata", {}).get("name", "")
        kind = doc.get("kind", "")

        if "team-" in name and kind == "ClusterRoleBinding":
            # Derive namespace from subjects or name
            target_ns = None
            for subj in doc.get("subjects", []):
                ns = subj.get("namespace")
                if ns and ns.startswith("team-"):
                    target_ns = ns
                    break
            if not target_ns:
                # Derive from name: team-core-admin -> team-core
                parts = name.rsplit("-admin", 1)
                if parts[0].startswith("team-"):
                    target_ns = parts[0]

            if target_ns:
                doc["kind"] = "RoleBinding"
                doc["apiVersion"] = "rbac.authorization.k8s.io/v1"
                doc["metadata"]["namespace"] = target_ns
                print(f"RBAC: Converted '{name}' to RoleBinding (ns={target_ns})")

    save_yaml_all("/app/rbac/team-bindings.yaml", docs)


def fix_crossplane_composition():
    """Fix fromFieldPath entries to match XRD schema field names."""
    xrd = load_yaml("/app/crossplane/xrd-database.yaml")
    composition = load_yaml("/app/crossplane/composition-database.yaml")

    params_props = (
        xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
        ["properties"]["spec"]["properties"]["parameters"]["properties"]
    )
    valid_names = set(params_props.keys())

    def find_closest(invalid_name, valid_set):
        best, best_ratio = None, 0
        for v in valid_set:
            if v.lower() == invalid_name.lower():
                return v
            ratio = SequenceMatcher(None, invalid_name.lower(), v.lower()).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = v
        return best if best_ratio > 0.6 else None

    resources = []
    if "resources" in composition.get("spec", {}):
        resources = composition["spec"]["resources"]
    elif "pipeline" in composition.get("spec", {}):
        for step in composition["spec"]["pipeline"]:
            inp = step.get("input", {})
            resources.extend(inp.get("resources", []))

    for resource in resources:
        for patch in resource.get("patches", []):
            from_field = patch.get("fromFieldPath", "")
            if from_field.startswith("spec.parameters."):
                parts = from_field.split(".")
                param_name = parts[2]
                if param_name not in valid_names:
                    correct = find_closest(param_name, valid_names)
                    if correct:
                        parts[2] = correct
                        patch["fromFieldPath"] = ".".join(parts)
                        print(f"Crossplane: Fixed field path "
                              f"'{from_field}' -> '{patch['fromFieldPath']}'")

    save_yaml("/app/crossplane/composition-database.yaml", composition)


def main():
    print("=" * 60)
    print("Multi-Tier Platform Governance — Solution")
    print("=" * 60)
    print()

    print("── Creating ResourceQuotas ──")
    create_resource_quotas()
    print()

    print("── Creating LimitRanges ──")
    create_limit_ranges()
    print()

    print("── Creating Kyverno Policies ──")
    create_kyverno_require_labels()
    create_kyverno_enforce_limits()
    print()

    print("── Fixing Prometheus Alerting Rules ──")
    fix_prometheus_alert_rules()
    print()

    print("── Fixing OTel Collector ──")
    fix_otel_collector()
    print()

    print("── Fixing RBAC Bindings ──")
    fix_rbac_bindings()
    print()

    print("── Fixing Crossplane Composition ──")
    fix_crossplane_composition()
    print()

    print("=" * 60)
    print("Governance framework implemented successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
