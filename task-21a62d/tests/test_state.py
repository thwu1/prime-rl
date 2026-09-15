
import json
import os
import pytest
import yaml


OUTPUT_DIR = "/app/output"


class TestIncidentReport:
    """Validate the forensics incident report."""

    @pytest.fixture(autouse=True)
    def load_report(self):
        path = os.path.join(OUTPUT_DIR, "incident-report.json")
        assert os.path.exists(path), "incident-report.json not found in /app/output/"
        with open(path) as f:
            self.report = json.load(f)
        self.content = json.dumps(self.report).lower()

    def test_valid_json_structure(self):
        """Report must be a valid JSON object (dict) or list."""
        assert isinstance(self.report, (dict, list)), "Report must be a JSON object or array"

    def test_compromised_identity_cibot(self):
        """Must identify ci-bot as the compromised service account."""
        assert "ci-bot" in self.content, (
            "Report must identify 'ci-bot' as the compromised service account"
        )

    def test_compromised_identity_namespace(self):
        """Must associate ci-bot with the build-system namespace."""
        assert "build-system" in self.content, (
            "Report must reference 'build-system' namespace for the compromised identity"
        )

    def test_exfiltrated_secret_registry_credentials(self):
        """Must identify registry-credentials as exfiltrated."""
        assert "registry-credentials" in self.content, (
            "Report must identify 'registry-credentials' secret"
        )

    def test_exfiltrated_secret_database_credentials(self):
        """Must identify database-credentials as exfiltrated."""
        assert "database-credentials" in self.content, (
            "Report must identify 'database-credentials' secret"
        )

    def test_exfiltrated_secret_api_keys(self):
        """Must identify api-keys as exfiltrated."""
        assert "api-keys" in self.content, (
            "Report must identify 'api-keys' secret"
        )

    def test_exfiltrated_secret_tls_cert(self):
        """Must identify tls-cert as exfiltrated."""
        assert "tls-cert" in self.content, (
            "Report must identify 'tls-cert' secret"
        )

    def test_privilege_escalation_detected(self):
        """Must identify the ClusterRoleBinding privilege escalation."""
        has_crb = "clusterrolebinding" in self.content
        has_cluster_admin = "cluster-admin" in self.content
        has_priv_esc = "privilege" in self.content or "escalat" in self.content
        assert (has_crb and has_cluster_admin) or has_priv_esc, (
            "Report must reference ClusterRoleBinding to cluster-admin or privilege escalation"
        )

    def test_lateral_movement_exec(self):
        """Must identify the pod exec lateral movement."""
        has_exec = "exec" in self.content
        has_pod = (
            "api-server-7f8d9c6b5-x2k4m" in self.content
            or ("api-server" in self.content and "production" in self.content)
        )
        assert has_exec and has_pod, (
            "Report must reference pod exec into api-server in production"
        )

    def test_persistence_debug_agent(self):
        """Must identify the debug-agent SA as a persistence mechanism."""
        assert "debug-agent" in self.content, (
            "Report must identify 'debug-agent' service account as persistence"
        )

    def test_persistence_kube_system(self):
        """Must associate debug-agent with kube-system namespace."""
        assert "kube-system" in self.content, (
            "Report must reference kube-system namespace for persistence mechanism"
        )

    def test_mitre_techniques_present(self):
        """Must include at least 3 relevant MITRE ATT&CK technique IDs."""
        content_upper = json.dumps(self.report).upper()
        relevant_techniques = [
            "T1078",   # Valid Accounts
            "T1552",   # Unsecured Credentials
            "T1098",   # Account Manipulation
            "T1609",   # Container Administration Command
            "T1053",   # Scheduled Task/Job
            "T1543",   # Create or Modify System Process
            "T1136",   # Create Account
            "T1087",   # Account Discovery
            "T1069",   # Permission Groups Discovery
            "T1530",   # Data from Cloud Storage Object
            "T1528",   # Steal Application Access Token
            "T1550",   # Use Alternate Authentication Material
            "T1548",   # Abuse Elevation Control Mechanism
            "T1068",   # Exploitation for Privilege Escalation
            "T1059",   # Command and Scripting Interpreter
            "T1105",   # Ingress Tool Transfer
            "T1046",   # Network Service Discovery
            "T1071",   # Application Layer Protocol
        ]
        found = [t for t in relevant_techniques if t in content_upper]
        assert len(found) >= 3, (
            f"Report must reference at least 3 MITRE ATT&CK technique IDs. "
            f"Found: {found}"
        )

    def test_does_not_flag_admin_as_attacker(self):
        """Should not incorrectly identify admin@company.com as the primary attacker."""
        cibot_count = self.content.count("ci-bot")
        assert cibot_count >= 2, (
            "ci-bot should be mentioned multiple times as the compromised identity"
        )

    def test_root_cause_rbac_vulnerability(self):
        """Must identify the pipeline-runner ClusterRole misconfiguration as root cause."""
        has_pipeline_runner = "pipeline-runner" in self.content
        root_cause_terms = [
            "root cause", "misconfigur", "overprivileg", "over-privileg",
            "excessive", "should not", "vulnerabilit", "improperly",
            "least privilege", "unintended", "too permissive", "overly permissive",
            "rbac misconfiguration", "rbac vulnerability", "rbac flaw",
            "incorrectly granted", "should not have", "violated",
        ]
        has_root_cause = any(term in self.content for term in root_cause_terms)
        assert has_pipeline_runner and has_root_cause, (
            "Report must identify the pipeline-runner ClusterRole as the root cause "
            "RBAC vulnerability (e.g., overprivileged, misconfigured, excessive permissions)"
        )

    def test_remediation_present(self):
        """Must include remediation or recommendations."""
        remediation_terms = [
            "remediat", "recommend", "mitigat", "harden",
            "action item", "next step", "response action",
            "should be", "must be", "rotat", "revok", "delet",
        ]
        has_remediation = any(term in self.content for term in remediation_terms)
        assert has_remediation, (
            "Report must include remediation recommendations or response actions"
        )

    def test_cross_source_correlation(self):
        """Must correlate findings from both audit logs and runtime (Falco) evidence."""
        audit_indicators = ["audit" in self.content or "api server" in self.content or "apiserver" in self.content]
        runtime_indicators = [
            "falco" in self.content
            or "runtime" in self.content
            or "shell" in self.content
            or "/etc/shadow" in self.content
            or "package" in self.content
        ]
        assert any(audit_indicators) and any(runtime_indicators), (
            "Report must correlate findings from both API audit logs and runtime/Falco evidence"
        )

    def test_source_ip_anomaly_detected(self):
        """Must detect and document the source IP anomaly in ci-bot's session."""
        ip_terms = [
            "10.10.99.5", "source ip", "ip change", "ip address",
            "external ip", "token theft", "token exfiltrat",
            "credential theft", "stolen token", "different ip",
            "outside the cluster", "outside the pod",
            "unexpected ip", "unknown ip", "anomalous ip",
            "suspicious ip", "network anomal", "ip anomal",
            "multiple.*ip", "external.*access", "ip inconsisten",
        ]
        has_ip_anomaly = any(term in self.content for term in ip_terms)
        assert has_ip_anomaly, (
            "Report must detect and document the source IP anomaly "
            "(ci-bot's IP changed from pod network 10.244.1.15 to external "
            "IP 10.10.99.5 during persistence operations, indicating token theft)"
        )

    def test_deploy_bot_not_primary_attacker(self):
        """deploy-bot activity was authorized — must not be flagged as the compromised identity."""
        # ci-bot must be mentioned significantly more than deploy-bot as the attacker
        cibot_mentions = self.content.count("ci-bot")
        # The report may mention deploy-bot as excluded/authorized, but ci-bot must dominate
        assert cibot_mentions >= 4, (
            "ci-bot must be prominently identified as the compromised identity "
            "(mentioned at least 4 times). deploy-bot was authorized and should "
            "not overshadow ci-bot in the report."
        )

    def test_evidence_integrity_acknowledged(self):
        """Must acknowledge evidence integrity issues (corrupted audit log entries)."""
        integrity_terms = [
            "corrupt", "malform", "truncat", "parse error", "parse fail",
            "invalid json", "integrity", "corrupted", "damaged",
            "incomplete", "missing entr", "log rotation", "syslog",
            "data quality", "evidence quality", "broken entr",
            "concatenat", "recover",
        ]
        has_integrity = any(term in self.content for term in integrity_terms)
        assert has_integrity, (
            "Report must acknowledge and document evidence integrity issues "
            "(the audit log contains malformed/truncated entries that required "
            "robust parsing)"
        )


