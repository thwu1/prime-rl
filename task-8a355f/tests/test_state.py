"""
Tests for Kubernetes security proposal evaluation and synthesis.
Verifies both the evaluation report and the final synthesized configuration.

"""

import json
import yaml
import os
import glob
import pytest


FINAL_CONFIG_DIR = "/app/final-config"
REPORT_PATH = "/app/evaluation-report.json"
PROPOSALS = {
    "proposal_a": "/app/proposal-a",
    "proposal_b": "/app/proposal-b",
    "proposal_c": "/app/proposal-c",
}
CATEGORIES = [
    "default_deny",
    "cross_namespace_selectors",
    "egress_policies",
    "rbac_scoping",
    "rbac_least_privilege",
    "resource_quotas",
    "limit_ranges",
    "security_contexts",
]
REQUIRED_NAMESPACES = {"prod-frontend", "prod-backend", "prod-data", "monitoring"}


def load_all_manifests(directory):
    """Load all YAML manifests from a directory."""
    manifests = []
    for yaml_file in sorted(glob.glob(os.path.join(directory, "*.yaml"))):
        with open(yaml_file) as f:
            for doc in yaml.safe_load_all(f):
                if doc is not None:
                    manifests.append(doc)
    return manifests


def get_resources(manifests, kind, namespace=None, name=None):
    """Filter manifests by kind, optional namespace, and optional name."""
    results = []
    for m in manifests:
        if m.get("kind") != kind:
            continue
        meta = m.get("metadata", {})
        if namespace is not None and meta.get("namespace") != namespace:
            continue
        if name is not None and meta.get("name") != name:
            continue
        results.append(m)
    return results


def parse_memory(value):
    """Parse Kubernetes memory value to bytes."""
    value = str(value)
    units = {"Ki": 1024, "Mi": 1024 ** 2, "Gi": 1024 ** 3, "Ti": 1024 ** 4}
    for suffix, multiplier in units.items():
        if value.endswith(suffix):
            return float(value[: -len(suffix)]) * multiplier
    return float(value)


def parse_cpu(value):
    """Parse Kubernetes CPU value to millicores."""
    value = str(value)
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


# ===============================================================
# Helper functions to independently assess proposal compliance
# ===============================================================


def check_default_deny(manifests):
    """Check if all namespaces have default-deny-ingress."""
    ns_names = {m["metadata"]["name"] for m in get_resources(manifests, "Namespace")}
    deny_policies = get_resources(manifests, "NetworkPolicy", name="default-deny-ingress")
    deny_ns = set()
    for p in deny_policies:
        spec = p.get("spec", {})
        ps = spec.get("podSelector")
        pt = spec.get("policyTypes", [])
        ingress = spec.get("ingress")
        if (
            ps is not None
            and (ps == {} or ps == {"matchLabels": {}})
            and "Ingress" in pt
            and (ingress is None or ingress == [])
        ):
            deny_ns.add(p["metadata"]["namespace"])
    return ns_names <= deny_ns


def check_cross_namespace_selectors(manifests):
    """Check that all cross-namespace from entries use AND semantics with correct pod labels."""
    all_policies = get_resources(manifests, "NetworkPolicy")
    for policy in all_policies:
        if policy["metadata"].get("name") == "default-deny-ingress":
            continue
        for rule in policy["spec"].get("ingress", []) or []:
            from_entries = rule.get("from", [])
            # Check for OR semantics: multiple from entries where one has
            # namespaceSelector and another has podSelector
            ns_sel_entries = [e for e in from_entries if "namespaceSelector" in e]
            for entry in ns_sel_entries:
                ns_labels = entry.get("namespaceSelector", {}).get("matchLabels", {})
                if not ns_labels:
                    continue
                # Bare namespaceSelector without podSelector
                if "podSelector" not in entry:
                    return False
                # Check monitoring references use prometheus
                if ns_labels.get("name") == "monitoring":
                    pod_labels = entry.get("podSelector", {}).get("matchLabels", {})
                    if pod_labels.get("app") != "prometheus":
                        return False
                # Check prod-frontend references use react-app
                if ns_labels.get("name") == "prod-frontend":
                    pod_labels = entry.get("podSelector", {}).get("matchLabels", {})
                    if pod_labels.get("app") != "react-app":
                        return False
    return True


