
import json
import glob
import os
import subprocess
import pytest
import yaml


# ============================================================
# Helper: load files
# ============================================================

def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def load_yaml_docs(path):
    with open(path, "r") as f:
        return [d for d in yaml.safe_load_all(f) if d is not None]


# ============================================================
# Test Group 1: Attack Summary JSON
# ============================================================

class TestAttackSummary:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/attack_summary.json"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.data = load_json(self.path)

    def test_has_required_fields(self):
        for field in [
            "attack_timeline",
            "compromised_service_account",
            "compromised_secrets",
            "attacker_created_resources",
        ]:
            assert field in self.data, f"Missing field: {field}"

    def test_timeline_is_list_with_events(self):
        tl = self.data["attack_timeline"]
        assert isinstance(tl, list)
        assert len(tl) >= 7, f"Expected >= 7 attack events, got {len(tl)}"

    def test_timeline_chronological(self):
        tl = self.data["attack_timeline"]
        timestamps = [e["timestamp"] for e in tl]
        assert timestamps == sorted(timestamps), "Timeline not in chronological order"

    def test_timeline_event_fields(self):
        tl = self.data["attack_timeline"]
        for event in tl:
            assert "timestamp" in event, "Event missing 'timestamp'"
            assert "action" in event or "verb" in event, "Event missing 'action'/'verb'"
            assert "resource_type" in event or "resource" in event, "Event missing 'resource_type'/'resource'"

    def test_compromised_service_account(self):
        sa = self.data["compromised_service_account"]
        assert "webapp-sa" in sa, f"Expected 'webapp-sa' in SA, got: {sa}"

    def test_compromised_secrets_db_credentials(self):
        secrets = self.data["compromised_secrets"]
        secrets_str = json.dumps(secrets).lower()
        assert "db-credentials" in secrets_str, "Missing db-credentials in compromised secrets"

    def test_compromised_secrets_payment_key(self):
        secrets = self.data["compromised_secrets"]
        secrets_str = json.dumps(secrets).lower()
        assert "payment-gateway-key" in secrets_str, "Missing payment-gateway-key in compromised secrets"

    def test_attacker_created_clusterrolebinding(self):
        resources = json.dumps(self.data["attacker_created_resources"]).lower()
        assert (
            "clusterrolebinding" in resources
            or "system-controller-manager-extension" in resources
        ), "Missing attacker-created ClusterRoleBinding"

    def test_attacker_created_pod(self):
        resources = json.dumps(self.data["attacker_created_resources"]).lower()
        assert (
            "log-collector-node-agent" in resources
            or ("pod" in resources and "kube-system" in resources)
        ), "Missing attacker-created pod in kube-system"

    def test_attacker_created_daemonset(self):
        resources = json.dumps(self.data["attacker_created_resources"]).lower()
        assert (
            "node-health-monitor" in resources
            or ("daemonset" in resources and "monitoring" in resources)
        ), "Missing attacker-created DaemonSet in monitoring"

    def test_attacker_source_ip(self):
        data_str = json.dumps(self.data).lower()
        assert "10.244.1.8" in data_str, "Missing attacker source IP 10.244.1.8"

    def test_initial_vulnerability_mentioned(self):
        data_str = json.dumps(self.data).lower()
        assert (
            "wildcard" in data_str
            or "full-access" in data_str
            or "overly permissive" in data_str
            or "cluster-wide" in data_str
            or "clusterrole" in data_str
            or "privilege" in data_str
        ), "attack_summary must reference the RBAC vulnerability"


# ============================================================
# Test Group 2: RBAC Remediation
# ============================================================

class TestRBACRemediation:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/remediation/webapp-rbac.yaml"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.docs = load_yaml_docs(self.path)
        self.kinds = [d.get("kind") for d in self.docs]

    def test_contains_role(self):
        assert "Role" in self.kinds, "Must contain a namespace-scoped Role"

    def test_no_cluster_role(self):
        assert "ClusterRole" not in self.kinds, (
            "Must use Role (namespace-scoped), not ClusterRole"
        )

    def test_contains_rolebinding(self):
        assert "RoleBinding" in self.kinds, "Must contain a RoleBinding"

    def test_role_namespace_is_ecommerce(self):
        roles = [d for d in self.docs if d.get("kind") == "Role"]
        for role in roles:
            ns = role.get("metadata", {}).get("namespace", "")
            assert ns == "ecommerce", f"Role namespace must be 'ecommerce', got '{ns}'"

    def test_no_wildcard_verbs(self):
        roles = [d for d in self.docs if d.get("kind") == "Role"]
        for role in roles:
            for rule in role.get("rules", []):
                assert "*" not in rule.get("verbs", []), (
                    "Role must not have wildcard verbs"
                )

    def test_no_wildcard_resources(self):
        roles = [d for d in self.docs if d.get("kind") == "Role"]
        for role in roles:
            for rule in role.get("rules", []):
                assert "*" not in rule.get("resources", []), (
                    "Role must not have wildcard resources"
                )

    def test_no_secrets_access(self):
        roles = [d for d in self.docs if d.get("kind") == "Role"]
        for role in roles:
            for rule in role.get("rules", []):
                resources = rule.get("resources", [])
                assert "secrets" not in resources, (
                    "Webapp Role must not grant secrets access"
                )

    def test_rolebinding_references_webapp_sa(self):
        bindings = [d for d in self.docs if d.get("kind") == "RoleBinding"]
        for rb in bindings:
            subjects = rb.get("subjects", [])
            sa_names = [s.get("name", "") for s in subjects]
            assert "webapp-sa" in sa_names, (
                "RoleBinding must reference webapp-sa ServiceAccount"
            )