class TestAuditPolicy:
    """Validate the hardened Kubernetes audit policy."""

    @pytest.fixture(autouse=True)
    def load_policy(self):
        path = os.path.join(OUTPUT_DIR, "hardened-audit-policy.yaml")
        assert os.path.exists(path), "hardened-audit-policy.yaml not found in /app/output/"
        with open(path) as f:
            self.policy = yaml.safe_load(f)

    def test_valid_api_version(self):
        assert self.policy.get("apiVersion") == "audit.k8s.io/v1", (
            "Audit policy must have apiVersion: audit.k8s.io/v1"
        )

    def test_valid_kind(self):
        assert self.policy.get("kind") == "Policy", (
            "Audit policy must have kind: Policy"
        )

    def test_has_rules(self):
        rules = self.policy.get("rules", [])
        assert len(rules) >= 4, (
            f"Audit policy must have at least 4 rules, found {len(rules)}"
        )

    def test_all_levels_valid(self):
        valid_levels = {"None", "Metadata", "Request", "RequestResponse"}
        for i, rule in enumerate(self.policy.get("rules", [])):
            level = rule.get("level")
            assert level in valid_levels, (
                f"Rule {i} has invalid level '{level}'. "
                f"Valid levels: {valid_levels}"
            )

    def test_secrets_rule_exists(self):
        """Must have a rule that logs secrets access at Request or higher."""
        rules = self.policy.get("rules", [])
        found = False
        for rule in rules:
            resources = rule.get("resources", [])
            resource_names = set()
            for r in resources:
                if isinstance(r, dict):
                    resource_names.update(r.get("resources", []))
            if "secrets" in resource_names:
                level = rule.get("level", "")
                if level in ("RequestResponse", "Request", "Metadata"):
                    found = True
                    break
        assert found, (
            "Audit policy must have a rule logging secrets access "
            "at Metadata, Request, or RequestResponse level"
        )

    def test_rbac_rule_exists(self):
        """Must have a rule logging RBAC resource mutations."""
        rules = self.policy.get("rules", [])
        rbac_resources = {
            "clusterrolebindings", "rolebindings", "clusterroles", "roles"
        }
        found = False
        for rule in rules:
            resources = rule.get("resources", [])
            resource_names = set()
            for r in resources:
                if isinstance(r, dict):
                    resource_names.update(r.get("resources", []))
            if resource_names & rbac_resources:
                level = rule.get("level", "")
                if level in ("RequestResponse", "Request", "Metadata"):
                    found = True
                    break
        assert found, (
            "Audit policy must have a rule logging RBAC resources "
            "(clusterrolebindings, rolebindings, clusterroles, roles)"
        )

    def test_exec_rule_exists(self):
        """Must have a rule for pod exec/attach operations."""
        rules = self.policy.get("rules", [])
        found = False
        for rule in rules:
            resources = rule.get("resources", [])
            for r in resources:
                if isinstance(r, dict):
                    res_names = r.get("resources", [])
                    if "pods/exec" in res_names or "pods/attach" in res_names:
                        level = rule.get("level", "")
                        if level in ("RequestResponse", "Request", "Metadata"):
                            found = True
                            break
            if found:
                break
        assert found, (
            "Audit policy must have a rule for pods/exec and/or pods/attach"
        )

    def test_noise_reduction_present(self):
        """Policy must include noise reduction (None level rules)."""
        rules = self.policy.get("rules", [])
        has_none = any(r.get("level") == "None" for r in rules)
        assert has_none, (
            "Audit policy must have at least one rule with level: None "
            "for noise reduction"
        )

    def test_catch_all_rule(self):
        """Last rule should be a catch-all (no resource/namespace filters)."""
        rules = self.policy.get("rules", [])
        assert len(rules) > 0
        last_rule = rules[-1]
        has_no_resources = not last_rule.get("resources")
        has_no_namespaces = not last_rule.get("namespaces")
        has_level = "level" in last_rule
        assert has_level and (has_no_resources or has_no_namespaces), (
            "Last rule should be a catch-all (no specific resource/namespace filter)"
        )

    def test_serviceaccount_coverage(self):
        """Must have a rule covering serviceaccount lifecycle or token operations."""
        rules = self.policy.get("rules", [])
        found = False
        for rule in rules:
            resources = rule.get("resources", [])
            resource_names = set()
            for r in resources:
                if isinstance(r, dict):
                    resource_names.update(r.get("resources", []))
            if resource_names & {"serviceaccounts", "serviceaccounts/token"}:
                level = rule.get("level", "")
                if level in ("RequestResponse", "Request", "Metadata"):
                    found = True
                    break
        assert found, (
            "Audit policy must have a rule covering serviceaccount "
            "lifecycle events"
        )