def check_egress_policies(manifests):
    """Check that egress-restricting policies exist and have correct policyTypes."""
    egress_policies = get_resources(
        manifests, "NetworkPolicy", namespace="prod-data", name="restrict-postgres-egress"
    )
    if len(egress_policies) == 0:
        return False
    for policy in egress_policies:
        pt = policy["spec"].get("policyTypes", [])
        if "Egress" not in pt:
            return False
        if "Ingress" in pt:
            return False
    return True


def check_rbac_scoping(manifests):
    """Check that no application service accounts have ClusterRoleBindings."""
    crbs = get_resources(manifests, "ClusterRoleBinding")
    for crb in crbs:
        for subject in crb.get("subjects", []):
            if (
                subject.get("name") == "deploy-bot"
                and subject.get("kind") == "ServiceAccount"
            ):
                return False
    # Verify deploy-bot has a namespaced RoleBinding
    rbs = get_resources(manifests, "RoleBinding", namespace="prod-backend")
    found = False
    for rb in rbs:
        for subject in rb.get("subjects", []):
            if subject.get("name") == "deploy-bot" and subject.get("kind") == "ServiceAccount":
                found = True
    return found


def check_rbac_least_privilege(manifests):
    """Check that no Role/ClusterRole uses wildcard verbs on secrets."""
    roles = get_resources(manifests, "Role") + get_resources(manifests, "ClusterRole")
    for role in roles:
        for rule in role.get("rules", []):
            if "secrets" in rule.get("resources", []):
                if "*" in rule.get("verbs", []):
                    return False
    return True


def check_resource_quotas(manifests):
    """Check that all namespaces have correct ResourceQuota values."""
    expected = {
        "prod-frontend": {"cpu": "4", "memory": "4Gi", "pods": "20"},
        "prod-backend": {"cpu": "8", "memory": "8Gi", "pods": "30"},
        "prod-data": {"cpu": "16", "memory": "32Gi", "pods": "10"},
        "monitoring": {"cpu": "4", "memory": "8Gi", "pods": "15"},
    }
    quotas = get_resources(manifests, "ResourceQuota")
    quota_ns = {}
    for q in quotas:
        ns = q["metadata"]["namespace"]
        quota_ns[ns] = q["spec"]["hard"]
    for ns, exp in expected.items():
        if ns not in quota_ns:
            return False
        hard = quota_ns[ns]
        if str(hard.get("cpu")) != exp["cpu"]:
            return False
        if hard.get("memory") != exp["memory"]:
            return False
        if str(hard.get("pods")) != exp["pods"]:
            return False
    return True


def check_limit_ranges(manifests):
    """Check that all LimitRanges have default <= max."""
    lrs = get_resources(manifests, "LimitRange")
    if len(lrs) < 4:
        return False
    for lr in lrs:
        for limit in lr["spec"]["limits"]:
            if limit.get("type") != "Container":
                continue
            default = limit.get("default", {})
            max_vals = limit.get("max", {})
            if "memory" in default and "memory" in max_vals:
                if parse_memory(default["memory"]) > parse_memory(max_vals["memory"]):
                    return False
            if "cpu" in default and "cpu" in max_vals:
                if parse_cpu(default["cpu"]) > parse_cpu(max_vals["cpu"]):
                    return False
    return True


def check_security_contexts(manifests):
    """Check that no containers are privileged and nginx has NET_BIND_SERVICE."""
    deployments = get_resources(manifests, "Deployment")
    nginx_ok = False
    for deploy in deployments:
        containers = deploy["spec"]["template"]["spec"]["containers"]
        for container in containers:
            sc = container.get("securityContext", {})
            if sc.get("privileged") is True:
                return False
            if container["name"] == "nginx":
                caps = sc.get("capabilities", {})
                if "NET_BIND_SERVICE" in caps.get("add", []):
                    nginx_ok = True
    return nginx_ok


