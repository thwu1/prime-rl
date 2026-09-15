
import os
import pytest
import yaml


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_yaml_all(path):
    with open(path) as f:
        return [doc for doc in yaml.safe_load_all(f) if doc is not None]


def parse_k8s_quantity(value):
    """Parse a Kubernetes resource quantity to a comparable numeric value.
    CPU: returned in millicores. Memory: returned in bytes.
    """
    value = str(value).strip()
    if value.endswith("Gi"):
        return float(value[:-2]) * 1024 * 1024 * 1024
    elif value.endswith("Mi"):
        return float(value[:-2]) * 1024 * 1024
    elif value.endswith("Ki"):
        return float(value[:-2]) * 1024
    elif value.endswith("Ti"):
        return float(value[:-2]) * 1024 ** 4
    elif value.endswith("m"):
        return float(value[:-1])
    else:
        return float(value) * 1000  # plain number → millicores for CPU


def parse_cpu(value):
    """Parse CPU quantity to millicores."""
    value = str(value).strip()
    if value.endswith("m"):
        return float(value[:-1])
    return float(value) * 1000


def parse_memory(value):
    """Parse memory quantity to bytes."""
    value = str(value).strip()
    if value.endswith("Gi"):
        return float(value[:-2]) * 1024 ** 3
    elif value.endswith("Mi"):
        return float(value[:-2]) * 1024 ** 2
    elif value.endswith("Ki"):
        return float(value[:-2]) * 1024
    elif value.endswith("Ti"):
        return float(value[:-2]) * 1024 ** 4
    return float(value)


TENANTS = ["team-core", "team-analytics", "team-edge"]

TIER_CONFIG = {
    "team-core": {
        "tier": "platinum",
        "min_req_cpu": 16000,      # 16 cores in millicores
        "min_req_mem": 64 * 1024 ** 3,  # 64Gi
        "max_lim_cpu": 24000,
        "max_lim_mem": 96 * 1024 ** 3,
        "max_pods": 100,
        "lr_max_cpu": 4000,        # 4 cores
        "lr_max_mem": 8 * 1024 ** 3,
    },
    "team-analytics": {
        "tier": "gold",
        "min_req_cpu": 12000,
        "min_req_mem": 48 * 1024 ** 3,
        "max_lim_cpu": 18000,
        "max_lim_mem": 72 * 1024 ** 3,
        "max_pods": 60,
        "lr_max_cpu": 2000,
        "lr_max_mem": 4 * 1024 ** 3,
    },
    "team-edge": {
        "tier": "silver",
        "min_req_cpu": 8000,
        "min_req_mem": 32 * 1024 ** 3,
        "max_lim_cpu": 12000,
        "max_lim_mem": 48 * 1024 ** 3,
        "max_pods": 30,
        "lr_max_cpu": 1000,
        "lr_max_mem": 2 * 1024 ** 3,
    },
}

CLUSTER_AVAIL_CPU = 40000       # 40 cores in millicores
CLUSTER_AVAIL_MEM = 160 * 1024 ** 3  # 160Gi
MAX_OVERCOMMIT = 1.5


# ── YAML validity ───────────────────────────────────────────────────────

class TestYAMLValidity:
    STATIC_FILES = [
        "/app/crossplane/xrd-database.yaml",
        "/app/crossplane/composition-database.yaml",
        "/app/monitoring/alerting-rules.yaml",
        "/app/monitoring/otel-collector.yaml",
        "/app/rbac/platform-roles.yaml",
        "/app/rbac/team-bindings.yaml",
    ]

    @pytest.mark.parametrize("path", STATIC_FILES)
    def test_static_yaml_valid(self, path):
        assert os.path.exists(path), f"File missing: {path}"
        load_yaml_all(path)

    @pytest.mark.parametrize("team", TENANTS)
    def test_quota_yaml_valid(self, team):
        path = f"/app/tenants/{team}/resourcequota.yaml"
        assert os.path.exists(path), f"ResourceQuota missing for {team}"
        load_yaml(path)

    @pytest.mark.parametrize("team", TENANTS)
    def test_limitrange_yaml_valid(self, team):
        path = f"/app/tenants/{team}/limitrange.yaml"
        assert os.path.exists(path), f"LimitRange missing for {team}"
        load_yaml(path)

    def test_require_labels_policy_yaml_valid(self):
        path = "/app/policies/require-labels.yaml"
        assert os.path.exists(path), "require-labels.yaml policy missing"
        load_yaml(path)

    def test_enforce_limits_policy_yaml_valid(self):
        path = "/app/policies/enforce-resource-limits.yaml"
        assert os.path.exists(path), "enforce-resource-limits.yaml policy missing"
        load_yaml(path)


