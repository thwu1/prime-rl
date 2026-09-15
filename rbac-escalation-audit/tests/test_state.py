
import json
import os
import pytest


@pytest.fixture(scope="module")
def report():
    with open("/app/output/report.json") as f:
        return json.load(f)


def _find_subject(perms, substring):
    """Find the subject key containing the given substring."""
    matches = [k for k in perms if substring in k]
    assert len(matches) >= 1, f"Subject containing '{substring}' not found in effective_permissions"
    return matches[0]


# == Report structure ========================================================


class TestReportStructure:
    def test_report_exists(self):
        assert os.path.exists("/app/output/report.json")

    def test_report_valid_json(self, report):
        assert isinstance(report, dict)

    def test_has_required_sections(self, report):
        assert "effective_permissions" in report
        assert "escalation_paths" in report
        assert "wildcard_roles" in report


# == Effective permissions: dev-lead =========================================


class TestDevLeadPermissions:
    def test_has_staging_permissions(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "dev-lead@example.com")
        namespaced = perms[key].get("namespaced", {})
        assert "staging" in namespaced, "dev-lead should have permissions in staging"

    def test_no_cluster_wide(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "dev-lead@example.com")
        cluster = perms[key].get("cluster_wide", [])
        assert len(cluster) == 0, "dev-lead should have no cluster-wide permissions"

    def test_has_bind_in_staging(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "dev-lead@example.com")
        staging_rules = perms[key]["namespaced"]["staging"]
        has_bind = any("bind" in rule.get("verbs", []) for rule in staging_rules)
        assert has_bind, "dev-lead should have bind verb in staging"


# == Effective permissions: developer ========================================


class TestDeveloperPermissions:
    def test_pods_exec_in_development(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "developer@example.com")
        dev_rules = perms[key]["namespaced"].get("development", [])
        resources = set()
        for rule in dev_rules:
            resources.update(rule.get("resources", []))
        assert "pods/exec" in resources, "developer should have pods/exec in development"

    def test_configmaps_in_production(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "developer@example.com")
        prod_rules = perms[key]["namespaced"].get("production", [])
        resources = set()
        for rule in prod_rules:
            resources.update(rule.get("resources", []))
        assert "configmaps" in resources, "developer should have configmaps in production"

    def test_pods_log_in_production(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "developer@example.com")
        prod_rules = perms[key]["namespaced"].get("production", [])
        resources = set()
        for rule in prod_rules:
            resources.update(rule.get("resources", []))
        assert "pods/log" in resources, "developer should have pods/log in production"

    def test_no_secrets(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "developer@example.com")
        dev = perms[key]
        for rule in dev.get("cluster_wide", []):
            assert "secrets" not in rule.get("resources", []), \
                "developer should not have secrets cluster-wide"
        for ns, rules in dev.get("namespaced", {}).items():
            for rule in rules:
                assert "secrets" not in rule.get("resources", []), \
                    f"developer should not have secrets in {ns}"


# == Effective permissions: prometheus =======================================


class TestPrometheusPermissions:
    def test_has_cluster_wide(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "prometheus")
        cluster = perms[key].get("cluster_wide", [])
        assert len(cluster) > 0, "prometheus should have cluster-wide permissions"

    def test_aggregated_permissions(self, report):
        """Prometheus should have permissions from ALL three aggregated sub-roles."""
        perms = report["effective_permissions"]
        key = _find_subject(perms, "prometheus")
        cluster = perms[key]["cluster_wide"]
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "pods" in all_resources, "Should have pods from monitoring-pods"
        assert "pods/log" in all_resources, "Should have pods/log from monitoring-pods"
        assert "nodes" in all_resources, "Should have nodes from monitoring-nodes"
        assert "events" in all_resources, "Should have events from monitoring-events"


# == Effective permissions: grafana (BUG 2 - transitive aggregation) =========


