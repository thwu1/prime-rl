"""
Tests for the Discourse Docker Configuration Resolver and Deployment Analyzer.

Verifies that the resolver correctly implements the launcher's resolution
algorithm and that the deployment analyzer produces correct audit findings
and docker-compose output.
"""

import subprocess
import json
import hashlib
import pytest
import yaml


def run_resolver(config_name, hostname="testhost"):
    """Run the resolver and return parsed JSON output."""
    result = subprocess.run(
        [
            "python3", "/app/resolve.py", config_name,
            "--base-dir", "/app",
            "--hostname", hostname,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Resolver exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    return json.loads(result.stdout)


def run_analyzer():
    """Run the deployment analyzer and return parsed JSON output."""
    result = subprocess.run(
        ["python3", "/app/analyze_deployment.py", "--base-dir", "/app"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Analyzer exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\n"
        f"stdout: {result.stdout}"
    )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Merge order: container config must override template values
# ---------------------------------------------------------------------------

class TestMergeOrder:
    def test_env_config_overrides_template(self):
        """Container config's DISCOURSE_HOSTNAME must win over the template's."""
        result = run_resolver("app")
        assert result["env"]["DISCOURSE_HOSTNAME"] == "forum.mysite.com"

    def test_env_developer_emails_from_config(self):
        result = run_resolver("app")
        assert result["env"]["DISCOURSE_DEVELOPER_EMAILS"] == (
            "admin@mysite.com,dev@mysite.com"
        )

    def test_params_config_overrides_template(self):
        result = run_resolver("app")
        assert result["params"]["db_shared_buffers"] == "512MB"


# ---------------------------------------------------------------------------
# Label substitution: {{config}} must be replaced in label values
# ---------------------------------------------------------------------------

class TestLabelSubstitution:
    def test_config_placeholder_in_labels(self):
        result = run_resolver("web_only")
        assert result["labels"]["app_name"] == "web_only_discourse"

    def test_static_labels_unaffected(self):
        result = run_resolver("web_only")
        assert result["labels"]["monitor"] == "true"
        assert result["labels"]["ssl"] == "enabled"


# ---------------------------------------------------------------------------
# Hook merging: commands from multiple layers must be concatenated
# ---------------------------------------------------------------------------

class TestHookMerging:
    def test_hooks_from_both_template_and_config(self):
        """after_code must contain commands from web template AND app config."""
        result = run_resolver("app")
        after_code = result["hooks"]["after_code"]
        all_text = json.dumps(after_code)
        assert "mkdir -p plugins" in all_text, "Template hook command missing"
        assert "docker_manager" in all_text, "Config hook command missing"

    def test_hook_command_order(self):
        """Template commands must appear before config commands."""
        result = run_resolver("app")
        after_code = result["hooks"]["after_code"]

        mkdir_idx = None
        clone_idx = None
        for i, entry in enumerate(after_code):
            entry_text = json.dumps(entry)
            if "mkdir -p plugins" in entry_text:
                mkdir_idx = i
            if "docker_manager" in entry_text:
                clone_idx = i

        assert mkdir_idx is not None, "Template hook (mkdir) not found"
        assert clone_idx is not None, "Config hook (git clone) not found"
        assert mkdir_idx < clone_idx, (
            f"Template hooks at {mkdir_idx} should precede "
            f"config hooks at {clone_idx}"
        )

    def test_independent_hooks_preserved(self):
        result = run_resolver("app")
        assert "after_postgres" in result["hooks"]
        assert "after_redis" in result["hooks"]
        assert "after_code" in result["hooks"]


# ---------------------------------------------------------------------------
# Port bind address: three-part format must keep the IP
# ---------------------------------------------------------------------------

class TestPortBindAddress:
    def test_ip_host_container_format_preserved(self):
        result = run_resolver("data")
        assert "-p 127.0.0.1:5432:5432" in result["port_args"]
        assert "-p 127.0.0.1:6379:6379" in result["port_args"]

    def test_simple_port_format(self):
        result = run_resolver("app")
        assert "-p 80:80" in result["port_args"]
        assert "-p 443:443" in result["port_args"]

    def test_expose_without_publish(self):
        result = run_resolver("data")
        assert "--expose 5432" in result["port_args"]
        assert "--expose 6379" in result["port_args"]


# ---------------------------------------------------------------------------
# Hostname normalization: underscores replaced with hyphens
# ---------------------------------------------------------------------------

class TestHostnameNormalization:
    def test_underscore_replaced_with_hyphen(self):
        result = run_resolver("web_only")
        assert result["hostname"] == "testhost-web-only"
        assert "_" not in result["hostname"]

    def test_hostname_without_underscores(self):
        result = run_resolver("app")
        assert result["hostname"] == "testhost-app"

    def test_mac_address_matches_normalized_hostname(self):
        result = run_resolver("web_only")
        expected_hostname = "testhost-web-only"
        md5 = hashlib.md5((expected_hostname + "\n").encode()).hexdigest()
        expected_mac = (
            f"02:{md5[0:2]}:{md5[2:4]}:"
            f"{md5[4:6]}:{md5[6:8]}:{md5[8:10]}"
        )
        assert result["mac_address"] == expected_mac


# ---------------------------------------------------------------------------
# General resolution correctness
# ---------------------------------------------------------------------------

class TestGeneralResolution:
    def test_template_env_preserved(self):
        result = run_resolver("app")
        assert result["env"]["DISCOURSE_DB_HOST"] == "localhost"
        assert result["env"]["DISCOURSE_REDIS_HOST"] == "localhost"

    def test_config_substitution_in_env(self):
        result = run_resolver("app")
        assert result["env"]["DISCOURSE_DB_NAME"] == "app_discourse"

    def test_data_config_substitution_in_env(self):
        result = run_resolver("data")
        assert result["env"]["DISCOURSE_DB_NAME"] == "data_discourse"

    def test_docker_args_from_config(self):
        result = run_resolver("app")
        assert result["docker_args"] == "--shm-size=512m"

    def test_data_docker_args(self):
        result = run_resolver("data")
        assert result["docker_args"] == "--shm-size=1g"

    def test_bundled_plugins_detected(self):
        result = run_resolver("app")
        assert "discourse-solved" in result["bundled_plugins"]
        assert "discourse-data-explorer" in result["bundled_plugins"]

    def test_non_bundled_plugins_not_flagged(self):
        result = run_resolver("app")
        assert "docker_manager" not in result["bundled_plugins"]

    def test_default_boot_command(self):
        result = run_resolver("app")
        assert result["boot_command"] == "/sbin/boot"

    def test_run_image_default(self):
        result = run_resolver("app")
        assert result["run_image"] == "local_discourse/app"

    def test_volumes_accumulated(self):
        result = run_resolver("app")
        assert len(result["volumes"]) >= 2

    def test_mac_address_format(self):
        result = run_resolver("app")
        mac = result["mac_address"]
        assert mac.startswith("02:")
        parts = mac.split(":")
        assert len(parts) == 6
        for part in parts:
            assert len(part) == 2

    def test_expose_deduplication(self):
        result = run_resolver("app")
        count = sum(1 for p in result["port_args"] if p == "-p 80:80")
        assert count == 1, f"Expected 1 occurrence of -p 80:80, got {count}"

    def test_web_only_bundled_plugins(self):
        result = run_resolver("web_only")
        assert "discourse-ai" in result["bundled_plugins"]
        assert "discourse-calendar" in result["bundled_plugins"]


# ---------------------------------------------------------------------------
# Deployment Analyzer — Audit Findings
# ---------------------------------------------------------------------------

class TestAuditPortConflicts:
    def test_port_conflict_detected(self):
        """Should detect that app and web_only both publish ports 80 and 443."""
        report = run_analyzer()
        conflicts = [f for f in report["audit"] if f["type"] == "port_conflict"]
        assert len(conflicts) >= 1, "No port_conflict findings detected"

    def test_port_conflict_involves_app_and_web_only(self):
        report = run_analyzer()
        conflicts = [f for f in report["audit"] if f["type"] == "port_conflict"]
        all_containers = set()
        for f in conflicts:
            all_containers.update(f["containers"])
        assert "app" in all_containers, "app should be in port conflict"
        assert "web_only" in all_containers, "web_only should be in port conflict"

    def test_port_conflict_excludes_data(self):
        """data binds to 127.0.0.1 on different ports, no conflict with app/web_only."""
        report = run_analyzer()
        conflicts = [f for f in report["audit"] if f["type"] == "port_conflict"]
        for f in conflicts:
            assert "data" not in f["containers"], (
                f"data should not be in port conflict: {f}"
            )

    def test_port_conflict_mentions_port_number(self):
        report = run_analyzer()
        conflicts = [f for f in report["audit"] if f["type"] == "port_conflict"]
        all_details = " ".join(f["detail"] for f in conflicts)
        assert "80" in all_details or "443" in all_details


class TestAuditBundledPlugins:
    def test_bundled_plugin_detected_for_app(self):
        report = run_analyzer()
        bp = [f for f in report["audit"] if f["type"] == "bundled_plugin"]
        app_findings = [f for f in bp if "app" in f["containers"]]
        assert len(app_findings) >= 1, "No bundled_plugin finding for app"
        all_details = " ".join(f["detail"] for f in app_findings)
        assert "discourse-solved" in all_details or \
               "discourse-data-explorer" in all_details

    def test_bundled_plugin_detected_for_web_only(self):
        report = run_analyzer()
        bp = [f for f in report["audit"] if f["type"] == "bundled_plugin"]
        wo_findings = [f for f in bp if "web_only" in f["containers"]]
        assert len(wo_findings) >= 1, "No bundled_plugin finding for web_only"
        all_details = " ".join(f["detail"] for f in wo_findings)
        assert "discourse-ai" in all_details or \
               "discourse-calendar" in all_details

    def test_bundled_plugin_is_warning_severity(self):
        report = run_analyzer()
        bp = [f for f in report["audit"] if f["type"] == "bundled_plugin"]
        assert len(bp) >= 1
        for f in bp:
            assert f["severity"] == "warning", (
                f"bundled_plugin should be warning, got {f['severity']}"
            )


class TestAuditLocalhostBinding:
    def test_localhost_binding_detected(self):
        """data binds postgres/redis to 127.0.0.1, web_only references data."""
        report = run_analyzer()
        lb = [f for f in report["audit"] if f["type"] == "localhost_binding"]
        assert len(lb) >= 1, "No localhost_binding finding detected"

    def test_localhost_binding_involves_data_and_web_only(self):
        report = run_analyzer()
        lb = [f for f in report["audit"] if f["type"] == "localhost_binding"]
        all_containers = set()
        for f in lb:
            all_containers.update(f["containers"])
        assert "data" in all_containers, "data should be in localhost_binding"
        assert "web_only" in all_containers, (
            "web_only should be in localhost_binding"
        )

    def test_localhost_binding_is_error_severity(self):
        report = run_analyzer()
        lb = [f for f in report["audit"] if f["type"] == "localhost_binding"]
        assert len(lb) >= 1
        for f in lb:
            assert f["severity"] == "error", (
                f"localhost_binding should be error, got {f['severity']}"
            )


class TestAuditFindingFormat:
    def test_all_findings_have_required_fields(self):
        report = run_analyzer()
        assert len(report["audit"]) >= 4, (
            "Expected at least 4 audit findings (port_conflict, "
            "bundled_plugin x2, localhost_binding)"
        )
        for f in report["audit"]:
            assert "type" in f, f"Finding missing 'type': {f}"
            assert "severity" in f, f"Finding missing 'severity': {f}"
            assert "containers" in f, f"Finding missing 'containers': {f}"
            assert "detail" in f, f"Finding missing 'detail': {f}"
            assert f["severity"] in ("error", "warning"), (
                f"Invalid severity: {f['severity']}"
            )
            assert isinstance(f["containers"], list), (
                f"'containers' must be a list: {f}"
            )
            assert len(f["containers"]) >= 1, (
                f"'containers' must not be empty: {f}"
            )


# ---------------------------------------------------------------------------
# Deployment Analyzer — Docker Compose Generation
# ---------------------------------------------------------------------------

class TestComposeGeneration:
    @pytest.fixture(autouse=True)
    def _load_compose(self):
        report = run_analyzer()
        assert "compose" in report, "Analyzer output missing 'compose' key"
        self.compose = yaml.safe_load(report["compose"])
        assert self.compose is not None, "compose YAML is empty or invalid"

    def test_compose_has_all_services(self):
        assert "services" in self.compose
        assert "app" in self.compose["services"]
        assert "web_only" in self.compose["services"]
        assert "data" in self.compose["services"]

    def test_compose_app_image(self):
        assert self.compose["services"]["app"]["image"] == "local_discourse/app"

    def test_compose_app_hostname(self):
        assert self.compose["services"]["app"]["hostname"] == "testhost-app"

    def test_compose_web_only_hostname_normalized(self):
        """Hostname must have underscores replaced with hyphens."""
        assert self.compose["services"]["web_only"]["hostname"] == (
            "testhost-web-only"
        )

    def test_compose_app_ports(self):
        ports = self.compose["services"]["app"]["ports"]
        assert "80:80" in ports
        assert "443:443" in ports

    def test_compose_data_ports(self):
        ports = self.compose["services"]["data"]["ports"]
        assert "127.0.0.1:5432:5432" in ports
        assert "127.0.0.1:6379:6379" in ports

    def test_compose_app_volumes(self):
        volumes = self.compose["services"]["app"]["volumes"]
        assert any("/shared" in str(v) for v in volumes)

    def test_compose_web_only_depends_on_data(self):
        """web_only references data via DISCOURSE_DB_HOST."""
        depends = self.compose["services"]["web_only"].get("depends_on", [])
        if isinstance(depends, dict):
            assert "data" in depends
        else:
            assert "data" in depends

    def test_compose_data_mac_address(self):
        mac = self.compose["services"]["data"]["mac_address"]
        expected_hostname = "testhost-data"
        md5 = hashlib.md5(
            (expected_hostname + "\n").encode()
        ).hexdigest()
        expected_mac = (
            f"02:{md5[0:2]}:{md5[2:4]}:"
            f"{md5[4:6]}:{md5[6:8]}:{md5[8:10]}"
        )
        assert mac == expected_mac

    def test_compose_app_environment_hostname(self):
        env = self.compose["services"]["app"]["environment"]
        if isinstance(env, dict):
            assert env.get("DISCOURSE_HOSTNAME") == "forum.mysite.com"
        else:
            assert any(
                "DISCOURSE_HOSTNAME" in str(e) and "forum.mysite.com" in str(e)
                for e in env
            )

    def test_compose_boot_command(self):
        assert self.compose["services"]["app"]["command"] == "/sbin/boot"