class TestFalcoRules:
    """Validate custom Falco detection rules."""

    @pytest.fixture(autouse=True)
    def load_rules(self):
        path = os.path.join(OUTPUT_DIR, "custom-falco-rules.yaml")
        assert os.path.exists(path), "custom-falco-rules.yaml not found in /app/output/"
        with open(path) as f:
            self.rules_list = yaml.safe_load(f)

    def test_valid_yaml_list(self):
        assert isinstance(self.rules_list, list), (
            "Falco rules file must be a YAML list"
        )

    def test_has_minimum_rules(self):
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        assert len(rules) >= 3, (
            f"Must have at least 3 Falco rules, found {len(rules)}"
        )

    def test_rules_have_required_fields(self):
        required_fields = {"rule", "desc", "condition", "output", "priority"}
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        for rule in rules:
            missing = required_fields - set(rule.keys())
            assert not missing, (
                f"Rule '{rule.get('rule', '?')}' missing fields: {missing}"
            )

    def test_rules_have_tags(self):
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        for rule in rules:
            assert "tags" in rule, (
                f"Rule '{rule['rule']}' must have 'tags' field"
            )
            assert isinstance(rule["tags"], list), (
                f"Rule '{rule['rule']}' tags must be a list"
            )

    def test_valid_priorities(self):
        valid_priorities = {
            "EMERGENCY", "ALERT", "CRITICAL", "ERROR",
            "WARNING", "NOTICE", "INFORMATIONAL", "DEBUG"
        }
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        for rule in rules:
            prio = rule.get("priority", "").upper()
            assert prio in valid_priorities, (
                f"Rule '{rule['rule']}' has invalid priority '{rule.get('priority')}'. "
                f"Valid: {valid_priorities}"
            )

    def test_has_container_shell_rule(self):
        """At least one rule must detect shell spawning or suspicious exec in containers."""
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        found = False
        for rule in rules:
            cond = rule.get("condition", "").lower()
            name = rule.get("rule", "").lower()
            desc = rule.get("desc", "").lower()
            combined = cond + " " + name + " " + desc
            if "container" in combined and (
                "shell" in combined
                or "spawned_process" in cond
                or "proc.name" in cond
                or "exec" in combined
            ):
                found = True
                break
        assert found, (
            "Must have at least one rule detecting shell/exec in containers"
        )

    def test_has_sensitive_file_rule(self):
        """At least one rule must detect sensitive file access."""
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        found = False
        for rule in rules:
            cond = rule.get("condition", "").lower()
            name = rule.get("rule", "").lower()
            desc = rule.get("desc", "").lower()
            combined = cond + " " + name + " " + desc
            if (
                "sensitive" in combined
                or "/etc/shadow" in combined
                or "passwd" in combined
                or "credential" in combined
                or "sensitive_files" in cond
                or "open_read" in cond
            ):
                found = True
                break
        assert found, (
            "Must have at least one rule detecting sensitive file access"
        )

    def test_has_binary_or_network_rule(self):
        """At least one rule must detect binary modification or network tool usage."""
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        found = False
        for rule in rules:
            cond = rule.get("condition", "").lower()
            name = rule.get("rule", "").lower()
            desc = rule.get("desc", "").lower()
            combined = cond + " " + name + " " + desc
            if (
                "binary" in combined
                or "bin/" in combined
                or "/usr/local/bin" in combined
                or "network" in combined
                or "curl" in combined
                or "wget" in combined
                or "package" in combined
                or "apt" in combined
                or "open_write" in cond
                or "network_tool" in cond
                or "package_mgmt" in cond
            ):
                found = True
                break
        assert found, (
            "Must have at least one rule detecting binary modification, "
            "network tool usage, or package management in containers"
        )

    def test_conditions_not_empty(self):
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        for rule in rules:
            cond = rule.get("condition", "").strip()
            assert len(cond) > 10, (
                f"Rule '{rule['rule']}' has an empty or trivial condition"
            )

    def test_outputs_not_empty(self):
        rules = [r for r in self.rules_list if isinstance(r, dict) and "rule" in r]
        for rule in rules:
            output = rule.get("output", "").strip()
            assert len(output) > 10, (
                f"Rule '{rule['rule']}' has an empty or trivial output"
            )