CHECKERS = {
    "default_deny": check_default_deny,
    "cross_namespace_selectors": check_cross_namespace_selectors,
    "egress_policies": check_egress_policies,
    "rbac_scoping": check_rbac_scoping,
    "rbac_least_privilege": check_rbac_least_privilege,
    "resource_quotas": check_resource_quotas,
    "limit_ranges": check_limit_ranges,
    "security_contexts": check_security_contexts,
}


# ===============================================================
# Fixtures
# ===============================================================


@pytest.fixture(scope="module")
def report():
    with open(REPORT_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def final_manifests():
    return load_all_manifests(FINAL_CONFIG_DIR)


# ===============================================================
# Evaluation Report Tests
# ===============================================================


class TestEvaluationReportStructure:
    """Verify the evaluation report exists and has the correct structure."""

    def test_report_exists(self):
        assert os.path.exists(REPORT_PATH), "evaluation-report.json not found at /app/"

    def test_report_has_all_proposals(self, report):
        for proposal in ["proposal_a", "proposal_b", "proposal_c"]:
            assert proposal in report, f"Report missing {proposal}"

    def test_report_has_all_categories(self, report):
        for proposal in ["proposal_a", "proposal_b", "proposal_c"]:
            for cat in CATEGORIES:
                assert cat in report[proposal], (
                    f"Report missing category '{cat}' for {proposal}"
                )
                assert report[proposal][cat] in ("pass", "fail"), (
                    f"{proposal}.{cat} must be 'pass' or 'fail', "
                    f"got '{report[proposal][cat]}'"
                )


class TestEvaluationAccuracy:
    """Verify the evaluation report correctly assesses each proposal.

    Each test independently analyzes the proposal manifests and compares
    the result against what the solver reported.
    """

    @pytest.mark.parametrize("proposal_name", ["proposal_a", "proposal_b", "proposal_c"])
    @pytest.mark.parametrize("category", CATEGORIES)
    def test_assessment_matches_reality(self, report, proposal_name, category):
        manifests = load_all_manifests(PROPOSALS[proposal_name])
        actual_passes = CHECKERS[category](manifests)
        reported = report[proposal_name][category]
        expected = "pass" if actual_passes else "fail"
        assert reported == expected, (
            f"{proposal_name}.{category}: reported '{reported}' but "
            f"independent analysis shows '{expected}'"
        )


# ===============================================================
# Final Configuration Tests — Network Policies
# ===============================================================


class TestFinalDefaultDenyPolicies:
    """Verify every namespace has a default-deny-ingress NetworkPolicy."""

    def test_all_namespaces_have_default_deny_ingress(self, final_manifests):
        namespaces = get_resources(final_manifests, "Namespace")
        ns_names = {m["metadata"]["name"] for m in namespaces}
        assert ns_names >= REQUIRED_NAMESPACES, (
            f"Missing namespaces: {REQUIRED_NAMESPACES - ns_names}"
        )

        deny_policies = get_resources(
            final_manifests, "NetworkPolicy", name="default-deny-ingress"
        )
        deny_ns = {p["metadata"]["namespace"] for p in deny_policies}

        for ns in REQUIRED_NAMESPACES:
            assert ns in deny_ns, (
                f"Namespace '{ns}' is missing a default-deny-ingress NetworkPolicy"
            )

    def test_default_deny_structure(self, final_manifests):
        deny_policies = get_resources(
            final_manifests, "NetworkPolicy", name="default-deny-ingress"
        )

        for policy in deny_policies:
            ns = policy["metadata"]["namespace"]
            spec = policy["spec"]
            ps = spec.get("podSelector", None)
            assert ps is not None, f"default-deny in {ns} missing podSelector"
            assert ps == {} or ps == {
                "matchLabels": {}
            }, f"default-deny in {ns} must have empty podSelector"

            pt = spec.get("policyTypes", [])
            assert "Ingress" in pt, (
                f"default-deny in {ns} must include 'Ingress' in policyTypes"
            )

            ingress = spec.get("ingress")
            assert ingress is None or ingress == [], (
                f"default-deny in {ns} must not have ingress rules"
            )


class TestFinalCrossNamespaceSelectors:
    """Verify cross-namespace rules use AND semantics."""

    def test_api_server_prod_frontend_uses_and_selector(self, final_manifests):
        policies = get_resources(
            final_manifests,
            "NetworkPolicy",
            namespace="prod-backend",
            name="allow-api-server-ingress",
        )
        assert len(policies) == 1, "Expected exactly one allow-api-server-ingress policy"
        policy = policies[0]

        found_prod_frontend_rule = False
        for rule in policy["spec"]["ingress"]:
            for from_entry in rule.get("from", []):
                ns_sel = from_entry.get("namespaceSelector")
                if (
                    ns_sel
                    and ns_sel.get("matchLabels", {}).get("name") == "prod-frontend"
                ):
                    found_prod_frontend_rule = True
                    assert "podSelector" in from_entry, (
                        "prod-frontend access to api-server must use AND semantics"
                    )
                    pod_labels = from_entry["podSelector"].get("matchLabels", {})
                    assert pod_labels.get("app") == "react-app", (
                        "Only react-app pods from prod-frontend should access api-server"
                    )

        assert found_prod_frontend_rule, (
            "No ingress rule found allowing prod-frontend -> api-server"
        )

    def test_monitoring_access_restricted_to_prometheus_pods(self, final_manifests):
        all_policies = get_resources(final_manifests, "NetworkPolicy")

        for policy in all_policies:
            pname = policy["metadata"].get("name", "")
            if pname == "default-deny-ingress":
                continue

            for rule in policy["spec"].get("ingress", []) or []:
                for from_entry in rule.get("from", []):
                    ns_sel = from_entry.get("namespaceSelector")
                    if (
                        ns_sel
                        and ns_sel.get("matchLabels", {}).get("name") == "monitoring"
                    ):
                        assert "podSelector" in from_entry, (
                            f"Policy '{pname}': access from monitoring namespace "
                            f"must specify podSelector (AND semantics)"
                        )
                        pod_labels = from_entry["podSelector"].get("matchLabels", {})
                        assert pod_labels.get("app") == "prometheus", (
                            f"Policy '{pname}': only prometheus pods should have "
                            f"cross-namespace access from monitoring"
                        )

    def test_no_bare_namespace_selectors_in_prod_backend(self, final_manifests):
        policies = get_resources(
            final_manifests, "NetworkPolicy", namespace="prod-backend"
        )

        for policy in policies:
            if policy["metadata"]["name"] == "default-deny-ingress":
                continue
            for rule in policy["spec"].get("ingress", []) or []:
                for from_entry in rule.get("from", []):
                    if "namespaceSelector" in from_entry:
                        ns_labels = from_entry["namespaceSelector"].get(
                            "matchLabels", {}
                        )
                        if ns_labels:
                            assert "podSelector" in from_entry, (
                                f"Policy '{policy['metadata']['name']}': "
                                f"bare namespaceSelector for {ns_labels} is too permissive"
                            )


class TestFinalEgressPolicies:
    """Verify egress policies have correct policyTypes."""

    def test_postgres_egress_policy_exists(self, final_manifests):
        policies = get_resources(
            final_manifests,
            "NetworkPolicy",
            namespace="prod-data",
            name="restrict-postgres-egress",
        )
        assert len(policies) == 1, (
            "Expected exactly one restrict-postgres-egress policy in final config"
        )

    def test_postgres_egress_policy_has_egress_type(self, final_manifests):
        policies = get_resources(
            final_manifests,
            "NetworkPolicy",
            namespace="prod-data",
            name="restrict-postgres-egress",
        )
        policy = policies[0]
        pt = policy["spec"].get("policyTypes", [])
        assert "Egress" in pt, (
            "restrict-postgres-egress must include 'Egress' in policyTypes"
        )

    def test_postgres_egress_not_ingress_type(self, final_manifests):
        policies = get_resources(
            final_manifests,
            "NetworkPolicy",
            namespace="prod-data",
            name="restrict-postgres-egress",
        )
        policy = policies[0]
        pt = policy["spec"].get("policyTypes", [])
        assert "Ingress" not in pt, (
            "restrict-postgres-egress should not include 'Ingress' in policyTypes"
        )


# ===============================================================
# Final Configuration Tests — RBAC
# ===============================================================


class TestFinalRBAC:
    """Verify RBAC scoping and least-privilege compliance."""

    def test_no_cluster_role_binding_for_deploy_bot(self, final_manifests):
        crbs = get_resources(final_manifests, "ClusterRoleBinding")
        for crb in crbs:
            for subject in crb.get("subjects", []):
                assert not (
                    subject.get("name") == "deploy-bot"
                    and subject.get("kind") == "ServiceAccount"
                ), (
                    f"ClusterRoleBinding '{crb['metadata']['name']}' grants "
                    f"cluster-wide access to deploy-bot"
                )

    def test_deploy_bot_has_namespaced_role_binding(self, final_manifests):
        rbs = get_resources(final_manifests, "RoleBinding", namespace="prod-backend")
        found = False
        for rb in rbs:
            for subject in rb.get("subjects", []):
                if (
                    subject.get("name") == "deploy-bot"
                    and subject.get("kind") == "ServiceAccount"
                ):
                    found = True
                    role_ref = rb.get("roleRef", {})
                    assert role_ref.get("name") == "edit", (
                        "deploy-bot RoleBinding should reference the 'edit' ClusterRole"
                    )
        assert found, "deploy-bot must have a RoleBinding in prod-backend namespace"

    def test_no_wildcard_verbs_on_secrets(self, final_manifests):
        roles = get_resources(final_manifests, "Role") + get_resources(
            final_manifests, "ClusterRole"
        )
        for role in roles:
            for rule in role.get("rules", []):
                resources = rule.get("resources", [])
                verbs = rule.get("verbs", [])
                if "secrets" in resources:
                    assert "*" not in verbs, (
                        f"Role '{role['metadata']['name']}' uses wildcard verbs on secrets"
                    )

    def test_data_reader_has_only_get_list(self, final_manifests):
        roles = get_resources(
            final_manifests, "Role", namespace="prod-data", name="data-reader-secrets"
        )
        assert len(roles) == 1, "Expected data-reader-secrets Role in prod-data"
        role = roles[0]
        for rule in role.get("rules", []):
            if "secrets" in rule.get("resources", []):
                verbs = set(rule.get("verbs", []))
                allowed = {"get", "list"}
                assert verbs <= allowed, (
                    f"data-reader-secrets grants verbs {verbs} on secrets, "
                    f"expected only {allowed}"
                )


# ===============================================================
# Final Configuration Tests — Resource Management
# ===============================================================


class TestFinalResourceQuotas:
    """Verify all namespaces have ResourceQuotas with correct values."""

    def test_all_namespaces_have_resource_quotas(self, final_manifests):
        quotas = get_resources(final_manifests, "ResourceQuota")
        quota_ns = {q["metadata"]["namespace"] for q in quotas}
        for ns in REQUIRED_NAMESPACES:
            assert ns in quota_ns, f"Namespace '{ns}' is missing a ResourceQuota"

    def test_monitoring_quota_values(self, final_manifests):
        quotas = get_resources(final_manifests, "ResourceQuota", namespace="monitoring")
        assert len(quotas) >= 1, "monitoring namespace must have a ResourceQuota"
        quota = quotas[0]
        hard = quota["spec"]["hard"]
        assert str(hard.get("cpu")) == "4", (
            f"monitoring quota cpu should be '4', got '{hard.get('cpu')}'"
        )
        assert hard.get("memory") == "8Gi", (
            f"monitoring quota memory should be '8Gi', got '{hard.get('memory')}'"
        )
        assert str(hard.get("pods")) == "15", (
            f"monitoring quota pods should be '15', got '{hard.get('pods')}'"
        )


class TestFinalLimitRanges:
    """Verify LimitRange defaults are within bounds."""

    def test_limit_range_defaults_within_bounds(self, final_manifests):
        lrs = get_resources(final_manifests, "LimitRange")
        for lr in lrs:
            ns = lr["metadata"]["namespace"]
            for limit in lr["spec"]["limits"]:
                if limit.get("type") != "Container":
                    continue
                default = limit.get("default", {})
                max_vals = limit.get("max", {})
                if "memory" in default and "memory" in max_vals:
                    def_mem = parse_memory(default["memory"])
                    max_mem = parse_memory(max_vals["memory"])
                    assert def_mem <= max_mem, (
                        f"LimitRange in {ns}: default memory ({default['memory']}) "
                        f"exceeds max ({max_vals['memory']})"
                    )
                if "cpu" in default and "cpu" in max_vals:
                    def_cpu = parse_cpu(default["cpu"])
                    max_cpu = parse_cpu(max_vals["cpu"])
                    assert def_cpu <= max_cpu, (
                        f"LimitRange in {ns}: default CPU ({default['cpu']}) "
                        f"exceeds max ({max_vals['cpu']})"
                    )

    def test_prod_frontend_limitrange_correct_values(self, final_manifests):
        lrs = get_resources(final_manifests, "LimitRange", namespace="prod-frontend")
        assert len(lrs) >= 1, "prod-frontend must have a LimitRange"
        lr = lrs[0]
        for limit in lr["spec"]["limits"]:
            if limit.get("type") != "Container":
                continue
            assert limit["default"]["memory"] == "512Mi", (
                f"prod-frontend default memory should be '512Mi', "
                f"got '{limit['default']['memory']}'"
            )
            assert limit["max"]["memory"] == "1Gi", (
                f"prod-frontend max memory should be '1Gi', "
                f"got '{limit['max']['memory']}'"
            )

    def test_prod_backend_limitrange_correct_values(self, final_manifests):
        lrs = get_resources(final_manifests, "LimitRange", namespace="prod-backend")
        assert len(lrs) >= 1, "prod-backend must have a LimitRange"
        lr = lrs[0]
        for limit in lr["spec"]["limits"]:
            if limit.get("type") != "Container":
                continue
            assert limit["default"]["memory"] == "1Gi", (
                f"prod-backend default memory should be '1Gi', "
                f"got '{limit['default']['memory']}'"
            )
            assert limit["max"]["memory"] == "2Gi", (
                f"prod-backend max memory should be '2Gi', "
                f"got '{limit['max']['memory']}'"
            )


# ===============================================================
# Final Configuration Tests — Security Contexts
# ===============================================================


class TestFinalSecurityContexts:
    """Verify container security context compliance."""

    def test_no_privileged_containers(self, final_manifests):
        deployments = get_resources(final_manifests, "Deployment")
        for deploy in deployments:
            ns = deploy["metadata"]["namespace"]
            name = deploy["metadata"]["name"]
            containers = deploy["spec"]["template"]["spec"]["containers"]
            for container in containers:
                sc = container.get("securityContext", {})
                assert sc.get("privileged") is not True, (
                    f"Deployment {ns}/{name} container '{container['name']}' "
                    f"runs in privileged mode"
                )

    def test_nginx_has_net_bind_service(self, final_manifests):
        deploys = get_resources(
            final_manifests, "Deployment", namespace="prod-frontend", name="nginx"
        )
        assert len(deploys) == 1, "Expected nginx Deployment in prod-frontend"
        container = deploys[0]["spec"]["template"]["spec"]["containers"][0]
        sc = container.get("securityContext", {})
        caps = sc.get("capabilities", {})
        add = caps.get("add", [])
        assert "NET_BIND_SERVICE" in add, (
            "nginx must have NET_BIND_SERVICE capability"
        )
