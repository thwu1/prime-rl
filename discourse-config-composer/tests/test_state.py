
import json
import os
import subprocess
import pytest

COMPOSE_SCRIPT = "/app/compose.py"
DEPLOYMENT_DIR = "/app/deployment"


def run_compose(config_file, config_name, base_dir=None):
    """Run compose.py and return the parsed JSON output."""
    cmd = ["python3", COMPOSE_SCRIPT, config_file, config_name]
    if base_dir:
        cmd.extend(["--base-dir", base_dir])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd="/app")
    assert result.returncode == 0, f"compose.py failed with exit code {result.returncode}: {result.stderr}"
    output = result.stdout.strip()
    assert output, f"compose.py produced no output. stderr: {result.stderr}"
    return json.loads(output)


# ---------------------------------------------------------------------------
# Environment variable merging
# ---------------------------------------------------------------------------

class TestEnvMerging:
    """Test environment variable merging across templates and main config."""

    def test_default_lang(self):
        """Default LANG should be en_US.UTF-8 (launcher starts with this default)."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["env_map"].get("LANG") == "en_US.UTF-8"

    def test_main_config_overrides_templates(self):
        """Main config env values should override template defaults."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        env = result["env_map"]
        assert env["DISCOURSE_HOSTNAME"] == "discourse.example.com"
        assert env["DISCOURSE_SMTP_ADDRESS"] == "smtp.example.com"

    def test_template_env_included(self):
        """Env vars set by templates should appear in the merged result."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        env = result["env_map"]
        # From postgres template
        assert "DISCOURSE_DB_SOCKET" in env
        assert env["DISCOURSE_DB_SOCKET"] == "/var/run/postgresql"
        # From web.ratelimited template
        assert env.get("DISCOURSE_MAX_REQS_PER_IP_MODE") == "block"

    def test_later_template_overrides_earlier(self):
        """Later templates override earlier templates for the same key."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        env = result["env_map"]
        # redis sets DISCOURSE_REDIS_HOST=localhost, web also sets it=localhost
        assert env["DISCOURSE_REDIS_HOST"] == "localhost"

    def test_web_only_overrides_template_db_host(self):
        """web_only.yml overrides template-set DISCOURSE_DB_HOST."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/web_only.yml", "web_only",
            base_dir=DEPLOYMENT_DIR
        )
        env = result["env_map"]
        # web template sets DISCOURSE_DB_HOST=localhost but main config sets it=data
        assert env["DISCOURSE_DB_HOST"] == "data"

    def test_env_list_format(self):
        """The env list should contain -e KEY=VALUE formatted strings."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        env_list = result["env"]
        assert any(e.startswith("-e LANG=") for e in env_list)
        assert any("DISCOURSE_HOSTNAME=" in e for e in env_list)


# ---------------------------------------------------------------------------
# {{config}} variable substitution
# ---------------------------------------------------------------------------