# ============================================================
# Test Group 3: Audit Policy
# ============================================================

class TestAuditPolicy:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/remediation/audit-policy.yaml"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.docs = load_yaml_docs(self.path)
        self.policy = self.docs[0]

    def test_api_version(self):
        assert self.policy.get("apiVersion") == "audit.k8s.io/v1", (
            "Audit policy must use apiVersion audit.k8s.io/v1"
        )

    def test_kind(self):
        assert self.policy.get("kind") == "Policy", (
            "Audit policy must have kind: Policy"
        )

    def test_has_rules(self):
        rules = self.policy.get("rules", [])
        assert isinstance(rules, list) and len(rules) >= 2, (
            "Audit policy must have at least 2 rules"
        )

    def test_covers_secrets(self):
        rules_str = json.dumps(self.policy.get("rules", [])).lower()
        assert "secrets" in rules_str, "Audit policy must cover secrets"

    def test_covers_rbac(self):
        rules_str = json.dumps(self.policy.get("rules", [])).lower()
        assert (
            "clusterrolebinding" in rules_str
            or "clusterrole" in rules_str
            or "rolebinding" in rules_str
            or "role" in rules_str
            or "rbac" in rules_str
        ), "Audit policy must cover RBAC resources"

    def test_uses_request_response_level(self):
        rules = self.policy.get("rules", [])
        levels = [r.get("level", "").lower() for r in rules]
        assert any(
            "requestresponse" in l.replace(" ", "").replace("_", "").replace("-", "")
            for l in levels
        ), "Audit policy should use RequestResponse level for high-risk resources"


# ============================================================
# Test Group 4: Network Policy
# ============================================================

class TestNetworkPolicy:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/remediation/network-policy.yaml"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.docs = load_yaml_docs(self.path)

    def test_has_network_policy(self):
        kinds = [d.get("kind") for d in self.docs]
        assert "NetworkPolicy" in kinds, "Must contain a NetworkPolicy resource"

    def test_api_version(self):
        nps = [d for d in self.docs if d.get("kind") == "NetworkPolicy"]
        for np_doc in nps:
            assert np_doc.get("apiVersion") == "networking.k8s.io/v1", (
                "NetworkPolicy must use apiVersion networking.k8s.io/v1"
            )

    def test_namespace_ecommerce(self):
        nps = [d for d in self.docs if d.get("kind") == "NetworkPolicy"]
        namespaces = [np_doc.get("metadata", {}).get("namespace", "") for np_doc in nps]
        assert "ecommerce" in namespaces, (
            "At least one NetworkPolicy must be in ecommerce namespace"
        )

    def test_has_ingress_policy_type(self):
        nps = [d for d in self.docs if d.get("kind") == "NetworkPolicy"]
        all_types = []
        for np_doc in nps:
            all_types.extend(np_doc.get("spec", {}).get("policyTypes", []))
        assert "Ingress" in all_types, "NetworkPolicy must include Ingress policyType"

    def test_has_egress_policy_type(self):
        nps = [d for d in self.docs if d.get("kind") == "NetworkPolicy"]
        all_types = []
        for np_doc in nps:
            all_types.extend(np_doc.get("spec", {}).get("policyTypes", []))
        assert "Egress" in all_types, "NetworkPolicy must include Egress policyType"

    def test_has_pod_selector(self):
        nps = [d for d in self.docs if d.get("kind") == "NetworkPolicy"]
        for np_doc in nps:
            assert "podSelector" in np_doc.get("spec", {}), (
                "NetworkPolicy must have a podSelector"
            )


# ============================================================
# Test Group 5: Falco Rules
# ============================================================