class TestGrafanaPermissions:
    def test_has_cluster_wide(self, report):
        """grafana via full-monitoring must have transitively aggregated permissions."""
        perms = report["effective_permissions"]
        key = _find_subject(perms, "grafana")
        cluster = perms[key].get("cluster_wide", [])
        assert len(cluster) > 0, \
            "grafana should have cluster-wide permissions via full-monitoring"

    def test_transitive_aggregation_pods(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "grafana")
        cluster = perms[key]["cluster_wide"]
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "pods" in all_resources, \
            "grafana should have pods via full-monitoring -> monitoring-aggregate -> monitoring-pods"

    def test_transitive_aggregation_nodes(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "grafana")
        cluster = perms[key]["cluster_wide"]
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "nodes" in all_resources, \
            "grafana should have nodes via transitive aggregation"
        assert "nodes/metrics" in all_resources, \
            "grafana should have nodes/metrics via transitive aggregation"

    def test_transitive_aggregation_events(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "grafana")
        cluster = perms[key]["cluster_wide"]
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "events" in all_resources, \
            "grafana should have events via transitive aggregation"


# == Effective permissions: deploy-bot =======================================


class TestDeployBotPermissions:
    def test_cluster_wide_deployments(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "deploy-bot")
        cluster = perms[key].get("cluster_wide", [])
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "deployments" in all_resources, "deploy-bot should have deployments"


# == Effective permissions: ci-deployer (BUG 1 - JSON manifest) ==============


class TestCiDeployerPermissions:
    def test_has_secrets_cluster_wide(self, report):
        """ci-deployer should have secret-reader from the JSON-format CRB."""
        perms = report["effective_permissions"]
        key = _find_subject(perms, "ci-deployer")
        cluster = perms[key].get("cluster_wide", [])
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "secrets" in all_resources, \
            "ci-deployer should have secrets cluster-wide (from JSON CRB)"

    def test_has_deploy_permissions(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "ci-deployer")
        cluster = perms[key].get("cluster_wide", [])
        all_resources = set()
        for rule in cluster:
            all_resources.update(rule.get("resources", []))
        assert "deployments" in all_resources, \
            "ci-deployer should have deployments cluster-wide"

    def test_has_exec_in_ci(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "ci-deployer")
        namespaced = perms[key].get("namespaced", {})
        assert "ci" in namespaced, "ci-deployer should have permissions in ci namespace"
        ci_resources = set()
        for rule in namespaced["ci"]:
            ci_resources.update(rule.get("resources", []))
        assert "pods/exec" in ci_resources, \
            "ci-deployer should have pods/exec in ci namespace"

    def test_secret_watch_verb(self, report):
        """secret-reader grants watch verb - verify it's present."""
        perms = report["effective_permissions"]
        key = _find_subject(perms, "ci-deployer")
        cluster = perms[key].get("cluster_wide", [])
        secret_verbs = set()
        for rule in cluster:
            if "secrets" in rule.get("resources", []):
                secret_verbs.update(rule.get("verbs", []))
        assert "watch" in secret_verbs, \
            "ci-deployer should have watch on secrets (from secret-reader)"


# == Effective permissions: ci-bot ===========================================


class TestCiBotPermissions:
    def test_has_impersonate(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "ci-bot@example.com")
        cluster = perms[key].get("cluster_wide", [])
        has_imp = any("impersonate" in rule.get("verbs", []) for rule in cluster)
        assert has_imp, "ci-bot should have impersonate verb"


# == Effective permissions: backup-agent (BUG 3 - SA namespace default) ======


class TestBackupAgentPermissions:
    def test_has_backup_namespace(self, report):
        """backup-agent should get permissions via SA namespace defaulting."""
        perms = report["effective_permissions"]
        key = _find_subject(perms, "backup-agent")
        namespaced = perms[key].get("namespaced", {})
        assert "backup" in namespaced, \
            "backup-agent should have permissions in backup namespace"

    def test_has_pv_permissions(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "backup-agent")
        backup_rules = perms[key]["namespaced"]["backup"]
        all_resources = set()
        for rule in backup_rules:
            all_resources.update(rule.get("resources", []))
        assert "persistentvolumes" in all_resources, \
            "backup-agent should have PV access in backup namespace"
        assert "persistentvolumeclaims" in all_resources, \
            "backup-agent should have PVC access in backup namespace"

    def test_has_snapshot_permissions(self, report):
        perms = report["effective_permissions"]
        key = _find_subject(perms, "backup-agent")
        backup_rules = perms[key]["namespaced"]["backup"]
        all_resources = set()
        for rule in backup_rules:
            all_resources.update(rule.get("resources", []))
        assert "volumesnapshots" in all_resources, \
            "backup-agent should have volumesnapshot access in backup namespace"


# == Escalation paths ========================================================


