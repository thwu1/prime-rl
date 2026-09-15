
import json
import os
import subprocess

import pytest
import yaml


@pytest.fixture(scope="session", autouse=True)
def playbook_result():
    """Run the site.yml playbook and capture the result."""
    result = subprocess.run(
        ["ansible-playbook", "site.yml"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=180,
    )
    return result


class TestPlaybookExecution:
    def test_playbook_runs_successfully(self, playbook_result):
        """The site.yml playbook must complete without errors."""
        assert playbook_result.returncode == 0, (
            f"Playbook failed with rc={playbook_result.returncode}\n"
            f"STDOUT:\n{playbook_result.stdout[-2000:]}\n"
            f"STDERR:\n{playbook_result.stderr[-2000:]}"
        )


class TestFilterPlugin:
    def test_filter_plugin_file_exists(self):
        """A custom filter plugin .py file must exist."""
        filter_dirs = [
            "/app/filter_plugins",
            "/app/roles/webapp/filter_plugins",
        ]
        found = False
        for d in filter_dirs:
            if os.path.isdir(d):
                for fname in os.listdir(d):
                    if fname.endswith(".py") and not fname.startswith("__"):
                        found = True
                        break
        assert found, (
            "No custom filter plugin .py file found in any filter_plugins directory"
        )

    def test_filter_plugin_defines_filtermodule(self):
        """The filter plugin must define a FilterModule class."""
        filter_dirs = [
            "/app/filter_plugins",
            "/app/roles/webapp/filter_plugins",
        ]
        for d in filter_dirs:
            if os.path.isdir(d):
                for fname in os.listdir(d):
                    if fname.endswith(".py") and not fname.startswith("__"):
                        with open(os.path.join(d, fname)) as f:
                            content = f.read()
                        if "class FilterModule" in content:
                            return
        pytest.fail("No FilterModule class found in any filter plugin file")


class TestRoleVarsIntegrity:
    def test_role_vars_preserves_intentional_overrides(self):
        """Intentional security overrides must remain in role vars."""
        vars_path = "/app/roles/webapp/vars/main.yml"
        assert os.path.isfile(vars_path), "Role vars/main.yml should still exist"
        with open(vars_path) as f:
            data = yaml.safe_load(f)
        assert data is not None, "Role vars/main.yml should not be empty"
        assert "max_connections" in data, (
            "max_connections must remain in role vars (intentional security hardening)"
        )
        assert "ssl_redirect" in data, (
            "ssl_redirect must remain in role vars (intentional security hardening)"
        )

    def test_role_vars_removes_accidental_override(self):
        """The accidental app_port override must be removed from role vars."""
        with open("/app/roles/webapp/vars/main.yml") as f:
            data = yaml.safe_load(f)
        if data is not None:
            assert "app_port" not in data, (
                "app_port should be removed from role vars — it accidentally "
                "shadows the group_vars value of 3000 with 8080"
            )


class TestNginxConfig:
    def test_nginx_config_exists(self):
        assert os.path.isfile("/etc/nginx/conf.d/app.conf"), (
            "/etc/nginx/conf.d/app.conf was not created"
        )

    def test_upstream_with_weights(self):
        """Upstream entries must include weight from service definitions."""
        with open("/etc/nginx/conf.d/app.conf") as f:
            content = f.read()
        assert "server 127.0.0.1:8001 weight=3;" in content, (
            "API service upstream entry should be '127.0.0.1:8001 weight=3'"
        )
        assert "server 127.0.0.1:8002 weight=5;" in content, (
            "Worker service upstream entry should be '127.0.0.1:8002 weight=5'"
        )

    def test_disabled_service_excluded(self):
        with open("/etc/nginx/conf.d/app.conf") as f:
            content = f.read()
        assert "8003" not in content, (
            "Disabled scheduler service (8003) should not appear in upstream"
        )

    def test_correct_server_name(self):
        with open("/etc/nginx/conf.d/app.conf") as f:
            content = f.read()
        assert "server_name webapp.local;" in content, (
            "server_name should be 'webapp.local' from app_server_name variable"
        )

    def test_ssl_redirect_present(self):
        """ssl_redirect from role vars should produce HTTPS redirect block."""
        with open("/etc/nginx/conf.d/app.conf") as f:
            content = f.read()
        assert "return 301 https://" in content, (
            "SSL redirect block should be present (ssl_redirect=true from role vars)"
        )

    def test_max_connections_header(self):
        """Max connections header should reflect role vars hardened value."""
        with open("/etc/nginx/conf.d/app.conf") as f:
            content = f.read()
        assert "X-Max-Conn 500" in content, (
            "X-Max-Conn should be 500 from role vars, not 100 from defaults"
        )


class TestAppConfig:
    def test_app_config_exists(self):
        assert os.path.isfile("/etc/app_config.json"), (
            "/etc/app_config.json was not created"
        )

    def test_app_config_valid_json(self):
        with open("/etc/app_config.json") as f:
            try:
                json.load(f)
            except json.JSONDecodeError as e:
                pytest.fail(f"app_config.json is not valid JSON: {e}")

    def test_app_config_port_from_group_vars(self):
        """Port must be 3000 from group_vars, not 8080 from role vars."""
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert data["port"] == 3000, (
            f"Port should be 3000 (from group_vars), got {data['port']}. "
            "The role vars override of app_port is accidental."
        )

    def test_app_config_max_connections_from_role_vars(self):
        """max_connections must be 500 from role vars (intentional hardening)."""
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert data["max_connections"] == 500, (
            f"max_connections should be 500 (role vars hardening), got {data['max_connections']}"
        )

    def test_app_config_app_name(self):
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert data["app_name"] == "mywebapp"

    def test_app_config_services(self):
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert len(data["services"]) == 3, (
            f"Expected 3 services, got {len(data['services'])}"
        )

    def test_health_endpoints_api(self):
        """Custom filter must produce health URL for enabled API service."""
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert "health_endpoints" in data, "health_endpoints key missing"
        assert data["health_endpoints"]["api"] == "http://127.0.0.1:8001/health", (
            "API health endpoint should be http://127.0.0.1:8001/health"
        )

    def test_health_endpoints_worker(self):
        """Custom filter must produce health URL for enabled worker service."""
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert data["health_endpoints"]["worker"] == "http://127.0.0.1:8002/health", (
            "Worker health endpoint should be http://127.0.0.1:8002/health"
        )

    def test_health_endpoints_excludes_disabled(self):
        """Disabled scheduler must not appear in health_endpoints."""
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert "scheduler" not in data["health_endpoints"], (
            "Disabled scheduler should not appear in health_endpoints"
        )

    def test_app_config_vault_secrets(self):
        with open("/etc/app_config.json") as f:
            data = json.load(f)
        assert data["database"]["password"] == "S3cur3P@ss!", (
            "database.password should contain vault-decrypted value"
        )
        assert data["api_key"] == "ak-7f3d9a2b1c4e5f6789", (
            "api_key should contain vault-decrypted value"
        )


class TestUserAccounts:
    def test_appuser1_exists(self):
        result = subprocess.run(["id", "appuser1"], capture_output=True, text=True)
        assert result.returncode == 0, "appuser1 does not exist"

    def test_appuser2_exists(self):
        result = subprocess.run(["id", "appuser2"], capture_output=True, text=True)
        assert result.returncode == 0, "appuser2 does not exist"

    def test_appuser1_in_appteam(self):
        result = subprocess.run(["id", "appuser1"], capture_output=True, text=True)
        assert "appteam" in result.stdout, "appuser1 not in appteam group"

    def test_appuser2_in_appteam(self):
        result = subprocess.run(["id", "appuser2"], capture_output=True, text=True)
        assert "appteam" in result.stdout, "appuser2 not in appteam group"


class TestSystemReport:
    def test_report_exists(self):
        assert os.path.isfile("/var/log/system_report.txt"), (
            "/var/log/system_report.txt was not created"
        )

    def test_report_hostname(self):
        with open("/var/log/system_report.txt") as f:
            content = f.read()
        assert "HOSTNAME=localhost" in content

    def test_report_memory(self):
        with open("/var/log/system_report.txt") as f:
            content = f.read()
        for line in content.splitlines():
            if line.startswith("MEMORY_MB="):
                val = line.split("=", 1)[1].strip()
                assert val.isdigit(), f"MEMORY_MB should be numeric, got '{val}'"
                return
        pytest.fail("MEMORY_MB line not found in report")

    def test_report_app_name(self):
        with open("/var/log/system_report.txt") as f:
            content = f.read()
        assert "APP_NAME=mywebapp" in content

    def test_report_app_port(self):
        with open("/var/log/system_report.txt") as f:
            content = f.read()
        assert "APP_PORT=3000" in content, (
            "APP_PORT should be 3000, not 8080"
        )

    def test_report_admin_email(self):
        with open("/var/log/system_report.txt") as f:
            content = f.read()
        assert "ADMIN_EMAIL=admin@example.com" in content, (
            "ADMIN_EMAIL should be vault-decrypted value"
        )


class TestCronJob:
    def test_cron_job_exists(self):
        result = subprocess.run(
            ["crontab", "-l", "-u", "appuser1"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"No crontab for appuser1: {result.stderr}"
        )
        assert "app log cleanup" in result.stdout, (
            "Cron job 'app log cleanup' not found in appuser1 crontab"
        )


class TestVault:
    def test_vault_decryptable(self):
        result = subprocess.run(
            [
                "ansible-vault", "view",
                "--vault-password-file", "/app/vault_pass.txt",
                "/app/secrets.yml",
            ],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"Cannot decrypt vault with vault_pass.txt: {result.stderr}"
        )

    def test_vault_contains_expected_vars(self):
        result = subprocess.run(
            [
                "ansible-vault", "view",
                "--vault-password-file", "/app/vault_pass.txt",
                "/app/secrets.yml",
            ],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert "db_password" in result.stdout
        assert "api_key" in result.stdout
        assert "admin_email" in result.stdout