class TestConfigSubstitution:
    """Test {{config}} variable substitution."""

    def test_config_substitution_in_env(self):
        """{{config}} in env values should be replaced with the config name."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["env_map"]["DISCOURSE_DB_NAME"] == "app_discourse"

    def test_config_substitution_different_name(self):
        """Substitution should use the provided config name, not the filename."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "mysite",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["env_map"]["DISCOURSE_DB_NAME"] == "mysite_discourse"

    def test_config_substitution_web_only(self):
        """{{config}} substitution in web_only container."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/web_only.yml", "web_only",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["env_map"]["DISCOURSE_DB_NAME"] == "web_only_discourse"


# ---------------------------------------------------------------------------
# Port / expose formatting
# ---------------------------------------------------------------------------

class TestPortFormatting:
    """Test port/expose argument formatting."""

    def test_port_mapping_generates_dash_p(self):
        """Port entries with ':' should generate -p arguments."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        ports = result["ports"]
        assert any("-p 80:80" in p for p in ports)
        assert any("-p 443:443" in p for p in ports)

    def test_port_expose_generates_expose(self):
        """Port entries without ':' should generate --expose arguments."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        ports = result["ports"]
        # postgres template exposes 5432 (no colon)
        assert any("--expose" in p and "5432" in p for p in ports)

    def test_ports_collected_from_templates_and_config(self):
        """Ports should come from BOTH templates AND the main config."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        raw = result["raw_ports"]
        # Templates contribute: 5432, 6379, 80, 443:443
        # Main config contributes: 80:80, 443:443
        assert len(raw) >= 6

    def test_data_container_port_mappings(self):
        """Data container has explicit host:container port mappings."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        ports = result["ports"]
        assert any("-p 5432:5432" in p for p in ports)
        assert any("-p 6379:6379" in p for p in ports)


# ---------------------------------------------------------------------------
# Volumes — only from main config
# ---------------------------------------------------------------------------

class TestVolumes:
    """Test that volumes come only from the main config file."""

    def test_volumes_from_config_only(self):
        """Volumes should come exclusively from the main config, not templates."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        volumes = result["volumes"]
        assert len(volumes) == 2
        assert any("/var/discourse/shared/standalone:/shared" in v for v in volumes)
        assert any("/var/discourse/shared/standalone/log/var-log:/var/log" in v for v in volumes)

    def test_data_container_has_own_volumes(self):
        """Data container should have its own volume config."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        volumes = result["volumes"]
        assert len(volumes) == 1
        assert any("/var/discourse/shared/data:/shared" in v for v in volumes)


# ---------------------------------------------------------------------------
# docker_args — only from main config
# ---------------------------------------------------------------------------

class TestDockerArgs:
    """Test that docker_args comes only from the main config file."""

    def test_docker_args_present(self):
        """data.yml has explicit docker_args."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["docker_args"] == "--restart=always"

    def test_docker_args_absent(self):
        """app.yml has no docker_args — should be empty string."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["docker_args"] == ""


# ---------------------------------------------------------------------------
# Boot command and run image defaults
# ---------------------------------------------------------------------------

class TestDefaults:
    """Test default values for boot_command and run_image."""

    def test_default_boot_command(self):
        """Default boot command should be /sbin/boot."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["boot_command"] == "/sbin/boot"

    def test_default_run_image(self):
        """Default run image should be local_discourse/{config_name}."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["run_image"] == "local_discourse/app"

    def test_run_image_uses_config_name(self):
        """Run image includes the provided config name."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["run_image"] == "local_discourse/data"


# ---------------------------------------------------------------------------
# Hooks merging
# ---------------------------------------------------------------------------

class TestHooksMerging:
    """Test hooks merging across templates and main config."""

    def test_hooks_merged_from_templates(self):
        """Hook names from templates should be present in merged output."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        hooks = result["hooks"]
        assert "after_code" in hooks
        assert "after_postgres" in hooks
        assert "after_redis" in hooks

    def test_hooks_from_letsencrypt_template(self):
        """after_ssl hook from Let's Encrypt template should be present."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "after_ssl" in result["hooks"]


# ---------------------------------------------------------------------------
# Params merging
# ---------------------------------------------------------------------------

class TestParamsMerging:
    """Test params merging across templates and main config."""

    def test_params_from_template(self):
        """Params set by templates should be in the merged result."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["params"]["db_default_text_search_config"] == "pg_catalog.english"

    def test_main_config_overrides_template_params(self):
        """Main config params override template params for same key."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        # postgres template sets 256MB, app.yml overrides to 4096MB
        assert result["params"]["db_shared_buffers"] == "4096MB"


# ---------------------------------------------------------------------------
# Issue detection
# ---------------------------------------------------------------------------

