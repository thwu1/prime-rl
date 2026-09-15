"""Tests for Kubernetes audit log forensics task.

"""
import json
import os
import pytest
import yaml

FINDINGS_DIR = "/app/findings"


# ============================================================
# Helper functions
# ============================================================

def load_json(filename):
    path = os.path.join(FINDINGS_DIR, filename)
    assert os.path.isfile(path), f"Missing required file: {path}"
    with open(path) as f:
        return json.load(f)


def load_yaml(filename):
    path = os.path.join(FINDINGS_DIR, filename)
    assert os.path.isfile(path), f"Missing required file: {path}"
    with open(path) as f:
        docs = list(yaml.safe_load_all(f))
    # For single-doc files, return the single doc; for multi-doc return all
    if len(docs) == 1:
        return docs[0]
    return docs


def flatten_str(obj):
    """Recursively collect all string values from a nested structure."""
    strings = []
    if isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            strings.extend(flatten_str(v))
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            strings.extend(flatten_str(item))
    return strings


# ============================================================
# TIMELINE TESTS
# ============================================================

class TestAttackTimeline:
    """Validate the attack timeline reconstruction."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.timeline = load_json("attack_timeline.json")

    def test_is_list(self):
        assert isinstance(self.timeline, list), "Timeline must be a JSON array"

    def test_minimum_events(self):
        assert len(self.timeline) >= 10, \
            f"Expected at least 10 attack events, found {len(self.timeline)}"

    def test_events_have_required_fields(self):
        required = {"timestamp", "verb", "resource", "user"}
        for i, event in enumerate(self.timeline):
            assert isinstance(event, dict), f"Event {i} is not a dict"
            missing = required - set(event.keys())
            assert not missing, f"Event {i} missing fields: {missing}"

    def test_chronological_order(self):
        timestamps = [e["timestamp"] for e in self.timeline]
        assert timestamps == sorted(timestamps), "Events must be in chronological order"

    def test_compromised_user_identified(self):
        users = {e["user"] for e in self.timeline}
        matching = [u for u in users if "webapp-sa" in u and "production" in u]
        assert matching, "Must identify compromised user containing 'webapp-sa' in 'production'"

    def test_clusterrolebinding_creation_detected(self):
        found = any(
            "clusterrolebinding" in e.get("resource", "").lower()
            and e.get("verb", "") in ("create",)
            for e in self.timeline
        )
        assert found, "Must detect ClusterRoleBinding creation (privilege escalation)"

    def test_debug_binding_name_found(self):
        all_strings = flatten_str(self.timeline)
        found = any("debug-binding" in s for s in all_strings)
        assert found, "Must identify the specific ClusterRoleBinding name 'debug-binding'"

    def test_secret_access_detected(self):
        secret_events = [
            e for e in self.timeline
            if "secret" in e.get("resource", "").lower()
        ]
        assert len(secret_events) >= 3, \
            f"Must detect at least 3 secret access events, found {len(secret_events)}"

    def test_specific_secrets_identified(self):
        all_strings = flatten_str(self.timeline)
        all_text = " ".join(all_strings).lower()
        assert "etcd-certs" in all_text, "Must identify exfiltrated secret 'etcd-certs'"
        assert "db-credentials" in all_text, "Must identify exfiltrated secret 'db-credentials'"
        assert "api-keys" in all_text, "Must identify exfiltrated secret 'api-keys'"

    def test_privileged_pod_detected(self):
        found = any(
            e.get("verb", "") == "create"
            and "pod" in e.get("resource", "").lower()
            and e.get("name", "") == "debug-pod"
            for e in self.timeline
        )
        if not found:
            # Looser check: just look for debug-pod anywhere
            all_strings = flatten_str(self.timeline)
            found = any("debug-pod" in s for s in all_strings)
        assert found, "Must detect creation of malicious pod 'debug-pod'"

    def test_exec_detected(self):
        all_strings = flatten_str(self.timeline)
        all_text = " ".join(all_strings).lower()
        assert "exec" in all_text, "Must detect pod exec operation"

    def test_namespace_creation_detected(self):
        all_strings = flatten_str(self.timeline)
        found = any("maintenance" in s for s in all_strings)
        assert found, "Must detect creation of persistence namespace 'maintenance'"

    def test_persistence_deployment_detected(self):
        all_strings = flatten_str(self.timeline)
        found = any("backdoor-deploy" in s for s in all_strings)
        assert found, "Must detect persistence deployment 'backdoor-deploy'"

    def test_mitre_techniques_present(self):
        techniques = []
        for e in self.timeline:
            t = e.get("mitre_technique", "")
            if t:
                techniques.append(t)
        assert len(techniques) >= 5, \
            f"Expected MITRE technique IDs for at least 5 events, found {len(techniques)}"
        # All should start with T followed by digits
        for t in techniques:
            assert t.startswith("T"), \
                f"MITRE technique '{t}' should start with 'T'"


# ============================================================
# INDICATORS OF COMPROMISE TESTS
# ============================================================

class TestIndicatorsOfCompromise:
    """Validate the IOC extraction."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.iocs = load_json("indicators_of_compromise.json")

    def test_is_dict(self):
        assert isinstance(self.iocs, dict), "IOCs must be a JSON object"

    def test_compromised_identity(self):
        identity = self.iocs.get("compromised_identity", "")
        assert "webapp-sa" in identity, \
            f"Compromised identity must contain 'webapp-sa', got '{identity}'"
        assert "production" in identity, \
            f"Compromised identity must reference 'production' namespace, got '{identity}'"

    def test_attacker_source_ip(self):
        ip = self.iocs.get("attacker_source_ip", "")
        assert ip == "10.0.15.23", \
            f"Attacker source IP must be '10.0.15.23', got '{ip}'"

    def test_attacker_user_agent(self):
        ua = self.iocs.get("attacker_user_agent", "")
        assert "kubectl" in ua, \
            f"Attacker user agent must contain 'kubectl', got '{ua}'"
        assert "linux" in ua.lower(), \
            f"Attacker user agent must reference 'linux', got '{ua}'"

    def test_exfiltrated_secrets(self):
        secrets = self.iocs.get("exfiltrated_secrets", [])
        assert isinstance(secrets, list), "exfiltrated_secrets must be a list"
        assert len(secrets) >= 3, \
            f"Must identify at least 3 exfiltrated secrets, found {len(secrets)}"

        # Check each expected secret is present
        secret_names = set()
        for s in secrets:
            if isinstance(s, dict):
                secret_names.add(s.get("name", ""))
            elif isinstance(s, str):
                secret_names.add(s)

        assert "etcd-certs" in secret_names, "Must list 'etcd-certs' as exfiltrated"
        assert "db-credentials" in secret_names, "Must list 'db-credentials' as exfiltrated"
        assert "api-keys" in secret_names, "Must list 'api-keys' as exfiltrated"

    def test_malicious_resources_present(self):
        resources = self.iocs.get("malicious_resources", {})
        assert isinstance(resources, dict), "malicious_resources must be a dict"

        all_text = " ".join(flatten_str(resources)).lower()
        assert "debug-binding" in all_text, \
            "malicious_resources must reference 'debug-binding'"
        assert "debug-pod" in all_text, \
            "malicious_resources must reference 'debug-pod'"
        assert "maintenance" in all_text, \
            "malicious_resources must reference 'maintenance' namespace"
        assert "backdoor-deploy" in all_text, \
            "malicious_resources must reference 'backdoor-deploy'"

    def test_malicious_resources_service_account(self):
        resources = self.iocs.get("malicious_resources", {})
        all_text = " ".join(flatten_str(resources)).lower()
        assert "maint-worker-sa" in all_text, \
            "malicious_resources must reference persistence service account 'maint-worker-sa'"

    def test_malicious_resources_rolebinding(self):
        resources = self.iocs.get("malicious_resources", {})
        all_text = " ".join(flatten_str(resources)).lower()
        assert "maint-admin-binding" in all_text, \
            "malicious_resources must reference persistence rolebinding 'maint-admin-binding'"


