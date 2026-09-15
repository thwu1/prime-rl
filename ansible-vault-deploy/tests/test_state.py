#!/usr/bin/env python3
"""Verification tests for the completed Ansible project."""


import os
import subprocess
import json
import configparser
import grp
import pwd

import pytest

PROJECT_DIR = "/app/ansible-project"


class TestAnsibleConfig:
    """Verify ansible.cfg has been correctly fixed."""

    def test_ansible_cfg_exists(self):
        assert os.path.exists(f"{PROJECT_DIR}/ansible.cfg")

    def test_inventory_path_correct(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        inv_path = config.get("defaults", "inventory").strip()
        assert "/inv/" not in inv_path, f"Inventory path still broken: {inv_path}"
        assert "inventory" in inv_path

    def test_host_key_checking_disabled(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        val = config.get("defaults", "host_key_checking").strip().lower()
        assert val == "false", f"host_key_checking should be False, got {val}"

    def test_vault_password_file_configured(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        vpf = config.get("defaults", "vault_password_file").strip()
        if not os.path.isabs(vpf):
            vpf = os.path.join(PROJECT_DIR, vpf)
        assert os.path.exists(vpf), f"Vault password file not found: {vpf}"

    def test_become_method_sudo(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        val = config.get("privilege_escalation", "become_method").strip()
        assert val == "sudo", f"become_method should be sudo, got {val}"

    def test_become_ask_pass_false(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        val = config.get("privilege_escalation", "become_ask_pass").strip().lower()
        assert val == "false", f"become_ask_pass should be False, got {val}"


class TestInventory:
    """Verify inventory structure is correct."""

    def test_all_hosts_present(self):
        result = subprocess.run(
            ["ansible-inventory", "--list"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
        )
        assert result.returncode == 0, f"ansible-inventory failed: {result.stderr}"
        inv = json.loads(result.stdout)
        hostvars = inv.get("_meta", {}).get("hostvars", {})
        for host in ["app1", "app2", "db1", "monitor1"]:
            assert host in hostvars, f"Host {host} not in inventory"

    def test_production_group_exists(self):
        result = subprocess.run(
            ["ansible-inventory", "--graph"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
        )
        assert result.returncode == 0
        assert "production" in result.stdout, "production group not found in inventory"

    def test_production_has_children(self):
        result = subprocess.run(
            ["ansible-inventory", "--list"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
        )
        inv = json.loads(result.stdout)
        prod = inv.get("production", {})
        children = prod.get("children", [])
        assert "webservers" in children, "webservers not child of production"
        assert "databases" in children, "databases not child of production"

    def test_webservers_hosts(self):
        result = subprocess.run(
            ["ansible-inventory", "--list"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
        )
        inv = json.loads(result.stdout)
        ws = inv.get("webservers", {})
        hosts = ws.get("hosts", [])
        assert "app1" in hosts
        assert "app2" in hosts

    def test_databases_hosts(self):
        result = subprocess.run(
            ["ansible-inventory", "--list"],
            capture_output=True,
            text=True,
            cwd=PROJECT_DIR,
        )
        inv = json.loads(result.stdout)
        db = inv.get("databases", {})
        hosts = db.get("hosts", [])
        assert "db1" in hosts


class TestVault:
    """Verify vault is properly created and encrypted."""

    def test_vault_file_exists(self):
        assert os.path.exists(f"{PROJECT_DIR}/vars/vault.yml")

    def test_vault_is_encrypted(self):
        with open(f"{PROJECT_DIR}/vars/vault.yml") as f:
            content = f.read()
        assert "$ANSIBLE_VAULT" in content, "Vault file is not encrypted"

    def test_vault_password_file_exists(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        vpf = config.get("defaults", "vault_password_file").strip()
        if not os.path.isabs(vpf):
            vpf = os.path.join(PROJECT_DIR, vpf)
        assert os.path.exists(vpf), f"Vault password file not found: {vpf}"

    def test_vault_decryptable_with_correct_contents(self):
        config = configparser.ConfigParser()
        config.read(f"{PROJECT_DIR}/ansible.cfg")
        vpf = config.get("defaults", "vault_password_file").strip()
        if not os.path.isabs(vpf):
            vpf = os.path.join(PROJECT_DIR, vpf)

        result = subprocess.run(
            [
                "ansible-vault",
                "view",
                f"{PROJECT_DIR}/vars/vault.yml",
                "--vault-password-file",
                vpf,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Cannot decrypt vault: {result.stderr}"
        assert "vault_db_password" in result.stdout
        assert "S3cur3P@ss2024!" in result.stdout
        assert "vault_api_key" in result.stdout
        assert "ak-7f3d9e2b1a4c8d5e" in result.stdout
        assert "vault_backup_passphrase" in result.stdout
        assert "bkp-X9mK2pL7" in result.stdout


class TestRoleStructure:
    """Verify role directory structure and required patterns."""

    def test_role_directory_exists(self):
        assert os.path.isdir(f"{PROJECT_DIR}/roles/site_deploy")

    def test_role_has_tasks(self):
        assert os.path.exists(f"{PROJECT_DIR}/roles/site_deploy/tasks/main.yml")

    def test_role_has_handlers(self):
        assert os.path.exists(f"{PROJECT_DIR}/roles/site_deploy/handlers/main.yml")

    def test_role_has_template(self):
        locations = [
            f"{PROJECT_DIR}/roles/site_deploy/templates/app_config.conf.j2",
            f"{PROJECT_DIR}/templates/app_config.conf.j2",
        ]
        assert any(
            os.path.exists(p) for p in locations
        ), "app_config.conf.j2 not found in role or project templates"

    def test_role_uses_block_rescue(self):
        with open(f"{PROJECT_DIR}/roles/site_deploy/tasks/main.yml") as f:
            content = f.read()
        assert "block" in content, "Role must use block for error handling"
        assert "rescue" in content, "Role must use rescue for error handling"


class TestSystemState:
    """Verify system state after playbook execution."""

    def test_group_appadmin_exists(self):
        group = grp.getgrnam("appadmin")
        assert group.gr_gid == 5000, f"appadmin GID should be 5000, got {group.gr_gid}"

    def test_user_deployer_exists(self):
        user = pwd.getpwnam("deployer")
        assert user.pw_uid == 5001, f"deployer UID should be 5001, got {user.pw_uid}"

    def test_user_deployer_shell(self):
        user = pwd.getpwnam("deployer")
        assert (
            user.pw_shell == "/bin/bash"
        ), f"deployer shell should be /bin/bash, got {user.pw_shell}"

    def test_user_deployer_primary_group(self):
        user = pwd.getpwnam("deployer")
        group = grp.getgrgid(user.pw_gid)
        assert (
            group.gr_name == "appadmin"
        ), f"deployer primary group should be appadmin, got {group.gr_name}"

    def test_user_svcaccount_exists(self):
        user = pwd.getpwnam("svcaccount")
        assert (
            user.pw_uid == 5002
        ), f"svcaccount UID should be 5002, got {user.pw_uid}"

    def test_user_svcaccount_shell(self):
        user = pwd.getpwnam("svcaccount")
        assert user.pw_shell in (
            "/sbin/nologin",
            "/usr/sbin/nologin",
        ), f"svcaccount shell should be nologin, got {user.pw_shell}"

    def test_webapp_directory_exists(self):
        assert os.path.isdir("/opt/webapp")

    def test_webapp_directory_setgid(self):
        stat = os.stat("/opt/webapp")
        assert stat.st_mode & 0o2000, "setgid bit not set on /opt/webapp"

    def test_webapp_directory_permissions(self):
        stat = os.stat("/opt/webapp")
        perms = oct(stat.st_mode)[-4:]
        assert perms == "2775", f"Expected permissions 2775, got {perms}"

    def test_webapp_directory_ownership(self):
        stat = os.stat("/opt/webapp")
        owner = pwd.getpwuid(stat.st_uid).pw_name
        group = grp.getgrgid(stat.st_gid).gr_name
        assert owner == "deployer", f"Expected owner deployer, got {owner}"
        assert group == "appadmin", f"Expected group appadmin, got {group}"

    def test_webapp_subdirectories(self):
        for subdir in ["config", "data", "logs"]:
            path = f"/opt/webapp/{subdir}"
            assert os.path.isdir(path), f"Directory {path} does not exist"


class TestConfigContent:
    """Verify config file content from template rendering."""

    def _find_config_files(self):
        config_dir = "/opt/webapp/config"
        if not os.path.isdir(config_dir):
            return []
        return sorted([f for f in os.listdir(config_dir) if f.endswith(".conf")])

    def test_config_files_exist(self):
        configs = self._find_config_files()
        assert len(configs) >= 4, (
            f"Expected at least 4 config files (app1, app2, db1, monitor1), "
            f"found {len(configs)}: {configs}"
        )

    def test_each_host_has_config(self):
        """Every inventory host must have its own config file."""
        for hostname in ["app1", "app2", "db1", "monitor1"]:
            cfg_path = f"/opt/webapp/config/{hostname}.conf"
            assert os.path.exists(cfg_path), (
                f"{hostname}.conf not found at /opt/webapp/config/"
            )

    def test_config_has_application_section(self):
        configs = self._find_config_files()
        assert len(configs) > 0, "No config files to check"
        for cfg in configs:
            path = f"/opt/webapp/config/{cfg}"
            with open(path) as f:
                content = f.read()
            assert "[application]" in content, f"{cfg} missing [application] section"

    def test_config_has_paths_section(self):
        configs = self._find_config_files()
        assert len(configs) > 0
        for cfg in configs:
            path = f"/opt/webapp/config/{cfg}"
            with open(path) as f:
                content = f.read()
            assert "[paths]" in content, f"{cfg} missing [paths] section"

    def test_config_has_cluster_members(self):
        configs = self._find_config_files()
        assert len(configs) > 0
        path = f"/opt/webapp/config/{configs[0]}"
        with open(path) as f:
            content = f.read()
        assert "[cluster_members]" in content
        assert "app1" in content, "cluster_members should list app1"
        assert "app2" in content, "cluster_members should list app2"

    def test_template_variables_rendered(self):
        """No raw Jinja2 template variables should remain in config files."""
        configs = self._find_config_files()
        for cfg in configs:
            path = f"/opt/webapp/config/{cfg}"
            with open(path) as f:
                content = f.read()
            assert "{{" not in content, f"Unrendered template variable in {cfg}"
            assert "{%" not in content, f"Unrendered template tag in {cfg}"

    def test_production_hosts_have_database_section(self):
        """Production hosts (app1, app2, db1) should have [database] with vault password."""
        for hostname in ["app1", "app2", "db1"]:
            cfg_path = f"/opt/webapp/config/{hostname}.conf"
            if not os.path.exists(cfg_path):
                continue
            with open(cfg_path) as f:
                content = f.read()
            assert "[database]" in content, (
                f"{hostname}.conf should have [database] section "
                f"(host is in production group)"
            )
            assert "S3cur3P@ss2024!" in content, (
                f"{hostname}.conf [database] should contain rendered vault_db_password"
            )

    def test_monitoring_host_has_monitoring_section(self):
        """monitor1 should have [monitoring] section, not [database]."""
        cfg_path = "/opt/webapp/config/monitor1.conf"
        if not os.path.exists(cfg_path):
            pytest.skip("monitor1.conf not found")
        with open(cfg_path) as f:
            content = f.read()
        assert "[monitoring]" in content, (
            "monitor1.conf should have [monitoring] section"
        )
        assert "[database]" not in content, (
            "monitor1.conf should NOT have [database] section "
            "(monitor1 is not in production group)"
        )

    def test_production_hosts_environment_name(self):
        """All production hosts must render PRODUCTION as their environment."""
        for hostname in ["app1", "app2", "db1"]:
            cfg_path = f"/opt/webapp/config/{hostname}.conf"
            if not os.path.exists(cfg_path):
                pytest.fail(f"{hostname}.conf not found")
            with open(cfg_path) as f:
                content = f.read()
            assert "PRODUCTION" in content, (
                f"{hostname}.conf should contain PRODUCTION as environment name"
            )

    def test_monitoring_host_environment_name(self):
        """monitor1 must render MONITORING as its environment."""
        cfg_path = "/opt/webapp/config/monitor1.conf"
        if not os.path.exists(cfg_path):
            pytest.skip("monitor1.conf not found")
        with open(cfg_path) as f:
            content = f.read()
        assert "MONITORING" in content, (
            "monitor1.conf should contain MONITORING as environment name"
        )

    def test_environment_rendered_uppercase(self):
        """env_name should be rendered uppercase via Jinja2 upper filter."""
        configs = self._find_config_files()
        assert len(configs) > 0
        found_upper = False
        for cfg in configs:
            path = f"/opt/webapp/config/{cfg}"
            with open(path) as f:
                content = f.read()
            if "PRODUCTION" in content or "MONITORING" in content:
                found_upper = True
                break
        assert found_upper, (
            "No config file has uppercased environment name "
            "(expected PRODUCTION or MONITORING from env_name | upper)"
        )


class TestReportContent:
    """Verify system report was generated."""

    def test_report_file_exists(self):
        assert os.path.exists(
            "/opt/webapp/system_report.txt"
        ), "System report not found at /opt/webapp/system_report.txt"

    def test_report_contains_system_info(self):
        with open("/opt/webapp/system_report.txt") as f:
            content = f.read()
        content_lower = content.lower()
        assert (
            "hostname" in content_lower or "host" in content_lower
        ), "Report should contain hostname information"
        assert (
            "memory" in content_lower or "mem" in content_lower
        ), "Report should contain memory information"

    def test_report_no_template_vars(self):
        with open("/opt/webapp/system_report.txt") as f:
            content = f.read()
        assert "{{" not in content, "Report contains unrendered template variables"