# ── ResourceQuota ────────────────────────────────────────────────────────

def _load_quota(team):
    return load_yaml(f"/app/tenants/{team}/resourcequota.yaml")


def _quota_hard(team):
    q = _load_quota(team)
    return q["spec"]["hard"]


class TestResourceQuotaStructure:
    REQUIRED_KEYS = ["requests.cpu", "requests.memory", "limits.cpu", "limits.memory", "pods"]

    @pytest.mark.parametrize("team", TENANTS)
    def test_quota_has_required_fields(self, team):
        hard = _quota_hard(team)
        for key in self.REQUIRED_KEYS:
            assert key in hard, f"{team} quota missing '{key}'"

    @pytest.mark.parametrize("team", TENANTS)
    def test_quota_is_resource_quota_kind(self, team):
        q = _load_quota(team)
        assert q["kind"] == "ResourceQuota"

    @pytest.mark.parametrize("team", TENANTS)
    def test_quota_has_correct_namespace(self, team):
        q = _load_quota(team)
        ns = q.get("metadata", {}).get("namespace", "")
        assert ns == team, f"{team} quota namespace is '{ns}', expected '{team}'"


class TestResourceQuotaTierMinimums:
    @pytest.mark.parametrize("team", TENANTS)
    def test_requests_cpu_meets_minimum(self, team):
        hard = _quota_hard(team)
        actual = parse_cpu(hard["requests.cpu"])
        minimum = TIER_CONFIG[team]["min_req_cpu"]
        assert actual >= minimum, (
            f"{team}: requests.cpu={hard['requests.cpu']} "
            f"({actual}m) < tier min ({minimum}m)"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_requests_memory_meets_minimum(self, team):
        hard = _quota_hard(team)
        actual = parse_memory(hard["requests.memory"])
        minimum = TIER_CONFIG[team]["min_req_mem"]
        assert actual >= minimum, (
            f"{team}: requests.memory={hard['requests.memory']} < tier min"
        )


class TestResourceQuotaTierMaximums:
    @pytest.mark.parametrize("team", TENANTS)
    def test_limits_cpu_within_maximum(self, team):
        hard = _quota_hard(team)
        actual = parse_cpu(hard["limits.cpu"])
        maximum = TIER_CONFIG[team]["max_lim_cpu"]
        assert actual <= maximum, (
            f"{team}: limits.cpu={hard['limits.cpu']} ({actual}m) > tier max ({maximum}m)"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_limits_memory_within_maximum(self, team):
        hard = _quota_hard(team)
        actual = parse_memory(hard["limits.memory"])
        maximum = TIER_CONFIG[team]["max_lim_mem"]
        assert actual <= maximum, (
            f"{team}: limits.memory={hard['limits.memory']} > tier max"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_pods_within_maximum(self, team):
        hard = _quota_hard(team)
        actual = int(str(hard["pods"]))
        maximum = TIER_CONFIG[team]["max_pods"]
        assert actual <= maximum, (
            f"{team}: pods={actual} > tier max ({maximum})"
        )


class TestResourceQuotaClusterCapacity:
    def _sum_across_tenants(self, field, parser):
        total = 0
        for team in TENANTS:
            hard = _quota_hard(team)
            total += parser(hard[field])
        return total

    def test_total_requests_cpu_within_capacity(self):
        total = self._sum_across_tenants("requests.cpu", parse_cpu)
        assert total <= CLUSTER_AVAIL_CPU, (
            f"Sum of requests.cpu ({total}m) exceeds cluster capacity ({CLUSTER_AVAIL_CPU}m)"
        )

    def test_total_requests_memory_within_capacity(self):
        total = self._sum_across_tenants("requests.memory", parse_memory)
        assert total <= CLUSTER_AVAIL_MEM, (
            f"Sum of requests.memory exceeds cluster capacity (160Gi)"
        )

    def test_total_limits_cpu_within_overcommit(self):
        total = self._sum_across_tenants("limits.cpu", parse_cpu)
        max_limit = CLUSTER_AVAIL_CPU * MAX_OVERCOMMIT
        assert total <= max_limit, (
            f"Sum of limits.cpu ({total}m) exceeds overcommit cap ({max_limit}m)"
        )

    def test_total_limits_memory_within_overcommit(self):
        total = self._sum_across_tenants("limits.memory", parse_memory)
        max_limit = CLUSTER_AVAIL_MEM * MAX_OVERCOMMIT
        assert total <= max_limit, (
            f"Sum of limits.memory exceeds overcommit cap (240Gi)"
        )


class TestResourceQuotaBurstRatio:
    @pytest.mark.parametrize("team", TENANTS)
    def test_cpu_burst_ratio(self, team):
        hard = _quota_hard(team)
        req = parse_cpu(hard["requests.cpu"])
        lim = parse_cpu(hard["limits.cpu"])
        ratio = lim / req
        assert ratio <= MAX_OVERCOMMIT, (
            f"{team}: CPU burst ratio {ratio:.2f} exceeds {MAX_OVERCOMMIT}"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_memory_burst_ratio(self, team):
        hard = _quota_hard(team)
        req = parse_memory(hard["requests.memory"])
        lim = parse_memory(hard["limits.memory"])
        ratio = lim / req
        assert ratio <= MAX_OVERCOMMIT, (
            f"{team}: Memory burst ratio {ratio:.2f} exceeds {MAX_OVERCOMMIT}"
        )


class TestResourceQuotaTierOrdering:
    def test_requests_cpu_ordering(self):
        vals = {t: parse_cpu(_quota_hard(t)["requests.cpu"]) for t in TENANTS}
        assert vals["team-core"] > vals["team-analytics"] > vals["team-edge"], (
            f"Tier ordering violated for requests.cpu: {vals}"
        )

    def test_requests_memory_ordering(self):
        vals = {t: parse_memory(_quota_hard(t)["requests.memory"]) for t in TENANTS}
        assert vals["team-core"] > vals["team-analytics"] > vals["team-edge"], (
            f"Tier ordering violated for requests.memory: {vals}"
        )


# ── LimitRange ───────────────────────────────────────────────────────────

def _load_limitrange(team):
    return load_yaml(f"/app/tenants/{team}/limitrange.yaml")


def _get_container_limit(team):
    lr = _load_limitrange(team)
    for entry in lr["spec"]["limits"]:
        if entry.get("type") == "Container":
            return entry
    pytest.fail(f"{team} LimitRange has no 'Container' type limit entry")


class TestLimitRangeConsistency:
    @pytest.mark.parametrize("team", TENANTS)
    def test_cpu_ordering(self, team):
        entry = _get_container_limit(team)
        max_v = parse_cpu(entry["max"]["cpu"])
        default_v = parse_cpu(entry["default"]["cpu"])
        default_req_v = parse_cpu(entry["defaultRequest"]["cpu"])
        min_v = parse_cpu(entry["min"]["cpu"])
        assert max_v >= default_v >= default_req_v >= min_v, (
            f"{team} LimitRange CPU consistency violated: "
            f"max={entry['max']['cpu']}, default={entry['default']['cpu']}, "
            f"defaultRequest={entry['defaultRequest']['cpu']}, min={entry['min']['cpu']}"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_memory_ordering(self, team):
        entry = _get_container_limit(team)
        max_v = parse_memory(entry["max"]["memory"])
        default_v = parse_memory(entry["default"]["memory"])
        default_req_v = parse_memory(entry["defaultRequest"]["memory"])
        min_v = parse_memory(entry["min"]["memory"])
        assert max_v >= default_v >= default_req_v >= min_v, (
            f"{team} LimitRange memory consistency violated: "
            f"max={entry['max']['memory']}, default={entry['default']['memory']}, "
            f"defaultRequest={entry['defaultRequest']['memory']}, min={entry['min']['memory']}"
        )


class TestLimitRangeTierBounds:
    @pytest.mark.parametrize("team", TENANTS)
    def test_max_cpu_within_tier(self, team):
        entry = _get_container_limit(team)
        actual = parse_cpu(entry["max"]["cpu"])
        maximum = TIER_CONFIG[team]["lr_max_cpu"]
        assert actual <= maximum, (
            f"{team}: LimitRange max.cpu={entry['max']['cpu']} ({actual}m) "
            f"exceeds tier bound ({maximum}m)"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_max_memory_within_tier(self, team):
        entry = _get_container_limit(team)
        actual = parse_memory(entry["max"]["memory"])
        maximum = TIER_CONFIG[team]["lr_max_mem"]
        assert actual <= maximum, (
            f"{team}: LimitRange max.memory={entry['max']['memory']} exceeds tier bound"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_min_cpu_at_least_50m(self, team):
        entry = _get_container_limit(team)
        actual = parse_cpu(entry["min"]["cpu"])
        assert actual >= 50, (
            f"{team}: LimitRange min.cpu={entry['min']['cpu']} ({actual}m) < 50m"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_min_memory_at_least_64mi(self, team):
        entry = _get_container_limit(team)
        actual = parse_memory(entry["min"]["memory"])
        assert actual >= 64 * 1024 * 1024, (
            f"{team}: LimitRange min.memory={entry['min']['memory']} < 64Mi"
        )


class TestLimitRangeDefaults:
    @pytest.mark.parametrize("team", TENANTS)
    def test_has_default_cpu(self, team):
        entry = _get_container_limit(team)
        assert "default" in entry and "cpu" in entry["default"], (
            f"{team}: LimitRange missing default.cpu"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_has_default_memory(self, team):
        entry = _get_container_limit(team)
        assert "default" in entry and "memory" in entry["default"], (
            f"{team}: LimitRange missing default.memory"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_has_default_request_cpu(self, team):
        entry = _get_container_limit(team)
        assert "defaultRequest" in entry and "cpu" in entry["defaultRequest"], (
            f"{team}: LimitRange missing defaultRequest.cpu"
        )

    @pytest.mark.parametrize("team", TENANTS)
    def test_has_default_request_memory(self, team):
        entry = _get_container_limit(team)
        assert "defaultRequest" in entry and "memory" in entry["defaultRequest"], (
            f"{team}: LimitRange missing defaultRequest.memory"
        )


# ── Kyverno Policies ────────────────────────────────────────────────────

class TestKyvernoRequireLabels:
    def _load_policy(self):
        return load_yaml("/app/policies/require-labels.yaml")

    def test_kind_is_cluster_policy(self):
        p = self._load_policy()
        assert p["kind"] == "ClusterPolicy", (
            f"require-labels kind is '{p['kind']}', expected ClusterPolicy"
        )

    def test_name_is_require_labels(self):
        p = self._load_policy()
        assert p["metadata"]["name"] == "require-labels"

    def test_validation_failure_action_is_enforce(self):
        p = self._load_policy()
        action = p["spec"].get("validationFailureAction", "")
        assert action == "Enforce", (
            f"require-labels validationFailureAction='{action}', must be 'Enforce'"
        )

    def test_matches_deployments_in_apps_v1(self):
        p = self._load_policy()
        found = self._find_kind_match(p, "Deployment", "apps/v1")
        assert found, "require-labels must match Deployment in apps/v1"

    def test_matches_statefulsets_in_apps_v1(self):
        p = self._load_policy()
        found = self._find_kind_match(p, "StatefulSet", "apps/v1")
        assert found, "require-labels must match StatefulSet in apps/v1"

    def test_checks_for_required_labels(self):
        p = self._load_policy()
        content = yaml.dump(p)
        assert "app.kubernetes.io/name" in content, (
            "require-labels policy must check for app.kubernetes.io/name label"
        )
        assert "app.kubernetes.io/managed-by" in content, (
            "require-labels policy must check for app.kubernetes.io/managed-by label"
        )

    @staticmethod
    def _find_kind_match(policy, kind, api_version):
        for rule in policy["spec"].get("rules", []):
            match = rule.get("match", {})
            entries = match.get("any", []) + match.get("all", [])
            if not entries and "resources" in match:
                entries = [match]
            for entry in entries:
                res = entry.get("resources", {})
                kinds = res.get("kinds", [])
                api_versions = res.get("apiVersions", [])
                if kind in kinds and api_version in api_versions:
                    return True
        return False


class TestKyvernoEnforceLimits:
    def _load_policy(self):
        return load_yaml("/app/policies/enforce-resource-limits.yaml")

    def test_kind_is_cluster_policy(self):
        p = self._load_policy()
        assert p["kind"] == "ClusterPolicy"

    def test_name_is_enforce_resource_limits(self):
        p = self._load_policy()
        assert p["metadata"]["name"] == "enforce-resource-limits"

    def test_validation_failure_action_is_enforce(self):
        p = self._load_policy()
        action = p["spec"].get("validationFailureAction", "")
        assert action == "Enforce", (
            f"enforce-resource-limits validationFailureAction='{action}', must be 'Enforce'"
        )

    def test_matches_deployments_in_apps_v1(self):
        p = self._load_policy()
        found = False
        for rule in p["spec"].get("rules", []):
            match = rule.get("match", {})
            entries = match.get("any", []) + match.get("all", [])
            if not entries and "resources" in match:
                entries = [match]
            for entry in entries:
                res = entry.get("resources", {})
                kinds = res.get("kinds", [])
                api_versions = res.get("apiVersions", [])
                if "Deployment" in kinds and "apps/v1" in api_versions:
                    found = True
        assert found, "enforce-resource-limits must match Deployment in apps/v1"

    def test_does_not_match_v1_for_deployments(self):
        p = self._load_policy()
        for rule in p["spec"].get("rules", []):
            match = rule.get("match", {})
            entries = match.get("any", []) + match.get("all", [])
            if not entries and "resources" in match:
                entries = [match]
            for entry in entries:
                res = entry.get("resources", {})
                kinds = res.get("kinds", [])
                api_versions = res.get("apiVersions", [])
                if "Deployment" in kinds:
                    assert "v1" not in api_versions or "apps/v1" in api_versions, (
                        "Deployments are in apps/v1, not core v1"
                    )

    def test_validates_resource_limits(self):
        p = self._load_policy()
        content = yaml.dump(p).lower()
        assert "limits" in content, (
            "enforce-resource-limits must validate for resource limits"
        )


# ── RBAC ─────────────────────────────────────────────────────────────────

class TestRBACBindings:
    def _load_bindings(self):
        return load_yaml_all("/app/rbac/team-bindings.yaml")

    def test_all_tenant_bindings_are_role_bindings(self):
        docs = self._load_bindings()
        tenant_bindings = [d for d in docs if "team-" in d.get("metadata", {}).get("name", "")]
        assert len(tenant_bindings) >= 3, (
            f"Expected at least 3 tenant bindings, found {len(tenant_bindings)}"
        )
        for doc in tenant_bindings:
            name = doc["metadata"]["name"]
            kind = doc["kind"]
            assert kind == "RoleBinding", (
                f"Tenant binding '{name}' is {kind}, must be RoleBinding. "
                f"ClusterRoleBindings violate tenant isolation."
            )

    def test_bindings_have_correct_namespaces(self):
        docs = self._load_bindings()
        expected = {
            "team-core-admin": "team-core",
            "team-analytics-admin": "team-analytics",
            "team-edge-admin": "team-edge",
        }
        for doc in docs:
            name = doc.get("metadata", {}).get("name", "")
            if name in expected:
                ns = doc.get("metadata", {}).get("namespace", "")
                assert ns == expected[name], (
                    f"Binding '{name}' namespace='{ns}', expected '{expected[name]}'"
                )

    def test_bindings_reference_tenant_admin_role(self):
        docs = self._load_bindings()
        for doc in docs:
            name = doc.get("metadata", {}).get("name", "")
            if "team-" in name:
                role_ref = doc.get("roleRef", {})
                assert role_ref.get("name") == "platform-tenant-admin", (
                    f"Binding '{name}' must reference platform-tenant-admin ClusterRole"
                )


# ── Prometheus Alerting Rules ────────────────────────────────────────────

class TestPrometheusAlertRules:
    def _get_alert(self, alert_name):
        rules_doc = load_yaml("/app/monitoring/alerting-rules.yaml")
        for group in rules_doc["spec"]["groups"]:
            for rule in group.get("rules", []):
                if rule.get("alert") == alert_name:
                    return rule
        pytest.fail(f"Alert '{alert_name}' not found in alerting-rules.yaml")

    def test_high_error_rate_has_sum_aggregation(self):
        rule = self._get_alert("HighErrorRate")
        expr = str(rule["expr"]).lower()
        assert "sum" in expr and "by" in expr, (
            f"HighErrorRate must use 'sum by(...)' aggregation. Current: {rule['expr']}"
        )

    def test_high_error_rate_aggregates_by_namespace_service(self):
        rule = self._get_alert("HighErrorRate")
        expr = str(rule["expr"]).lower()
        assert "namespace" in expr and "service" in expr, (
            f"HighErrorRate must aggregate by (namespace, service). Current: {rule['expr']}"
        )

    def test_high_error_rate_has_for_duration(self):
        rule = self._get_alert("HighErrorRate")
        assert "for" in rule and rule["for"], (
            "HighErrorRate must have a 'for' duration"
        )

    def test_high_error_rate_for_is_10m(self):
        rule = self._get_alert("HighErrorRate")
        for_val = str(rule.get("for", ""))
        assert for_val == "10m", (
            f"HighErrorRate 'for' should be '10m', got '{for_val}'"
        )

    def test_high_memory_usage_has_for(self):
        rule = self._get_alert("HighMemoryUsage")
        assert "for" in rule and rule["for"], "HighMemoryUsage must have 'for'"

    def test_pod_crash_looping_has_for(self):
        rule = self._get_alert("PodCrashLooping")
        assert "for" in rule and rule["for"], "PodCrashLooping must have 'for'"


# ── OTel Collector ───────────────────────────────────────────────────────

class TestOTelCollector:
    def _load_config(self):
        collector = load_yaml("/app/monitoring/otel-collector.yaml")
        return collector["spec"]["config"]

    def test_memory_limiter_first_in_all_pipelines(self):
        config = self._load_config()
        for pipeline_name, pcfg in config["service"]["pipelines"].items():
            processors = pcfg.get("processors", [])
            if "memory_limiter" in processors:
                assert processors[0] == "memory_limiter", (
                    f"Pipeline '{pipeline_name}': memory_limiter must be first processor, "
                    f"got {processors}"
                )

    def test_all_exporter_refs_resolve(self):
        config = self._load_config()
        defined = set(config.get("exporters", {}).keys())
        for pipeline_name, pcfg in config["service"]["pipelines"].items():
            for exp in pcfg.get("exporters", []):
                assert exp in defined, (
                    f"Pipeline '{pipeline_name}' references undefined exporter '{exp}'. "
                    f"Defined: {defined}"
                )

    def test_all_receiver_refs_resolve(self):
        config = self._load_config()
        defined = set(config.get("receivers", {}).keys())
        for pipeline_name, pcfg in config["service"]["pipelines"].items():
            for recv in pcfg.get("receivers", []):
                assert recv in defined, (
                    f"Pipeline '{pipeline_name}' references undefined receiver '{recv}'. "
                    f"Defined: {defined}"
                )

    def test_all_processor_refs_resolve(self):
        config = self._load_config()
        defined = set(config.get("processors", {}).keys())
        for pipeline_name, pcfg in config["service"]["pipelines"].items():
            for proc in pcfg.get("processors", []):
                assert proc in defined, (
                    f"Pipeline '{pipeline_name}' references undefined processor '{proc}'. "
                    f"Defined: {defined}"
                )


# ── Crossplane Composition ───────────────────────────────────────────────

class TestCrossplaneFieldPaths:
    def test_composition_field_paths_match_xrd(self):
        xrd = load_yaml("/app/crossplane/xrd-database.yaml")
        composition = load_yaml("/app/crossplane/composition-database.yaml")

        params_props = (
            xrd["spec"]["versions"][0]["schema"]["openAPIV3Schema"]
            ["properties"]["spec"]["properties"]["parameters"]["properties"]
        )
        valid_names = set(params_props.keys())

        resources = []
        if "resources" in composition.get("spec", {}):
            resources = composition["spec"]["resources"]
        elif "pipeline" in composition.get("spec", {}):
            for step in composition["spec"]["pipeline"]:
                inp = step.get("input", {})
                resources.extend(inp.get("resources", []))

        assert len(resources) > 0, "Composition must have resources"

        for resource in resources:
            for patch in resource.get("patches", []):
                from_field = patch.get("fromFieldPath", "")
                if from_field.startswith("spec.parameters."):
                    param_name = from_field.split(".")[2]
                    assert param_name in valid_names, (
                        f"Composition references 'spec.parameters.{param_name}' "
                        f"but XRD schema only defines: {valid_names}"
                    )