class TestFalcoRules:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/remediation/falco-rules.yaml"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.docs = load_yaml_docs(self.path)
        self.rules = []
        for d in self.docs:
            if d and isinstance(d, dict) and "rule" in d:
                self.rules.append(d)
            elif d and isinstance(d, list):
                for item in d:
                    if isinstance(item, dict) and "rule" in item:
                        self.rules.append(item)

    def test_has_at_least_two_rules(self):
        assert len(self.rules) >= 2, (
            f"Must have at least 2 Falco rules, found {len(self.rules)}"
        )

    def test_rules_have_desc(self):
        for rule in self.rules:
            assert "desc" in rule, f"Falco rule '{rule.get('rule')}' missing 'desc'"

    def test_rules_have_condition(self):
        for rule in self.rules:
            assert "condition" in rule, (
                f"Falco rule '{rule.get('rule')}' missing 'condition'"
            )

    def test_rules_have_output(self):
        for rule in self.rules:
            assert "output" in rule, (
                f"Falco rule '{rule.get('rule')}' missing 'output'"
            )

    def test_rules_have_priority(self):
        for rule in self.rules:
            assert "priority" in rule, (
                f"Falco rule '{rule.get('rule')}' missing 'priority'"
            )
            valid_priorities = [
                "EMERGENCY", "ALERT", "CRITICAL", "ERROR",
                "WARNING", "NOTICE", "INFORMATIONAL", "DEBUG",
                "emergency", "alert", "critical", "error",
                "warning", "notice", "informational", "debug",
            ]
            assert rule["priority"] in valid_priorities, (
                f"Invalid priority '{rule['priority']}' in rule '{rule.get('rule')}'"
            )

    def test_rules_cover_secret_access(self):
        all_conditions = " ".join(
            str(r.get("condition", "")) + " " + str(r.get("desc", "")) + " " + str(r.get("rule", ""))
            for r in self.rules
        ).lower()
        assert (
            "secret" in all_conditions
            or "credential" in all_conditions
            or "sensitive" in all_conditions
        ), "Falco rules must include detection of secret/credential access"

    def test_rules_cover_rbac_escalation(self):
        all_text = " ".join(
            str(r.get("condition", "")) + " " + str(r.get("desc", "")) + " " + str(r.get("rule", ""))
            for r in self.rules
        ).lower()
        assert (
            "clusterrolebinding" in all_text
            or "cluster-admin" in all_text
            or "privilege" in all_text
            or "escalat" in all_text
            or "rbac" in all_text
            or "role" in all_text
        ), "Falco rules must include detection of RBAC privilege escalation"


# ============================================================
# Test Group 6: Trivy Configuration Scan
# ============================================================

class TestTrivyScan:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/trivy-scan/current-state.json"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.data = load_json(self.path)

    def test_is_valid_trivy_output(self):
        """Verify the output has trivy-specific JSON structure"""
        data_str = json.dumps(self.data).lower()
        assert (
            "results" in data_str
            or "misconfigurations" in data_str
            or "misconf" in data_str
            or "target" in data_str
        ), "Output must be valid trivy JSON with Results/Misconfigurations"

    def test_scanned_cluster_state_files(self):
        """Verify trivy scanned the cluster state directory"""
        data_str = json.dumps(self.data)
        assert (
            "current-rbac" in data_str
            or "current-workloads" in data_str
            or "cluster-state" in data_str
        ), "Trivy scan must reference cluster-state files"

    def test_found_misconfigurations(self):
        """The insecure cluster state should produce findings"""
        data_str = json.dumps(self.data)
        # Trivy should find misconfigurations - the output should be non-trivial
        assert len(data_str) > 500, (
            "Trivy scan output is too small - expected misconfigurations in insecure cluster state"
        )

    def test_results_contain_severity(self):
        """Findings should include severity information"""
        data_str = json.dumps(self.data).upper()
        assert (
            "HIGH" in data_str
            or "CRITICAL" in data_str
            or "MEDIUM" in data_str
            or "LOW" in data_str
        ), "Trivy findings must include severity levels"


# ============================================================
# Test Group 7: OPA/Rego Policies
# ============================================================