class TestIssueDetection:
    """Test configuration issue detection."""

    def _codes(self, result):
        return [i["code"] for i in result["issues"]]

    # --- app.yml issues ---

    def test_smtp_not_configured(self):
        """Should detect SMTP still set to example address."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "SMTP_NOT_CONFIGURED" in self._codes(result)

    def test_hostname_not_configured(self):
        """Should detect hostname still set to example value."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "HOSTNAME_NOT_CONFIGURED" in self._codes(result)

    def test_bundled_plugin_detected(self):
        """Should detect at least 2 bundled plugins in hooks."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        codes = self._codes(result)
        bundled_count = codes.count("BUNDLED_PLUGIN")
        assert bundled_count >= 2, f"Expected >= 2 BUNDLED_PLUGIN, got {bundled_count}"

    def test_missing_shm_size(self):
        """Should detect missing --shm-size when postgres template is used."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "MISSING_SHM_SIZE" in self._codes(result)

    def test_shared_buffers_too_high(self):
        """Should detect db_shared_buffers set unreasonably high."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "SHARED_BUFFERS_TOO_HIGH" in self._codes(result)

    def test_missing_letsencrypt_email_app(self):
        """Should detect missing LE email in app.yml (uses LE template)."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "MISSING_LETSENCRYPT_EMAIL" in self._codes(result)

    # --- data.yml issues ---

    def test_exposed_db_port(self):
        """Should detect PostgreSQL port exposed on all interfaces."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        assert "EXPOSED_DB_PORT" in self._codes(result)

    def test_exposed_redis_port(self):
        """Should detect Redis port exposed on all interfaces."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        assert "EXPOSED_REDIS_PORT" in self._codes(result)

    def test_data_missing_shm_size(self):
        """data.yml uses postgres template but docker_args has no --shm-size."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/data.yml", "data",
            base_dir=DEPLOYMENT_DIR
        )
        assert "MISSING_SHM_SIZE" in self._codes(result)

    # --- web_only.yml issues ---

    def test_ssl_with_ip_hostname(self):
        """Should detect SSL template used with IP-only hostname."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/web_only.yml", "web_only",
            base_dir=DEPLOYMENT_DIR
        )
        assert "SSL_WITH_IP_HOSTNAME" in self._codes(result)

    def test_missing_letsencrypt_email_web(self):
        """Should detect missing LE email in web_only.yml."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/web_only.yml", "web_only",
            base_dir=DEPLOYMENT_DIR
        )
        assert "MISSING_LETSENCRYPT_EMAIL" in self._codes(result)

    def test_missing_template_file(self):
        """Should report template file that does not exist."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/web_only.yml", "web_only",
            base_dir=DEPLOYMENT_DIR
        )
        assert len(result["template_errors"]) > 0
        assert any("nonexistent" in e["template"] for e in result["template_errors"])

    # --- Negative tests (no false positives) ---

    def test_no_smtp_false_positive_when_configured(self):
        """web_only.yml has valid SMTP — should NOT flag it."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/web_only.yml", "web_only",
            base_dir=DEPLOYMENT_DIR
        )
        assert "SMTP_NOT_CONFIGURED" not in self._codes(result)

    def test_no_bundled_plugin_for_docker_manager(self):
        """docker_manager is NOT bundled — should not be flagged."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        messages = [i["message"] for i in result["issues"] if i["code"] == "BUNDLED_PLUGIN"]
        assert not any("docker_manager" in m or "docker-manager" in m for m in messages)

    def test_no_exposed_port_for_app_standalone(self):
        """app.yml templates expose 5432/6379 as --expose (not mapping) — no issue."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        codes = self._codes(result)
        assert "EXPOSED_DB_PORT" not in codes
        assert "EXPOSED_REDIS_PORT" not in codes


# ---------------------------------------------------------------------------
# Templates tracking
# ---------------------------------------------------------------------------

class TestTemplatesUsed:
    """Test that the output tracks which templates were referenced."""

    def test_templates_used_listed(self):
        """templates_used should list the template paths from the config."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert "templates/postgres.template.yml" in result["templates_used"]
        assert "templates/web.template.yml" in result["templates_used"]
        assert len(result["templates_used"]) == 6


# ---------------------------------------------------------------------------
# Label merging with {{config}} substitution
# ---------------------------------------------------------------------------