# ============================================================
# DETECTION RULES TESTS
# ============================================================

VALID_FALCO_PRIORITIES = {
    "EMERGENCY", "ALERT", "CRITICAL", "ERROR", "WARNING",
    "NOTICE", "INFORMATIONAL", "DEBUG",
    "emergency", "alert", "critical", "error", "warning",
    "notice", "informational", "debug",
    "Emergency", "Alert", "Critical", "Error", "Warning",
    "Notice", "Informational", "Debug",
}


class TestDetectionRules:
    """Validate Falco detection rules."""

    @pytest.fixture(autouse=True)
    def setup(self):
        raw = load_yaml("detection_rules.yaml")
        # Handle both list-of-rules and list-of-docs
        if isinstance(raw, list) and all(isinstance(r, dict) and "rule" in r for r in raw):
            self.rules = raw
        elif isinstance(raw, list) and len(raw) > 0:
            # Multi-doc YAML: flatten
            self.rules = []
            for doc in raw:
                if isinstance(doc, list):
                    self.rules.extend(doc)
                elif isinstance(doc, dict) and "rule" in doc:
                    self.rules.append(doc)
        else:
            self.rules = []

    def test_has_rules(self):
        assert len(self.rules) >= 4, \
            f"Expected at least 4 detection rules, found {len(self.rules)}"

    def test_rules_have_required_fields(self):
        required = {"rule", "desc", "condition", "output", "priority"}
        for i, rule in enumerate(self.rules):
            missing = required - set(rule.keys())
            assert not missing, \
                f"Rule {i} ('{rule.get('rule', 'unnamed')}') missing fields: {missing}"

    def test_valid_priorities(self):
        for rule in self.rules:
            pri = rule.get("priority", "")
            assert pri in VALID_FALCO_PRIORITIES, \
                f"Rule '{rule.get('rule')}' has invalid priority '{pri}'"

    def test_rules_have_tags(self):
        for rule in self.rules:
            tags = rule.get("tags", [])
            assert isinstance(tags, list) and len(tags) > 0, \
                f"Rule '{rule.get('rule')}' must have non-empty tags list"

    def test_coverage_privilege_escalation(self):
        """At least one rule should detect RBAC-based privilege escalation."""
        conditions = " ".join(r.get("condition", "") for r in self.rules).lower()
        rule_names = " ".join(r.get("rule", "") for r in self.rules).lower()
        combined = conditions + " " + rule_names
        assert ("clusterrolebinding" in combined or "cluster-admin" in combined
                or "privilege" in combined or "rbac" in combined
                or "rolebinding" in combined), \
            "Must have a rule covering RBAC privilege escalation"

    def test_coverage_secret_access(self):
        """At least one rule should detect suspicious secret access."""
        conditions = " ".join(r.get("condition", "") for r in self.rules).lower()
        rule_names = " ".join(r.get("rule", "") for r in self.rules).lower()
        combined = conditions + " " + rule_names
        assert "secret" in combined, \
            "Must have a rule covering secret access/exfiltration"

    def test_coverage_pod_creation(self):
        """At least one rule should detect dangerous pod creation."""
        conditions = " ".join(r.get("condition", "") for r in self.rules).lower()
        rule_names = " ".join(r.get("rule", "") for r in self.rules).lower()
        combined = conditions + " " + rule_names
        assert ("pod" in combined and ("privileged" in combined or "host" in combined)), \
            "Must have a rule covering privileged/host-access pod creation"

    def test_coverage_exec(self):
        """At least one rule should detect exec into pods."""
        all_text = " ".join(flatten_str(self.rules)).lower()
        assert "exec" in all_text, \
            "Must have a rule covering pod exec operations"

    def test_conditions_use_ka_fields(self):
        """Detection rules should use ka.* field notation for k8s audit events."""
        conditions = " ".join(r.get("condition", "") for r in self.rules)
        outputs = " ".join(r.get("output", "") for r in self.rules)
        combined = conditions + " " + outputs
        assert "ka." in combined, \
            "Detection rules should use ka.* field notation for k8s audit fields"