class TestOPAPolicies:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.policy_dir = "/app/results/policies/"
        assert os.path.isdir(self.policy_dir), f"Missing policies directory {self.policy_dir}"
        self.rego_files = glob.glob(os.path.join(self.policy_dir, "*.rego"))

    def test_has_rego_files(self):
        assert len(self.rego_files) >= 1, "Must have at least one .rego policy file"

    def test_rego_files_declare_package(self):
        for f in self.rego_files:
            with open(f) as fp:
                content = fp.read()
            assert "package" in content, f"{os.path.basename(f)} must declare a Rego package"

    def test_rego_files_have_deny_rules(self):
        all_content = ""
        for f in self.rego_files:
            with open(f) as fp:
                all_content += fp.read()
        assert (
            "deny" in all_content or "violation" in all_content
        ), "OPA policies must contain deny or violation rules"

    def test_policies_cover_rbac_wildcards(self):
        """Policies must check for wildcard permissions in RBAC"""
        all_content = ""
        for f in self.rego_files:
            with open(f) as fp:
                all_content += fp.read()
        content_lower = all_content.lower()
        assert (
            '"*"' in all_content
            or "wildcard" in content_lower
            or ("verbs" in content_lower and "resources" in content_lower)
        ), "OPA policies must check for RBAC wildcard permissions"

    def test_policies_cover_network_policy(self):
        """Policies must validate NetworkPolicy policyTypes"""
        all_content = ""
        for f in self.rego_files:
            with open(f) as fp:
                all_content += fp.read()
        content_lower = all_content.lower()
        assert (
            "networkpolicy" in content_lower
            or "policytypes" in content_lower
            or ("ingress" in content_lower and "egress" in content_lower)
        ), "OPA policies must validate NetworkPolicy requirements"

    def test_policies_cover_audit_secrets(self):
        """Policies must validate audit policy covers secrets"""
        all_content = ""
        for f in self.rego_files:
            with open(f) as fp:
                all_content += fp.read()
        content_lower = all_content.lower()
        assert (
            "requestresponse" in content_lower
            or ("secrets" in content_lower and "level" in content_lower)
            or ("audit" in content_lower and "secrets" in content_lower)
        ), "OPA policies must validate audit policy for secrets"


# ============================================================
# Test Group 8: Conftest Results
# ============================================================

class TestConftestResults:

    @pytest.fixture(autouse=True)
    def setup(self):
        self.path = "/app/results/conftest-results.json"
        assert os.path.exists(self.path), f"Missing {self.path}"
        self.data = load_json(self.path)

    def test_is_valid_conftest_output(self):
        """Verify conftest JSON output structure"""
        assert isinstance(self.data, list), "Conftest output must be a JSON array"
        assert len(self.data) >= 1, "Conftest must have tested at least one file"

    def test_no_failures(self):
        """All remediation files must pass conftest validation"""
        for result in self.data:
            failures = result.get("failures") or []
            assert len(failures) == 0, (
                f"Conftest failures in {result.get('filename', 'unknown')}: "
                f"{json.dumps(failures, indent=2)}"
            )

    def test_results_reference_remediation_files(self):
        """Conftest must have tested remediation YAML files"""
        all_filenames = json.dumps([r.get("filename", "") for r in self.data]).lower()
        assert (
            "rbac" in all_filenames
            or "audit" in all_filenames
            or "network" in all_filenames
            or "remediation" in all_filenames
        ), "Conftest results must reference remediation files"


# ============================================================
# Test Group 9: Live Conftest Validation
# ============================================================

class TestConftestLiveValidation:
    """Actually run conftest to verify policies work against remediation"""

    def test_conftest_validates_rbac(self):
        if not os.path.exists("/usr/local/bin/conftest"):
            pytest.skip("conftest not installed")
        if not os.path.isdir("/app/results/policies/"):
            pytest.skip("No policies directory")
        if not os.path.exists("/app/results/remediation/webapp-rbac.yaml"):
            pytest.skip("No RBAC remediation file")

        result = subprocess.run(
            ["/usr/local/bin/conftest", "test",
             "-p", "/app/results/policies/",
             "/app/results/remediation/webapp-rbac.yaml"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"conftest failed on webapp-rbac.yaml:\n{result.stdout}\n{result.stderr}"
        )

    def test_conftest_validates_audit_policy(self):
        if not os.path.exists("/usr/local/bin/conftest"):
            pytest.skip("conftest not installed")
        if not os.path.isdir("/app/results/policies/"):
            pytest.skip("No policies directory")
        if not os.path.exists("/app/results/remediation/audit-policy.yaml"):
            pytest.skip("No audit policy file")

        result = subprocess.run(
            ["/usr/local/bin/conftest", "test",
             "-p", "/app/results/policies/",
             "/app/results/remediation/audit-policy.yaml"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"conftest failed on audit-policy.yaml:\n{result.stdout}\n{result.stderr}"
        )

    def test_conftest_validates_network_policy(self):
        if not os.path.exists("/usr/local/bin/conftest"):
            pytest.skip("conftest not installed")
        if not os.path.isdir("/app/results/policies/"):
            pytest.skip("No policies directory")
        if not os.path.exists("/app/results/remediation/network-policy.yaml"):
            pytest.skip("No network policy file")

        result = subprocess.run(
            ["/usr/local/bin/conftest", "test",
             "-p", "/app/results/policies/",
             "/app/results/remediation/network-policy.yaml"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"conftest failed on network-policy.yaml:\n{result.stdout}\n{result.stderr}"
        )