class TestLabelMerging:
    """Test label merging and variable substitution in labels."""

    def test_labels_with_config_substitution(self):
        """Labels should have {{config}} replaced with the config name."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["label_map"]["app"] == "multi"
        assert result["label_map"]["monitor"] == "true"

    def test_labels_list_format(self):
        """Labels list should contain -l KEY=VALUE formatted strings."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert any("app=multi" in lbl for lbl in result["labels"])

    def test_no_labels_when_absent(self):
        """Configs without labels section should produce empty label outputs."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/app.yml", "app",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["label_map"] == {}
        assert result["labels"] == []


# ---------------------------------------------------------------------------
# Custom boot_command and run_image overrides
# ---------------------------------------------------------------------------

class TestCustomOverrides:
    """Test that custom boot_command and run_image override defaults."""

    def test_custom_boot_command(self):
        """Config-specified boot_command should override the /sbin/boot default."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["boot_command"] == "/sbin/custom_boot"

    def test_custom_run_image(self):
        """Config-specified run_image should override local_discourse/{name}."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["run_image"] == "registry.mycompany.com/discourse:latest"


# ---------------------------------------------------------------------------
# Three-part port notation (ip:hostport:containerport)
# ---------------------------------------------------------------------------

class TestAdvancedPortFormats:
    """Test three-part port notation and mixed port formats."""

    def test_three_part_port_generates_dash_p(self):
        """ip:hostport:containerport notation should produce a -p argument."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        ports = result["ports"]
        assert any("-p 127.0.0.1:8080:80" in p for p in ports)

    def test_bare_port_generates_expose(self):
        """Bare port number without colons should produce --expose argument."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        ports = result["ports"]
        assert any("--expose" in p and "3000" in p for p in ports)


# ---------------------------------------------------------------------------
# Multi-site composition correctness
# ---------------------------------------------------------------------------

class TestMultiSiteComposition:
    """Test composition behavior on the multi-site configuration."""

    def test_multi_env_from_templates(self):
        """Multi config should include env vars from its referenced templates."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        env = result["env_map"]
        assert env["DISCOURSE_DB_SOCKET"] == "/var/run/postgresql"
        assert env["DISCOURSE_REDIS_HOST"] == "localhost"
        assert env["DISCOURSE_MAX_REQS_PER_IP_MODE"] == "block"

    def test_multi_config_name_substitution(self):
        """{{config}} should be substituted with 'multi' in env values."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert result["env_map"]["DISCOURSE_DB_NAME"] == "multi_discourse"

    def test_multi_templates_listed(self):
        """templates_used should list the 4 templates from multi.yml."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert len(result["templates_used"]) == 4
        assert "templates/postgres.template.yml" in result["templates_used"]

    def test_multi_docker_args(self):
        """docker_args should reflect multi.yml's custom value."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert "--shm-size=512m" in result["docker_args"]
        assert "--restart=always" in result["docker_args"]

    def test_multi_volumes(self):
        """Volumes should be from multi.yml main config only."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert len(result["volumes"]) == 1
        assert any("/var/discourse/shared/multi:/shared" in v for v in result["volumes"])

    def test_multi_hooks_merged(self):
        """Hooks from templates and config should be merged by name."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        hooks = result["hooks"]
        assert "after_code" in hooks
        assert "after_postgres" in hooks
        assert "after_redis" in hooks
        # after_code should have entries from both web template and multi config
        assert len(hooks["after_code"]) >= 2


# ---------------------------------------------------------------------------
# Multi-site negative issue tests (no false positives)
# ---------------------------------------------------------------------------

class TestMultiSiteNegatives:
    """Verify zero false positives on the correctly configured multi-site deployment."""

    def _codes(self, result):
        return [i["code"] for i in result["issues"]]

    def test_no_smtp_issue_when_properly_configured(self):
        """Valid SMTP should NOT trigger SMTP_NOT_CONFIGURED."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert "SMTP_NOT_CONFIGURED" not in self._codes(result)

    def test_no_hostname_issue_with_real_domain(self):
        """Real domain hostname should NOT trigger HOSTNAME_NOT_CONFIGURED."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert "HOSTNAME_NOT_CONFIGURED" not in self._codes(result)

    def test_no_shm_issue_when_docker_args_set(self):
        """--shm-size in docker_args should prevent MISSING_SHM_SIZE."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert "MISSING_SHM_SIZE" not in self._codes(result)

    def test_no_shared_buffers_issue_below_threshold(self):
        """db_shared_buffers under 2048MB should NOT trigger warning."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert "SHARED_BUFFERS_TOO_HIGH" not in self._codes(result)

    def test_no_exposed_port_with_localhost_binding(self):
        """127.0.0.1-bound ports should NOT trigger exposed port warnings."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        codes = self._codes(result)
        assert "EXPOSED_DB_PORT" not in codes
        assert "EXPOSED_REDIS_PORT" not in codes

    def test_multi_has_zero_issues(self):
        """Correctly configured multi.yml should have zero detected issues."""
        result = run_compose(
            f"{DEPLOYMENT_DIR}/containers/multi.yml", "multi",
            base_dir=DEPLOYMENT_DIR
        )
        assert len(result["issues"]) == 0, f"Unexpected issues: {result['issues']}"
