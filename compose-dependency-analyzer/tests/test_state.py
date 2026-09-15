"""Tests for Docker Compose Production Topology Auditor."""

import json
import subprocess
import sys

import pytest


@pytest.fixture(scope="session")
def audit_result():
    """Run the auditor and return parsed JSON result."""
    result = subprocess.run(
        [sys.executable, "/app/audit.py"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd="/app",
    )
    assert result.returncode == 0, (
        f"Auditor exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout[:500]}"
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Auditor output is not valid JSON: {exc}\nOutput: {result.stdout[:500]}")
    return data


# ========== structural / smoke tests ==========

def test_output_has_required_keys(audit_result):
    required = [
        "services",
        "network_violations",
        "port_conflicts",
        "resource_violations",
        "healthcheck_gaps",
        "undefined_references",
        "circular_dependencies",
        "startup_waves",
        "critical_path_length",
        "critical_path",
        "single_points_of_failure",
    ]
    for key in required:
        assert key in audit_result, f"Missing required key: {key}"


def test_list_valued_keys(audit_result):
    for key in ["services", "network_violations", "port_conflicts",
                 "resource_violations", "healthcheck_gaps", "undefined_references",
                 "circular_dependencies", "startup_waves", "critical_path",
                 "single_points_of_failure"]:
        assert isinstance(audit_result[key], list), f"{key} should be a list"


def test_critical_path_length_is_int(audit_result):
    assert isinstance(audit_result["critical_path_length"], int), \
        "critical_path_length should be an integer"


# ========== services (merge correctness) ==========

def test_services_count(audit_result):
    assert len(audit_result["services"]) == 13, (
        f"Expected 13 services, got {len(audit_result['services'])}: {audit_result['services']}"
    )


def test_services_list(audit_result):
    expected = [
        "admin-panel", "analytics-worker", "api-gateway", "auth-api",
        "grafana", "notification-worker", "order-api", "postgres",
        "product-api", "prometheus", "rabbitmq", "redis", "user-api",
    ]
    assert audit_result["services"] == expected


def test_services_sorted(audit_result):
    assert audit_result["services"] == sorted(audit_result["services"])


# ========== network violations ==========

def test_network_violations_count(audit_result):
    assert len(audit_result["network_violations"]) == 3, (
        f"Expected 3 network violations, got {len(audit_result['network_violations'])}"
    )


def test_network_violation_auth_to_notification(audit_result):
    violations = audit_result["network_violations"]
    match = [v for v in violations
             if v["source"] == "auth-api" and v["target"] == "notification-worker"]
    assert len(match) == 1, "Expected auth-api -> notification-worker network violation"
    v = match[0]
    assert v["env_var"] == "NOTIFICATION_CALLBACK"
    assert set(v["source_networks"]) == {"backend", "frontend"}
    assert v["target_networks"] == ["messaging"]


def test_network_violation_notification_to_auth(audit_result):
    violations = audit_result["network_violations"]
    match = [v for v in violations
             if v["source"] == "notification-worker" and v["target"] == "auth-api"]
    assert len(match) == 1, "Expected notification-worker -> auth-api network violation"
    v = match[0]
    assert v["env_var"] == "AUTH_SERVICE_URL"
    assert v["source_networks"] == ["messaging"]
    assert set(v["target_networks"]) == {"backend", "frontend"}


def test_network_violation_notification_to_user(audit_result):
    violations = audit_result["network_violations"]
    match = [v for v in violations
             if v["source"] == "notification-worker" and v["target"] == "user-api"]
    assert len(match) == 1, "Expected notification-worker -> user-api network violation"
    v = match[0]
    assert v["env_var"] == "USER_SERVICE_URL"
    assert v["source_networks"] == ["messaging"]
    assert set(v["target_networks"]) == {"backend", "frontend"}


def test_no_false_positive_network_violations(audit_result):
    """Services that share a network should NOT appear as violations."""
    violations = audit_result["network_violations"]
    sources = {(v["source"], v["target"]) for v in violations}
    assert ("order-api", "rabbitmq") not in sources
    assert ("api-gateway", "redis") not in sources
    assert ("user-api", "postgres") not in sources


def test_network_violations_sorted(audit_result):
    violations = audit_result["network_violations"]
    keys = [(v["source"], v["target"], v["env_var"]) for v in violations]
    assert keys == sorted(keys), "network_violations must be sorted by (source, target, env_var)"


def test_network_violation_sublists_sorted(audit_result):
    for v in audit_result["network_violations"]:
        assert v["source_networks"] == sorted(v["source_networks"])
        assert v["target_networks"] == sorted(v["target_networks"])


# ========== port conflicts ==========

def test_port_conflicts_count(audit_result):
    assert len(audit_result["port_conflicts"]) == 1, (
        f"Expected 1 port conflict, got {len(audit_result['port_conflicts'])}"
    )


def test_port_conflict_8080(audit_result):
    conflict = audit_result["port_conflicts"][0]
    assert conflict["host_port"] == 8080
    assert set(conflict["services"]) == {"auth-api", "user-api"}


def test_port_conflict_host_port_is_int(audit_result):
    for conflict in audit_result["port_conflicts"]:
        assert isinstance(conflict["host_port"], int), "host_port must be an integer"


def test_no_false_positive_port_conflicts(audit_result):
    ports = {c["host_port"] for c in audit_result["port_conflicts"]}
    assert ports == {8080}


# ========== resource violations ==========

def test_resource_violations_count(audit_result):
    assert len(audit_result["resource_violations"]) == 2, (
        f"Expected 2 resource violations, got {len(audit_result['resource_violations'])}"
    )


def test_resource_violation_user_api(audit_result):
    violations = audit_result["resource_violations"]
    match = [v for v in violations if v["service"] == "user-api"]
    assert len(match) == 1, "Expected user-api resource violation"

    def parse_mem(s):
        s = str(s).strip().upper()
        if s.endswith("G"):
            return float(s[:-1]) * 1024
        if s.endswith("M"):
            return float(s[:-1])
        return float(s)

    v = match[0]
    assert parse_mem(v["reservation"]) > parse_mem(v["limit"]), (
        f"reservation {v['reservation']} should exceed limit {v['limit']}"
    )


def test_resource_violation_analytics_worker(audit_result):
    violations = audit_result["resource_violations"]
    match = [v for v in violations if v["service"] == "analytics-worker"]
    assert len(match) == 1, "Expected analytics-worker resource violation"

    def parse_mem(s):
        s = str(s).strip().upper()
        if s.endswith("G"):
            return float(s[:-1]) * 1024
        if s.endswith("M"):
            return float(s[:-1])
        return float(s)

    v = match[0]
    assert parse_mem(v["reservation"]) > parse_mem(v["limit"]), (
        f"reservation {v['reservation']} should exceed limit {v['limit']}"
    )


def test_no_false_positive_resource_violations(audit_result):
    flagged = {v["service"] for v in audit_result["resource_violations"]}
    for svc in ["postgres", "redis", "auth-api", "notification-worker", "api-gateway"]:
        assert svc not in flagged, f"{svc} should not have a resource violation"


def test_resource_violations_sorted(audit_result):
    services = [v["service"] for v in audit_result["resource_violations"]]
    assert services == sorted(services)


# ========== healthcheck gaps ==========

def test_healthcheck_gaps_count(audit_result):
    assert len(audit_result["healthcheck_gaps"]) == 1, (
        f"Expected 1 healthcheck gap, got {len(audit_result['healthcheck_gaps'])}"
    )


def test_healthcheck_gap_grafana_prometheus(audit_result):
    gap = audit_result["healthcheck_gaps"][0]
    assert gap["service"] == "grafana"
    assert gap["depends_on"] == "prometheus"
    assert gap["condition"] == "service_healthy"


def test_no_false_positive_healthcheck_gaps(audit_result):
    flagged = {g["service"] for g in audit_result["healthcheck_gaps"]}
    for svc in ["auth-api", "user-api", "product-api", "order-api",
                "notification-worker", "analytics-worker"]:
        assert svc not in flagged, f"{svc} should not have a healthcheck gap"


# ========== undefined references ==========

def test_undefined_references_count(audit_result):
    assert len(audit_result["undefined_references"]) == 3, (
        f"Expected 3 undefined references, got {len(audit_result['undefined_references'])}"
    )


def test_undefined_ref_search_api(audit_result):
    refs = audit_result["undefined_references"]
    match = [r for r in refs if r["referenced_hostname"] == "search-api"]
    assert len(match) == 1
    assert match[0]["service"] == "product-api"
    assert match[0]["env_var"] == "SEARCH_ENGINE_URL"


def test_undefined_ref_inventory_api(audit_result):
    refs = audit_result["undefined_references"]
    match = [r for r in refs if r["referenced_hostname"] == "inventory-api"]
    assert len(match) == 1
    assert match[0]["service"] == "product-api"
    assert match[0]["env_var"] == "INVENTORY_URL"


def test_undefined_ref_cache_service(audit_result):
    refs = audit_result["undefined_references"]
    match = [r for r in refs if r["referenced_hostname"] == "cache-service"]
    assert len(match) == 1
    assert match[0]["service"] == "user-api"
    assert match[0]["env_var"] == "CACHE_URL"


def test_external_hostname_not_in_undefined(audit_result):
    refs = audit_result["undefined_references"]
    hostnames = {r["referenced_hostname"] for r in refs}
    assert "api.stripe.com" not in hostnames
    assert "smtp.company.com" not in hostnames


def test_undefined_references_sorted(audit_result):
    keys = [(r["service"], r["env_var"]) for r in audit_result["undefined_references"]]
    assert keys == sorted(keys), "undefined_references must be sorted by (service, env_var)"


# ========== merge correctness validation ==========

def test_prod_port_merge_concatenation(audit_result):
    """Verify ports are concatenated (not replaced) during merge."""
    conflicts = audit_result["port_conflicts"]
    conflict_8080 = [c for c in conflicts if c["host_port"] == 8080]
    assert len(conflict_8080) == 1, (
        "Port 8080 conflict proves ports were correctly concatenated during merge"
    )


def test_prod_network_merge_fixes_user_api(audit_result):
    """In base, user-api is only on frontend. Prod adds backend.
    user-api -> postgres should NOT be a network violation in prod."""
    violations = audit_result["network_violations"]
    user_pg = [v for v in violations
               if v["source"] == "user-api" and v["target"] == "postgres"]
    assert len(user_pg) == 0, (
        "user-api -> postgres should not be a violation after prod network merge"
    )


def test_prod_depends_on_merge_overrides_condition(audit_result):
    """Prod changes grafana->prometheus from service_started to service_healthy.
    This should be detected as a healthcheck gap since prometheus has no healthcheck."""
    gaps = audit_result["healthcheck_gaps"]
    grafana_gaps = [g for g in gaps if g["service"] == "grafana"]
    assert len(grafana_gaps) == 1, (
        "grafana->prometheus healthcheck gap proves depends_on condition was merged correctly"
    )


def test_prod_environment_merge_adds_inventory_url(audit_result):
    """Prod adds INVENTORY_URL to product-api environment.
    This should appear as an undefined reference."""
    refs = audit_result["undefined_references"]
    inv = [r for r in refs if r["env_var"] == "INVENTORY_URL"]
    assert len(inv) == 1, (
        "INVENTORY_URL reference proves environment was correctly merged (not replaced)"
    )
    assert inv[0]["service"] == "product-api"


# ========== circular dependencies ==========

def test_circular_deps_count(audit_result):
    """Exactly 1 SCC should exist in the combined dependency graph."""
    assert len(audit_result["circular_dependencies"]) == 1, (
        f"Expected 1 circular dependency SCC, got {len(audit_result['circular_dependencies'])}"
    )


def test_circular_deps_members(audit_result):
    """The SCC contains auth-api, notification-worker, user-api.
    auth-api has implicit dep on notification-worker (NOTIFICATION_CALLBACK URL),
    notification-worker has implicit deps on auth-api and user-api (env var URLs),
    user-api has explicit dep on auth-api (depends_on)."""
    scc = audit_result["circular_dependencies"][0]
    assert scc == ["auth-api", "notification-worker", "user-api"], (
        f"Expected SCC [auth-api, notification-worker, user-api], got {scc}"
    )


def test_circular_deps_sorted(audit_result):
    """Each SCC must be internally sorted, and the list of SCCs sorted."""
    for scc in audit_result["circular_dependencies"]:
        assert scc == sorted(scc), "SCC members must be sorted alphabetically"
    firsts = [scc[0] for scc in audit_result["circular_dependencies"]]
    assert firsts == sorted(firsts), "SCCs must be sorted by first element"


def test_circular_deps_uses_combined_graph(audit_result):
    """The cycle only exists because of BOTH explicit and implicit deps.
    If only explicit deps were used, no cycle would exist (notification-worker
    has no depends_on pointing to auth-api or user-api)."""
    scc = audit_result["circular_dependencies"][0]
    assert "notification-worker" in scc, (
        "notification-worker must be in the SCC — it's connected via implicit deps"
    )


def test_no_false_positive_cycles(audit_result):
    """Infrastructure services should NOT be in any cycle."""
    all_cycle_members = set()
    for scc in audit_result["circular_dependencies"]:
        all_cycle_members.update(scc)
    for svc in ["postgres", "redis", "rabbitmq", "prometheus", "grafana",
                "api-gateway", "order-api", "product-api"]:
        assert svc not in all_cycle_members, f"{svc} should not be in any cycle"


# ========== startup waves ==========

def test_startup_waves_count(audit_result):
    assert len(audit_result["startup_waves"]) == 4, (
        f"Expected 4 startup waves, got {len(audit_result['startup_waves'])}"
    )


def test_startup_wave_0(audit_result):
    """Wave 0: services with no explicit dependencies."""
    assert audit_result["startup_waves"][0] == [
        "postgres", "prometheus", "rabbitmq", "redis"
    ]


def test_startup_wave_1(audit_result):
    """Wave 1: services whose all deps are in wave 0."""
    assert audit_result["startup_waves"][1] == [
        "analytics-worker", "auth-api", "grafana", "notification-worker", "product-api"
    ]


def test_startup_wave_2(audit_result):
    """Wave 2: services depending on wave-1 services."""
    assert audit_result["startup_waves"][2] == [
        "admin-panel", "order-api", "user-api"
    ]


def test_startup_wave_3(audit_result):
    """Wave 3: api-gateway depends on services in waves 1 and 2."""
    assert audit_result["startup_waves"][3] == ["api-gateway"]


def test_all_services_in_waves(audit_result):
    """Every service must appear in exactly one wave."""
    all_in_waves = []
    for wave in audit_result["startup_waves"]:
        all_in_waves.extend(wave)
    assert sorted(all_in_waves) == audit_result["services"], (
        "All services must appear exactly once across all waves"
    )


def test_startup_waves_each_sorted(audit_result):
    for i, wave in enumerate(audit_result["startup_waves"]):
        assert wave == sorted(wave), f"Wave {i} must be sorted alphabetically"


def test_startup_waves_use_explicit_deps_only(audit_result):
    """notification-worker should be in wave 1 (explicit dep only on rabbitmq,
    which is in wave 0). If implicit deps were used, it would be in a later wave
    due to its dep on auth-api."""
    assert "notification-worker" in audit_result["startup_waves"][1], (
        "notification-worker should be in wave 1 — startup waves use explicit deps only"
    )


# ========== critical path ==========

def test_critical_path_length(audit_result):
    assert audit_result["critical_path_length"] == 4, (
        f"Expected critical path length 4, got {audit_result['critical_path_length']}"
    )


def test_critical_path(audit_result):
    assert audit_result["critical_path"] == [
        "postgres", "auth-api", "order-api", "api-gateway"
    ], f"Expected [postgres, auth-api, order-api, api-gateway], got {audit_result['critical_path']}"


def test_critical_path_length_matches_path(audit_result):
    assert len(audit_result["critical_path"]) == audit_result["critical_path_length"], (
        "critical_path length must equal critical_path_length"
    )


def test_critical_path_valid_chain(audit_result):
    """Each consecutive pair in the path must be a valid explicit dependency."""
    path = audit_result["critical_path"]
    # path[i] must be an explicit dep of path[i+1]
    # We verify this indirectly: path[0] must be in wave 0,
    # path[-1] must be in the last wave
    waves = audit_result["startup_waves"]
    assert path[0] in waves[0], "Critical path must start in wave 0"
    assert path[-1] in waves[-1], "Critical path must end in the last wave"


# ========== single points of failure ==========

def test_spof_count(audit_result):
    """All 13 services should be listed."""
    assert len(audit_result["single_points_of_failure"]) == 13, (
        f"Expected 13 SPOF entries, got {len(audit_result['single_points_of_failure'])}"
    )


def test_spof_postgres(audit_result):
    spof = audit_result["single_points_of_failure"]
    match = [s for s in spof if s["service"] == "postgres"]
    assert len(match) == 1
    assert match[0]["affected_count"] == 7
    assert match[0]["affected_services"] == [
        "admin-panel", "analytics-worker", "api-gateway",
        "auth-api", "order-api", "product-api", "user-api"
    ]


def test_spof_redis(audit_result):
    spof = audit_result["single_points_of_failure"]
    match = [s for s in spof if s["service"] == "redis"]
    assert len(match) == 1
    assert match[0]["affected_count"] == 7
    assert match[0]["affected_services"] == [
        "admin-panel", "analytics-worker", "api-gateway",
        "auth-api", "order-api", "product-api", "user-api"
    ]


def test_spof_auth_api(audit_result):
    spof = audit_result["single_points_of_failure"]
    match = [s for s in spof if s["service"] == "auth-api"]
    assert len(match) == 1
    assert match[0]["affected_count"] == 4
    assert match[0]["affected_services"] == [
        "admin-panel", "api-gateway", "order-api", "user-api"
    ]


def test_spof_rabbitmq(audit_result):
    spof = audit_result["single_points_of_failure"]
    match = [s for s in spof if s["service"] == "rabbitmq"]
    assert len(match) == 1
    assert match[0]["affected_count"] == 4
    assert match[0]["affected_services"] == [
        "analytics-worker", "api-gateway", "notification-worker", "order-api"
    ]


def test_spof_product_api(audit_result):
    spof = audit_result["single_points_of_failure"]
    match = [s for s in spof if s["service"] == "product-api"]
    assert len(match) == 1
    assert match[0]["affected_count"] == 2
    assert match[0]["affected_services"] == ["api-gateway", "order-api"]


def test_spof_leaf_services_zero(audit_result):
    """Services with no dependents should have affected_count 0."""
    spof = audit_result["single_points_of_failure"]
    leaf_services = {"admin-panel", "analytics-worker", "api-gateway",
                     "grafana", "notification-worker"}
    for entry in spof:
        if entry["service"] in leaf_services:
            assert entry["affected_count"] == 0, (
                f"{entry['service']} should have 0 affected services"
            )
            assert entry["affected_services"] == [], (
                f"{entry['service']} should have empty affected_services"
            )


def test_spof_sorting(audit_result):
    """Must be sorted by (-affected_count, service)."""
    spof = audit_result["single_points_of_failure"]
    keys = [(-s["affected_count"], s["service"]) for s in spof]
    assert keys == sorted(keys), (
        "SPOF must be sorted by descending affected_count, then ascending service name"
    )


def test_spof_no_self_reference(audit_result):
    """No service should list itself in affected_services."""
    for entry in audit_result["single_points_of_failure"]:
        assert entry["service"] not in entry["affected_services"], (
            f"{entry['service']} must not be in its own affected_services"
        )


def test_spof_affected_services_sorted(audit_result):
    for entry in audit_result["single_points_of_failure"]:
        assert entry["affected_services"] == sorted(entry["affected_services"]), (
            f"affected_services for {entry['service']} must be sorted"
        )


def test_spof_affected_count_matches_list(audit_result):
    for entry in audit_result["single_points_of_failure"]:
        assert entry["affected_count"] == len(entry["affected_services"]), (
            f"affected_count for {entry['service']} must match len(affected_services)"
        )


def test_spof_uses_explicit_deps(audit_result):
    """SPOF uses explicit deps only. notification-worker has no explicit dependents,
    so its affected_count should be 0 even though auth-api implicitly depends on it."""
    spof = audit_result["single_points_of_failure"]
    nw = [s for s in spof if s["service"] == "notification-worker"]
    assert len(nw) == 1
    assert nw[0]["affected_count"] == 0, (
        "notification-worker should have 0 affected (SPOF uses explicit deps only)"
    )