class TestEscalationPaths:
    def test_bind_escalation_detected(self, report):
        """dev-lead has bind verb on roles/rolebindings in staging."""
        paths = report["escalation_paths"]
        bind_paths = [p for p in paths if p["type"] == "bind"]
        bind_subjects = {p["subject"] for p in bind_paths}
        assert any("dev-lead" in s for s in bind_subjects), \
            "Should detect bind escalation for dev-lead"

    def test_impersonate_escalation_detected(self, report):
        """ci-bot can impersonate admin."""
        paths = report["escalation_paths"]
        imp_paths = [p for p in paths if p["type"] == "impersonate"]
        imp_subjects = {p["subject"] for p in imp_paths}
        assert any("ci-bot" in s for s in imp_subjects), \
            "Should detect impersonate escalation for ci-bot"

    def test_create_pods_developer(self, report):
        """developer can create pods + exec into them in development."""
        paths = report["escalation_paths"]
        pod_paths = [p for p in paths if p["type"] == "create_pods"]
        pod_subjects = {p["subject"] for p in pod_paths}
        assert any("developer" in s for s in pod_subjects), \
            "Should detect create_pods escalation for developer"

    def test_escalate_verb_detected(self, report):
        """sre-team has escalate verb on clusterroles."""
        paths = report["escalation_paths"]
        esc_paths = [p for p in paths if p["type"] == "escalate"]
        esc_subjects = {p["subject"] for p in esc_paths}
        assert any("sre" in s for s in esc_subjects), \
            "Should detect escalate-verb escalation for sre-team"

    def test_create_pods_ci_deployer_cross_scope(self, report):
        """ci-deployer has cluster-wide pod create + namespace-scoped pods/exec.

        This is a cross-scope escalation: cluster-wide permissions to create
        pods combined with namespace-scoped pods/exec in ci namespace.
        """
        paths = report["escalation_paths"]
        pod_paths = [p for p in paths if p["type"] == "create_pods"]
        ci_deployer_pods = [
            p for p in pod_paths if "ci-deployer" in p["subject"]
        ]
        assert len(ci_deployer_pods) >= 1, \
            "Should detect cross-scope create_pods escalation for ci-deployer"

    def test_admin_full_escalation(self, report):
        """admin with cluster-admin-custom should trigger all escalation types."""
        paths = report["escalation_paths"]
        admin_paths = [p for p in paths if "admin@example.com" in p["subject"]]
        admin_types = {p["type"] for p in admin_paths}
        assert "bind" in admin_types, "admin should have bind escalation"
        assert "escalate" in admin_types, "admin should have escalate escalation"
        assert "impersonate" in admin_types, "admin should have impersonate escalation"
        assert "create_pods" in admin_types, "admin should have create_pods escalation"


# == Wildcard roles ==========================================================


class TestWildcardRoles:
    def test_cluster_admin_flagged(self, report):
        wildcards = report["wildcard_roles"]
        names = {w["name"] for w in wildcards}
        assert "cluster-admin-custom" in names, \
            "cluster-admin-custom should be flagged for wildcard usage"

    def test_namespace_admin_flagged(self, report):
        wildcards = report["wildcard_roles"]
        names = {w["name"] for w in wildcards}
        assert "namespace-admin" in names, \
            "namespace-admin should be flagged for wildcard verbs"

    def test_cluster_admin_wildcard_details(self, report):
        wildcards = report["wildcard_roles"]
        ca = [w for w in wildcards if w["name"] == "cluster-admin-custom"]
        assert len(ca) == 1
        wf = ca[0].get("wildcard_fields", [])
        assert "verbs" in wf, "Should flag wildcard verbs"
        assert "resources" in wf, "Should flag wildcard resources"
        assert "apiGroups" in wf, "Should flag wildcard apiGroups"

    def test_namespace_admin_wildcard_verbs_only(self, report):
        wildcards = report["wildcard_roles"]
        na = [w for w in wildcards if w["name"] == "namespace-admin"]
        assert len(na) == 1
        wf = na[0].get("wildcard_fields", [])
        assert "verbs" in wf, "namespace-admin should have wildcard verbs"
        assert "resources" not in wf, \
            "namespace-admin should NOT have wildcard resources"
        assert "apiGroups" not in wf, \
            "namespace-admin should NOT have wildcard apiGroups"
