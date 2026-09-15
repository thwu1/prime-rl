"""
Tests for Kubernetes Security Incident Response task.

Validates four deliverables:
1. Incident report (JSON) - correct attack chain identification
2. OPA admission policy (Rego) - correct deny/allow decisions
3. Falco detection rules (YAML) - correct rule structure and coverage
4. Kubernetes audit policy (YAML) - correct levels and resource targeting
"""


import json
import os
import subprocess
import tempfile

import pytest
import yaml


# ============================================================
# Test Group 1: Incident Report
# ============================================================

class TestIncidentReport:
    @pytest.fixture(autouse=True)
    def load_report(self):
        path = "/app/analysis/incident-report.json"
        assert os.path.exists(path), f"Incident report not found at {path}"
        with open(path) as f:
            self.report = json.load(f)

    def test_has_compromised_identity(self):
        assert "compromised_identity" in self.report

    def test_compromised_identity_name(self):
        identity = self.report["compromised_identity"]
        assert identity.get("name") == "frontend-sa", (
            f"Expected compromised identity 'frontend-sa', got '{identity.get('name')}'"
        )

    def test_compromised_identity_namespace(self):
        identity = self.report["compromised_identity"]
        assert identity.get("namespace") == "webapp", (
            f"Expected namespace 'webapp', got '{identity.get('namespace')}'"
        )

    def test_affected_namespaces_contains_required(self):
        namespaces = set(self.report.get("affected_namespaces", []))
        required = {"webapp", "kube-system", "payment"}
        missing = required - namespaces
        assert not missing, f"Missing affected namespaces: {missing}"

    def test_attack_chain_minimum_length(self):
        chain = self.report.get("attack_chain", [])
        assert len(chain) >= 5, (
            f"Attack chain should have at least 5 steps, found {len(chain)}"
        )

    def test_attack_chain_includes_privilege_escalation(self):
        chain = self.report.get("attack_chain", [])
        all_text = " ".join(
            f"{s.get('tactic', '')} {s.get('description', '')}".lower()
            for s in chain
        )
        keywords = [
            "privilege escalation", "privesc", "escalat",
            "cluster-admin", "clusterrolebinding"
        ]
        assert any(kw in all_text for kw in keywords), (
            "Attack chain must include a privilege escalation step"
        )

    def test_attack_chain_includes_persistence(self):
        chain = self.report.get("attack_chain", [])
        all_text = " ".join(
            f"{s.get('tactic', '')} {s.get('description', '')}".lower()
            for s in chain
        )
        keywords = [
            "persistence", "backdoor", "backup-controller",
            "new service account", "serviceaccount"
        ]
        assert any(kw in all_text for kw in keywords), (
            "Attack chain must include a persistence step"
        )

    def test_severity_critical(self):
        assert self.report.get("severity", "").lower() == "critical", (
            f"Expected critical severity, got '{self.report.get('severity')}'"
        )

    def test_has_iocs(self):
        iocs = self.report.get("indicators_of_compromise", [])
        assert len(iocs) >= 1, "Report should include at least one IOC"


# ============================================================
# Test Group 2: OPA Admission Policy
# ============================================================

