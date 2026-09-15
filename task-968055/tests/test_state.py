
import json
import os
import re
import pytest

try:
    import yaml
except ImportError:
    yaml = None


def load_json(path):
    with open(path) as f:
        return json.load(f)


def find_attack_events(report):
    """Find the attack events list in the report, trying various key names."""
    for key in ["attack_events", "events", "timeline", "attack_timeline",
                "malicious_events", "incidents", "attack_chain"]:
        if key in report and isinstance(report[key], list):
            return report[key]
    # Fall back: find any list with 5+ dicts having event-like fields
    for val in report.values():
        if isinstance(val, list) and len(val) >= 5:
            if val and isinstance(val[0], dict):
                sample_keys = set(val[0].keys())
                if sample_keys & {"timestamp", "verb", "resource", "action", "time"}:
                    return val
    return []


# ==================== FORENSIC REPORT TESTS ====================

class TestForensicReportExists:
    def test_file_exists(self):
        assert os.path.exists("/app/output/forensic-report.json"), \
            "forensic-report.json must exist at /app/output/"

    def test_valid_json(self):
        report = load_json("/app/output/forensic-report.json")
        assert isinstance(report, dict), "Report must be a JSON object"


class TestCompromisedIdentity:
    def test_identifies_ci_bot(self):
        report = load_json("/app/output/forensic-report.json")
        text = json.dumps(report).lower()
        assert "ci-bot" in text, \
            "Must identify ci-bot as the compromised identity"

    def test_identifies_pipeline_namespace(self):
        report = load_json("/app/output/forensic-report.json")
        # Check the compromised_identity field specifically, or fall back to full text
        ci = report.get("compromised_identity", {})
        ci_text = json.dumps(ci).lower() if ci else json.dumps(report).lower()
        assert "pipeline" in ci_text, \
            "Must identify pipeline as the service account's home namespace"

    def test_identifies_attack_source_ip(self):
        report = load_json("/app/output/forensic-report.json")
        text = json.dumps(report)
        assert "10.0.2.15" in text, \
            "Must identify 10.0.2.15 as the attack source IP"