# ============================================================
# AUDIT POLICY TESTS
# ============================================================

class TestAuditPolicy:
    """Validate the Kubernetes audit policy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        raw = load_yaml("audit_policy.yaml")
        if isinstance(raw, list):
            # Multi-doc: find the Policy document
            self.policy = None
            for doc in raw:
                if isinstance(doc, dict) and doc.get("kind") == "Policy":
                    self.policy = doc
                    break
            if self.policy is None and len(raw) > 0:
                self.policy = raw[0] if isinstance(raw[0], dict) else {}
        else:
            self.policy = raw

    def test_api_version(self):
        assert self.policy.get("apiVersion") == "audit.k8s.io/v1", \
            f"apiVersion must be 'audit.k8s.io/v1', got '{self.policy.get('apiVersion')}'"

    def test_kind(self):
        assert self.policy.get("kind") == "Policy", \
            f"kind must be 'Policy', got '{self.policy.get('kind')}'"

    def test_has_rules(self):
        rules = self.policy.get("rules", [])
        assert isinstance(rules, list) and len(rules) >= 4, \
            f"Policy must have at least 4 rules, found {len(self.policy.get('rules', []))}"

    def test_valid_levels(self):
        valid_levels = {"None", "Metadata", "Request", "RequestResponse"}
        for i, rule in enumerate(self.policy.get("rules", [])):
            level = rule.get("level", "")
            assert level in valid_levels, \
                f"Rule {i} has invalid level '{level}'. Must be one of {valid_levels}"

    def test_covers_rbac_resources(self):
        """Policy must cover RBAC resources."""
        all_resources = []
        for rule in self.policy.get("rules", []):
            for rg in rule.get("resources", []):
                all_resources.extend(rg.get("resources", []))
        all_text = " ".join(all_resources).lower()
        rbac_covered = ("clusterrolebindings" in all_text or "rolebindings" in all_text
                        or "clusterroles" in all_text or "roles" in all_text)
        assert rbac_covered, "Audit policy must cover RBAC resources"

    def test_covers_secrets(self):
        """Policy must cover secrets."""
        all_resources = []
        for rule in self.policy.get("rules", []):
            for rg in rule.get("resources", []):
                all_resources.extend(rg.get("resources", []))
        assert "secrets" in " ".join(all_resources).lower(), \
            "Audit policy must cover secrets"

    def test_covers_pods(self):
        """Policy must cover pods."""
        all_resources = []
        for rule in self.policy.get("rules", []):
            for rg in rule.get("resources", []):
                all_resources.extend(rg.get("resources", []))
        assert "pods" in " ".join(all_resources).lower(), \
            "Audit policy must cover pods"

    def test_covers_exec_subresource(self):
        """Policy must specifically cover pods/exec subresource."""
        all_text = " ".join(flatten_str(self.policy)).lower()
        assert "exec" in all_text, \
            "Audit policy must cover pods/exec subresource"

    def test_has_requestresponse_level(self):
        """At least one rule should use RequestResponse level for high-value events."""
        levels = {rule.get("level") for rule in self.policy.get("rules", [])}
        assert "RequestResponse" in levels, \
            "Must have at least one rule at RequestResponse level"

    def test_has_metadata_level(self):
        """At least one rule should use Metadata level."""
        levels = {rule.get("level") for rule in self.policy.get("rules", [])}
        assert "Metadata" in levels, \
            "Must have at least one rule at Metadata level"

    def test_rbac_at_high_level(self):
        """RBAC resources should be logged at Request or RequestResponse level."""
        for rule in self.policy.get("rules", []):
            resources_text = " ".join(flatten_str(rule.get("resources", []))).lower()
            if "clusterrolebinding" in resources_text or "rolebinding" in resources_text:
                level = rule.get("level", "")
                assert level in ("Request", "RequestResponse"), \
                    f"RBAC binding resources should be at Request/RequestResponse level, got '{level}'"
                return
        # If we get here, RBAC resources weren't found (caught by other tests)