class TestOPAPolicy:
    POLICY_PATH = "/app/policies/admission.rego"

    @pytest.fixture(autouse=True)
    def check_exists(self):
        assert os.path.exists(self.POLICY_PATH), (
            f"OPA policy not found at {self.POLICY_PATH}"
        )

    def _eval_deny(self, input_obj):
        """Run opa eval and return the deny set (list of strings)."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(input_obj, f)
            input_path = f.name

        try:
            result = subprocess.run(
                [
                    "opa", "eval",
                    "-d", self.POLICY_PATH,
                    "-i", input_path,
                    "data.kubernetes.admission.deny",
                    "--format", "json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert result.returncode == 0, (
                f"opa eval failed: {result.stderr}"
            )
            output = json.loads(result.stdout)
            exprs = output.get("result", [{}])[0].get("expressions", [])
            if not exprs:
                return []
            value = exprs[0].get("value", [])
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                return list(value.values()) if value else []
            return [str(value)] if value else []
        finally:
            os.unlink(input_path)

    @staticmethod
    def _pod_input(name, namespace="default", labels=None,
                   containers=None, host_pid=False,
                   host_network=False, volumes=None):
        spec = {
            "containers": containers or [
                {"name": "app", "image": "registry.company.com/app:v1.0"}
            ]
        }
        if host_pid:
            spec["hostPID"] = True
        if host_network:
            spec["hostNetwork"] = True
        if volumes:
            spec["volumes"] = volumes
        return {
            "review": {
                "object": {
                    "apiVersion": "v1",
                    "kind": "Pod",
                    "metadata": {
                        "name": name,
                        "namespace": namespace,
                        "labels": labels or {},
                    },
                    "spec": spec,
                }
            }
        }

    def test_deny_privileged_container(self):
        inp = self._pod_input(
            "priv-pod",
            containers=[{
                "name": "app",
                "image": "registry.company.com/app:v1.0",
                "securityContext": {"privileged": True},
            }],
        )
        deny = self._eval_deny(inp)
        assert len(deny) > 0, "Privileged container should be denied"

    def test_deny_host_pid(self):
        inp = self._pod_input("hostpid-pod", host_pid=True)
        deny = self._eval_deny(inp)
        assert len(deny) > 0, "hostPID should be denied"

    def test_deny_host_network(self):
        inp = self._pod_input("hostnet-pod", host_network=True)
        deny = self._eval_deny(inp)
        assert len(deny) > 0, "hostNetwork should be denied"

    def test_deny_hostpath_root(self):
        inp = self._pod_input(
            "hp-root",
            volumes=[{"name": "root", "hostPath": {"path": "/"}}],
        )
        deny = self._eval_deny(inp)
        assert len(deny) > 0, "hostPath to / should be denied"

    def test_deny_hostpath_etcd(self):
        inp = self._pod_input(
            "hp-etcd",
            volumes=[{"name": "etcd", "hostPath": {"path": "/var/lib/etcd"}}],
        )
        deny = self._eval_deny(inp)
        assert len(deny) > 0, "hostPath to /var/lib/etcd should be denied"

    def test_deny_hostpath_docker_sock(self):
        inp = self._pod_input(
            "hp-docker",
            volumes=[{
                "name": "docker",
                "hostPath": {"path": "/var/run/docker.sock"},
            }],
        )
        deny = self._eval_deny(inp)
        assert len(deny) > 0, "hostPath to docker.sock should be denied"

    def test_allow_normal_pod(self):
        inp = self._pod_input(
            "good-pod",
            containers=[{
                "name": "app",
                "image": "registry.company.com/app:v1.2",
                "securityContext": {
                    "runAsNonRoot": True,
                    "readOnlyRootFilesystem": True,
                },
            }],
        )
        deny = self._eval_deny(inp)
        assert len(deny) == 0, f"Normal pod should be allowed, got: {deny}"

    def test_exempt_system_component(self):
        inp = self._pod_input(
            "kube-proxy-abc",
            namespace="kube-system",
            labels={"system-component": "true"},
            host_network=True,
            containers=[{
                "name": "kube-proxy",
                "image": "registry.k8s.io/kube-proxy:v1.29.0",
                "securityContext": {"privileged": True},
            }],
        )
        deny = self._eval_deny(inp)
        assert len(deny) == 0, (
            f"kube-system system-component should be exempt, got: {deny}"
        )


# ============================================================
# Test Group 3: Falco Detection Rules
# ============================================================

class TestFalcoRules:
    RULES_PATH = "/app/policies/falco_rules.yaml"

    @pytest.fixture(autouse=True)
    def load_rules(self):
        assert os.path.exists(self.RULES_PATH), (
            f"Falco rules not found at {self.RULES_PATH}"
        )
        with open(self.RULES_PATH) as f:
            self.raw = f.read()
        self.parsed = yaml.safe_load(self.raw)

    def _get_rules(self):
        if isinstance(self.parsed, list):
            return [r for r in self.parsed
                    if isinstance(r, dict) and "rule" in r]
        return []

    def test_minimum_rule_count(self):
        rules = self._get_rules()
        assert len(rules) >= 3, (
            f"Expected at least 3 Falco rules, found {len(rules)}"
        )

    def test_rules_have_required_fields(self):
        for rule in self._get_rules():
            name = rule.get("rule", "<unnamed>")
            for field in ("rule", "condition", "output", "priority"):
                assert field in rule, (
                    f"Rule '{name}' missing required field '{field}'"
                )

    def test_valid_priorities(self):
        valid = {
            "emergency", "alert", "critical", "error",
            "warning", "notice", "informational", "debug",
        }
        for rule in self._get_rules():
            p = rule.get("priority", "").lower()
            assert p in valid, (
                f"Rule '{rule.get('rule')}' has invalid priority '{p}'"
            )

    def test_has_privileged_container_rule(self):
        content = self.raw.lower()
        assert "privileged" in content, (
            "No rule detecting privileged containers"
        )

    def test_has_sensitive_file_rule(self):
        content = self.raw.lower()
        keywords = ["/etc/shadow", "sensitive", "etcd", "/etc/passwd"]
        assert any(kw in content for kw in keywords), (
            "No rule detecting sensitive file access"
        )

    def test_has_crypto_mining_rule(self):
        content = self.raw.lower()
        keywords = ["crypto", "mining", "xmrig", "xmr", "stratum", "miner"]
        assert any(kw in content for kw in keywords), (
            "No rule detecting cryptomining activity"
        )


# ============================================================
# Test Group 4: Kubernetes Audit Policy
# ============================================================

class TestAuditPolicy:
    POLICY_PATH = "/app/policies/audit-policy.yaml"

    @pytest.fixture(autouse=True)
    def load_policy(self):
        assert os.path.exists(self.POLICY_PATH), (
            f"Audit policy not found at {self.POLICY_PATH}"
        )
        with open(self.POLICY_PATH) as f:
            self.policy = yaml.safe_load(f)

    def test_api_version(self):
        assert self.policy.get("apiVersion") == "audit.k8s.io/v1"

    def test_kind(self):
        assert self.policy.get("kind") == "Policy"

    def test_minimum_rule_count(self):
        rules = self.policy.get("rules", [])
        assert len(rules) >= 3, (
            f"Expected at least 3 audit rules, found {len(rules)}"
        )

    def test_secrets_at_request_level_or_higher(self):
        high = {"Request", "RequestResponse"}
        for rule in self.policy.get("rules", []):
            for rg in rule.get("resources", []):
                if "secrets" in rg.get("resources", []):
                    if rule.get("level") in high:
                        return
        pytest.fail("Secrets must be logged at Request or RequestResponse level")

    def test_rbac_resources_logged(self):
        for rule in self.policy.get("rules", []):
            for rg in rule.get("resources", []):
                group = rg.get("group", "")
                res = rg.get("resources", [])
                rbac_group = "rbac" in group.lower()
                rbac_res = any(
                    r in res for r in [
                        "clusterrolebindings", "clusterroles",
                        "rolebindings", "roles",
                    ]
                )
                if rbac_group or rbac_res:
                    if rule.get("level") in {
                        "Request", "RequestResponse", "Metadata"
                    }:
                        return
        pytest.fail("RBAC resources must be logged in audit policy")

    def test_pods_logged(self):
        for rule in self.policy.get("rules", []):
            for rg in rule.get("resources", []):
                if "pods" in rg.get("resources", []):
                    if rule.get("level") in {
                        "Request", "RequestResponse", "Metadata"
                    }:
                        return
        pytest.fail("Pod operations must be logged in audit policy")