class TestAttackEvents:
    def test_sufficient_events(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        assert len(events) >= 7, \
            f"Expected at least 7 attack events, got {len(events)}"

    def test_identifies_secret_access(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        text = json.dumps(events).lower()
        assert "secret" in text, \
            "Must identify secret access in attack events"

    def test_identifies_privilege_escalation(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        text = json.dumps(events).lower()
        assert any(x in text for x in [
            "clusterrolebinding", "cluster-admin", "privilege",
            "escalat", "rbac", "role-binding", "ci-pipeline-admin"
        ]), "Must identify privilege escalation (ClusterRoleBinding creation)"

    def test_identifies_kube_system_pod(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        text = json.dumps(events).lower()
        assert "kube-system" in text, \
            "Must identify pod creation in kube-system namespace"

    def test_identifies_deployment_modification(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        text = json.dumps(events).lower()
        assert any(x in text for x in [
            "backend-api", "deployment", "sidecar", "exfiltrat",
            "patch"
        ]), "Must identify deployment modification (sidecar injection)"

    def test_identifies_persistence_mechanism(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        text = json.dumps(events).lower()
        assert any(x in text for x in [
            "cronjob", "cron", "persistence", "log-rotation",
            "scheduled"
        ]), "Must identify persistence mechanism (CronJob creation)"

    def test_events_chronological_order(self):
        report = load_json("/app/output/forensic-report.json")
        events = find_attack_events(report)
        timestamps = [e.get("timestamp", "") for e in events if e.get("timestamp")]
        if len(timestamps) >= 2:
            assert timestamps == sorted(timestamps), \
                "Attack events must be in chronological order"

    def test_mitre_techniques_present(self):
        report = load_json("/app/output/forensic-report.json")
        text = json.dumps(report)
        techniques = re.findall(r'T\d{4}', text)
        assert len(techniques) >= 3, \
            f"Must include at least 3 MITRE ATT&CK technique IDs (found {len(techniques)})"


# ==================== AUDIT POLICY TESTS ====================

class TestAuditPolicy:
    @pytest.fixture(autouse=True)
    def skip_if_no_yaml(self):
        if yaml is None:
            pytest.skip("PyYAML not installed")

    def test_file_exists(self):
        assert os.path.exists("/app/output/audit-policy.yaml"), \
            "audit-policy.yaml must exist"

    def test_valid_yaml(self):
        with open("/app/output/audit-policy.yaml") as f:
            policy = yaml.safe_load(f)
        assert policy is not None, "Must be valid YAML"

    def test_correct_api_version(self):
        with open("/app/output/audit-policy.yaml") as f:
            policy = yaml.safe_load(f)
        assert policy.get("apiVersion") == "audit.k8s.io/v1", \
            "Must use apiVersion audit.k8s.io/v1"

    def test_correct_kind(self):
        with open("/app/output/audit-policy.yaml") as f:
            policy = yaml.safe_load(f)
        assert policy.get("kind") == "Policy", \
            "Must have kind: Policy"

    def test_has_rules(self):
        with open("/app/output/audit-policy.yaml") as f:
            policy = yaml.safe_load(f)
        assert "rules" in policy, "Must contain rules"
        assert len(policy["rules"]) >= 3, \
            f"Must have at least 3 audit rules, got {len(policy['rules'])}"

    def test_covers_secrets_at_high_level(self):
        with open("/app/output/audit-policy.yaml") as f:
            policy = yaml.safe_load(f)
        found = False
        for rule in policy["rules"]:
            resources = rule.get("resources", [])
            for r in resources:
                res_list = r.get("resources", [])
                if "secrets" in res_list:
                    assert rule["level"] in ["RequestResponse", "Request"], \
                        "Secrets must be logged at Request or RequestResponse level"
                    found = True
                    break
            if found:
                break
        assert found, "Must have a specific audit rule covering secrets"

    def test_covers_rbac_resources(self):
        with open("/app/output/audit-policy.yaml") as f:
            policy = yaml.safe_load(f)
        text = json.dumps(policy).lower()
        assert any(x in text for x in [
            "clusterrolebinding", "rolebinding",
            "clusterrole", "rbac"
        ]), "Audit policy must cover RBAC resources"


# ==================== NETWORK POLICY TESTS ====================

class TestNetworkPolicies:
    @pytest.fixture(autouse=True)
    def skip_if_no_yaml(self):
        if yaml is None:
            pytest.skip("PyYAML not installed")

    def test_directory_exists(self):
        assert os.path.isdir("/app/output/network-policies"), \
            "network-policies directory must exist at /app/output/"

    def test_sufficient_policies(self):
        np_dir = "/app/output/network-policies"
        files = [f for f in os.listdir(np_dir)
                 if f.endswith((".yaml", ".yml"))]
        assert len(files) >= 3, \
            f"Expected at least 3 NetworkPolicy files, got {len(files)}"

    def test_all_valid_network_policies(self):
        np_dir = "/app/output/network-policies"
        for f in os.listdir(np_dir):
            if not f.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(np_dir, f)) as fh:
                policy = yaml.safe_load(fh)
            assert policy.get("kind") == "NetworkPolicy", \
                f"{f} must have kind: NetworkPolicy"
            assert policy.get("apiVersion") == "networking.k8s.io/v1", \
                f"{f} must use apiVersion networking.k8s.io/v1"

    def test_policies_have_policy_types(self):
        np_dir = "/app/output/network-policies"
        for f in os.listdir(np_dir):
            if not f.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(np_dir, f)) as fh:
                policy = yaml.safe_load(fh)
            if policy.get("kind") == "NetworkPolicy":
                spec = policy.get("spec", {})
                types = spec.get("policyTypes", [])
                assert len(types) >= 1, \
                    f"{f} must specify policyTypes"

    def test_database_isolation(self):
        """Database must only accept ingress from backend-api."""
        np_dir = "/app/output/network-policies"
        found = False
        for f in os.listdir(np_dir):
            if not f.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(np_dir, f)) as fh:
                policy = yaml.safe_load(fh)
            if policy.get("kind") != "NetworkPolicy":
                continue
            selector = policy.get("spec", {}).get("podSelector", {}).get("matchLabels", {})
            fname = f.lower()
            if selector.get("app") == "database" or selector.get("app") == "postgres" \
                    or "database" in fname or "db" in fname or "postgres" in fname:
                found = True
                ingress = policy["spec"].get("ingress", [])
                text = json.dumps(ingress).lower()
                assert "backend" in text, \
                    "Database NetworkPolicy ingress must reference backend-api"
                break
        assert found, "Must have a NetworkPolicy isolating the database"

    def test_redis_isolation(self):
        """Redis must only accept ingress from backend-api."""
        np_dir = "/app/output/network-policies"
        found = False
        for f in os.listdir(np_dir):
            if not f.endswith((".yaml", ".yml")):
                continue
            with open(os.path.join(np_dir, f)) as fh:
                policy = yaml.safe_load(fh)
            if policy.get("kind") != "NetworkPolicy":
                continue
            selector = policy.get("spec", {}).get("podSelector", {}).get("matchLabels", {})
            fname = f.lower()
            if selector.get("app") == "redis" or "redis" in fname:
                found = True
                ingress = policy["spec"].get("ingress", [])
                text = json.dumps(ingress).lower()
                assert "backend" in text, \
                    "Redis NetworkPolicy ingress must reference backend-api"
                break
        assert found, "Must have a NetworkPolicy isolating redis"


# ==================== FALCO RULES TESTS ====================

class TestFalcoRules:
    @pytest.fixture(autouse=True)
    def skip_if_no_yaml(self):
        if yaml is None:
            pytest.skip("PyYAML not installed")

    def test_file_exists(self):
        assert os.path.exists("/app/output/falco-rules.yaml"), \
            "falco-rules.yaml must exist"

    def test_valid_yaml(self):
        with open("/app/output/falco-rules.yaml") as f:
            items = yaml.safe_load(f)
        assert isinstance(items, list), "Falco rules must be a YAML list"

    def test_sufficient_rules(self):
        with open("/app/output/falco-rules.yaml") as f:
            items = yaml.safe_load(f)
        rules = [item for item in items if isinstance(item, dict) and "rule" in item]
        assert len(rules) >= 3, \
            f"Expected at least 3 Falco rules, got {len(rules)}"

    def test_rules_have_required_fields(self):
        with open("/app/output/falco-rules.yaml") as f:
            items = yaml.safe_load(f)
        rules = [item for item in items if isinstance(item, dict) and "rule" in item]
        for rule in rules:
            assert "condition" in rule, \
                f"Rule '{rule['rule']}' missing condition field"
            assert "output" in rule, \
                f"Rule '{rule['rule']}' missing output field"
            assert "priority" in rule, \
                f"Rule '{rule['rule']}' missing priority field"

    def test_covers_secret_access(self):
        with open("/app/output/falco-rules.yaml") as f:
            text = f.read().lower()
        assert "secret" in text, \
            "Falco rules must include a rule covering secret access"

    def test_covers_privilege_escalation(self):
        with open("/app/output/falco-rules.yaml") as f:
            text = f.read().lower()
        assert any(x in text for x in [
            "clusterrolebinding", "privilege", "escalat",
            "role", "rbac", "cluster-admin"
        ]), "Falco rules must include a rule covering privilege escalation"
