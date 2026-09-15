"""
"""

import subprocess
import json
import os
import hashlib
import importlib.util


class TestInventoryPlugin:
    """Test the custom fleet inventory plugin and its computed values."""

    def _get_inventory(self):
        env = {**os.environ, "ANSIBLE_CONFIG": "/app/project/ansible.cfg"}
        result = subprocess.run(
            ["ansible-inventory", "-i", "/app/project/fleet_inventory.yml", "--list"],
            capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"ansible-inventory failed: {result.stderr}"
        return json.loads(result.stdout)

    def test_plugin_file_exists(self):
        assert os.path.isfile("/app/project/plugins/inventory/fleet.py")

    def test_inventory_config_exists(self):
        assert os.path.isfile("/app/project/fleet_inventory.yml")

    def test_datacenter_groups(self):
        data = self._get_inventory()
        for dc in ["us_east_1", "us_west_2"]:
            assert dc in data, f"Missing datacenter group '{dc}'"

    def test_us_east_1_has_three_hosts(self):
        data = self._get_inventory()
        hosts = data.get("us_east_1", {}).get("hosts", [])
        assert len(hosts) == 3, f"Expected 3 us_east_1 hosts, got {len(hosts)}"

    def test_us_west_2_has_two_hosts(self):
        data = self._get_inventory()
        hosts = data.get("us_west_2", {}).get("hosts", [])
        assert len(hosts) == 2, f"Expected 2 us_west_2 hosts, got {len(hosts)}"

    def test_role_groups_exist(self):
        data = self._get_inventory()
        for role in ["webserver", "database", "cache", "application", "monitoring"]:
            assert role in data, f"Missing role group '{role}'"

    def test_compound_group_exists(self):
        data = self._get_inventory()
        assert "us_east_1_webserver" in data, \
            "Missing compound group 'us_east_1_webserver'"
        hosts = data["us_east_1_webserver"].get("hosts", [])
        assert "localhost" in hosts

    def test_excludes_decommissioned(self):
        data = self._get_inventory()
        all_hosts = set()
        for key, val in data.items():
            if isinstance(val, dict) and "hosts" in val:
                all_hosts.update(val["hosts"])
        assert "legacy-db" not in all_hosts, \
            "Decommissioned host 'legacy-db' should be excluded"

    def test_host_connection_local(self):
        data = self._get_inventory()
        meta = data.get("_meta", {})
        hostvars = meta.get("hostvars", {})
        lh = hostvars.get("localhost", {})
        assert lh.get("ansible_connection") == "local"

    def test_capacity_utilization_localhost(self):
        """localhost: cpu 3/4=0.75, mem 6G/8G=0.75, disk 80G/100G=0.8
        capacity = 0.75*40 + 0.75*35 + 0.8*25 = 30+26.25+20 = 76.25"""
        data = self._get_inventory()
        meta = data.get("_meta", {}).get("hostvars", {})
        util = meta.get("localhost", {}).get("capacity_utilization")
        assert util is not None, "Missing capacity_utilization for localhost"
        assert abs(util - 76.25) < 0.01, f"Expected 76.25, got {util}"

    def test_capacity_utilization_db_primary(self):
        """db-primary: cpu 7/8=0.875, mem 12G/16G=0.75, disk 150G/200G=0.75
        capacity = 0.875*40 + 0.75*35 + 0.75*25 = 35+26.25+18.75 = 80.00"""
        data = self._get_inventory()
        meta = data.get("_meta", {}).get("hostvars", {})
        util = meta.get("db-primary", {}).get("capacity_utilization")
        assert util is not None, "Missing capacity_utilization for db-primary"
        assert abs(util - 80.0) < 0.01, f"Expected 80.00, got {util}"

    def test_capacity_utilization_cache_node(self):
        """cache-node: cpu 1/4=0.25, mem 4G/16G=0.25, disk 25G/100G=0.25
        capacity = 0.25*40 + 0.25*35 + 0.25*25 = 10+8.75+6.25 = 25.00"""
        data = self._get_inventory()
        meta = data.get("_meta", {}).get("hostvars", {})
        util = meta.get("cache-node", {}).get("capacity_utilization")
        assert util is not None, "Missing capacity_utilization for cache-node"
        assert abs(util - 25.0) < 0.01, f"Expected 25.00, got {util}"

    def test_usable_hosts_localhost(self):
        """/23 -> 2^9 - 2 = 510"""
        data = self._get_inventory()
        meta = data.get("_meta", {}).get("hostvars", {})
        hosts = meta.get("localhost", {}).get("usable_hosts")
        assert hosts == 510, f"Expected 510 usable hosts, got {hosts}"

    def test_usable_hosts_db_primary(self):
        """/22 -> 2^10 - 2 = 1022"""
        data = self._get_inventory()
        meta = data.get("_meta", {}).get("hostvars", {})
        hosts = meta.get("db-primary", {}).get("usable_hosts")
        assert hosts == 1022, f"Expected 1022 usable hosts, got {hosts}"

    def test_usable_hosts_monitor(self):
        """/28 -> 2^4 - 2 = 14"""
        data = self._get_inventory()
        meta = data.get("_meta", {}).get("hostvars", {})
        hosts = meta.get("monitor-srv", {}).get("usable_hosts")
        assert hosts == 14, f"Expected 14 usable hosts, got {hosts}"


class TestFilterPlugin:
    """Test the custom compliance filter plugins."""

    def _load_filters(self):
        spec = importlib.util.spec_from_file_location(
            "compliance_filters",
            "/app/project/plugins/filter/compliance_filters.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.FilterModule().filters()

    def test_plugin_file_exists(self):
        assert os.path.isfile("/app/project/plugins/filter/compliance_filters.py")

    def test_risk_grade_a(self):
        filters = self._load_filters()
        assert filters["risk_grade"](12) == "A"
        assert filters["risk_grade"](20) == "A"

    def test_risk_grade_b(self):
        filters = self._load_filters()
        assert filters["risk_grade"](35) == "B"

    def test_risk_grade_c(self):
        filters = self._load_filters()
        assert filters["risk_grade"](45) == "C"

    def test_risk_grade_d(self):
        filters = self._load_filters()
        assert filters["risk_grade"](72) == "D"

    def test_risk_grade_f(self):
        filters = self._load_filters()
        assert filters["risk_grade"](95) == "F"

    def test_capacity_status_green(self):
        filters = self._load_filters()
        assert filters["capacity_status"](25.0) == "green"
        assert filters["capacity_status"](59.99) == "green"

    def test_capacity_status_yellow(self):
        filters = self._load_filters()
        assert filters["capacity_status"](60.0) == "yellow"
        assert filters["capacity_status"](76.25) == "yellow"

    def test_capacity_status_red(self):
        filters = self._load_filters()
        assert filters["capacity_status"](80.0) == "red"
        assert filters["capacity_status"](88.125) == "red"

    def test_cidr_host_count_23(self):
        filters = self._load_filters()
        assert filters["cidr_host_count"]("10.10.0.0/23") == 510

    def test_cidr_host_count_22(self):
        filters = self._load_filters()
        assert filters["cidr_host_count"]("10.20.0.0/22") == 1022

    def test_cidr_host_count_28(self):
        filters = self._load_filters()
        assert filters["cidr_host_count"]("10.50.0.0/28") == 14

    def test_cidr_host_count_20(self):
        filters = self._load_filters()
        assert filters["cidr_host_count"]("10.40.0.0/20") == 4094

    def test_mask_credential_standard(self):
        filters = self._load_filters()
        result = filters["mask_credential"]("Pg_m4st3r_2024!")
        assert result == "Pg_**********4!", f"Got: {result}"

    def test_mask_credential_token(self):
        filters = self._load_filters()
        result = filters["mask_credential"]("tok-9f8e7d6c5b4a3210")
        assert result == "tok***************10", f"Got: {result}"

    def test_mask_credential_short(self):
        filters = self._load_filters()
        result = filters["mask_credential"]("abc")
        assert result == "***"

    def test_mask_credential_exactly_five(self):
        filters = self._load_filters()
        result = filters["mask_credential"]("abcde")
        assert result == "*****"

    def test_mask_credential_six(self):
        filters = self._load_filters()
        result = filters["mask_credential"]("abcdef")
        assert result == "abc*ef"

    def test_sha256_digest(self):
        filters = self._load_filters()
        expected = hashlib.sha256("test_input".encode()).hexdigest()
        assert filters["sha256_digest"]("test_input") == expected

    def test_sha256_digest_empty(self):
        filters = self._load_filters()
        expected = hashlib.sha256("".encode()).hexdigest()
        assert filters["sha256_digest"]("") == expected


class TestCustomModule:
    """Test the custom fleet_validate module and its validation output."""

    def test_module_file_exists(self):
        assert os.path.isfile("/app/project/plugins/modules/fleet_validate.py")

    def test_module_has_check_mode_support(self):
        with open("/app/project/plugins/modules/fleet_validate.py") as f:
            content = f.read()
        assert "supports_check_mode" in content, \
            "Module must declare supports_check_mode"

    def test_module_has_capacity_weights_param(self):
        with open("/app/project/plugins/modules/fleet_validate.py") as f:
            content = f.read()
        assert "capacity_weights" in content, \
            "Module must accept capacity_weights parameter"

    def test_validation_results_exist(self):
        assert os.path.isfile("/app/project/validation_results.json"), \
            "validation_results.json not generated"

    def test_validation_results_valid_json(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_all_active_hosts_validated(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        for host in ["localhost", "db-primary", "cache-node",
                      "app-worker-01", "monitor-srv"]:
            assert host in data, f"Missing host '{host}' in validation results"

    def test_no_decommissioned_in_results(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert "legacy-db" not in data, \
            "Decommissioned host should not appear in validation results"

    def test_localhost_compliant(self):
        """localhost: capacity 76.25 < 80, risk 35 <= 50 -> compliant"""
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert data["localhost"]["compliant"] is True, \
            f"localhost should be compliant, got: {data['localhost']}"

    def test_db_primary_non_compliant(self):
        """db-primary: capacity 80.00 >= 80 AND risk 72 > 50 -> non-compliant"""
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert data["db-primary"]["compliant"] is False, \
            f"db-primary should be non-compliant, got: {data['db-primary']}"

    def test_db_primary_has_two_violations(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        violations = data["db-primary"]["violations"]
        assert len(violations) == 2, \
            f"Expected 2 violations for db-primary, got {len(violations)}: {violations}"

    def test_cache_node_compliant(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert data["cache-node"]["compliant"] is True

    def test_app_worker_compliant(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert data["app-worker-01"]["compliant"] is True

    def test_monitor_compliant(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        assert data["monitor-srv"]["compliant"] is True

    def test_capacity_utilization_in_results(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        for host in ["localhost", "db-primary", "cache-node",
                      "app-worker-01", "monitor-srv"]:
            assert "capacity_utilization" in data[host], \
                f"Missing capacity_utilization for {host}"

    def test_localhost_capacity_value(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        util = data["localhost"]["capacity_utilization"]
        assert abs(util - 76.25) < 0.01, f"Expected 76.25, got {util}"

    def test_db_primary_capacity_value(self):
        with open("/app/project/validation_results.json") as f:
            data = json.load(f)
        util = data["db-primary"]["capacity_utilization"]
        assert abs(util - 80.0) < 0.01, f"Expected 80.0, got {util}"


class TestCallbackPlugin:
    """Test the custom fleet_audit callback plugin."""

    def test_callback_file_exists(self):
        assert os.path.isfile("/app/project/plugins/callback/fleet_audit.py")

    def test_callback_has_required_attributes(self):
        with open("/app/project/plugins/callback/fleet_audit.py") as f:
            content = f.read()
        assert "CALLBACK_VERSION" in content, \
            "Callback must declare CALLBACK_VERSION"
        assert "CALLBACK_TYPE" in content, \
            "Callback must declare CALLBACK_TYPE"
        assert "CALLBACK_NAME" in content, \
            "Callback must declare CALLBACK_NAME"
        assert "CallbackBase" in content, \
            "Callback must inherit from CallbackBase"

    def test_audit_log_exists(self):
        assert os.path.isfile("/app/project/audit_log.json"), \
            "audit_log.json not generated by callback"

    def test_audit_log_valid_json(self):
        with open("/app/project/audit_log.json") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_audit_log_has_task_count(self):
        with open("/app/project/audit_log.json") as f:
            data = json.load(f)
        assert "tasks_ok" in data, "Audit log missing tasks_ok field"
        assert data["tasks_ok"] > 0, "Audit log should have at least one successful task"

    def test_audit_log_has_task_log(self):
        with open("/app/project/audit_log.json") as f:
            data = json.load(f)
        assert "task_log" in data, "Audit log missing task_log field"
        assert isinstance(data["task_log"], list)
        assert len(data["task_log"]) > 0, "Audit log task_log should not be empty"


class TestVault:
    """Test vault operations."""

    def test_secrets_file_exists(self):
        assert os.path.isfile("/app/project/secrets.yml")

    def test_secrets_file_encrypted(self):
        with open("/app/project/secrets.yml") as f:
            content = f.read()
        assert "$ANSIBLE_VAULT" in content, "secrets.yml is not encrypted"

    def test_vault_password_file(self):
        assert os.path.isfile("/app/project/vault_pass.txt")
        with open("/app/project/vault_pass.txt") as f:
            password = f.read().strip()
        assert password == "Fl33t_N3w!_S3cur3"

    def test_vault_decrypts_with_new_password(self):
        result = subprocess.run(
            ["ansible-vault", "view",
             "--vault-password-file=/app/project/vault_pass.txt",
             "/app/project/secrets.yml"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Vault decrypt failed: {result.stderr}"

    def test_vault_contains_original_variables(self):
        result = subprocess.run(
            ["ansible-vault", "view",
             "--vault-password-file=/app/project/vault_pass.txt",
             "/app/project/secrets.yml"],
            capture_output=True, text=True
        )
        assert "db_master_password" in result.stdout
        assert "Pg_m4st3r_2024!" in result.stdout
        assert "api_token" in result.stdout
        assert "tok-9f8e7d6c5b4a3210" in result.stdout
        assert "tls_passphrase" in result.stdout
        assert "X7kL9mN2pQ4r" in result.stdout

    def test_vault_contains_new_variables(self):
        result = subprocess.run(
            ["ansible-vault", "view",
             "--vault-password-file=/app/project/vault_pass.txt",
             "/app/project/secrets.yml"],
            capture_output=True, text=True
        )
        assert "backup_key" in result.stdout
        assert "bk-alpha-7742-omega" in result.stdout
        assert "deploy_token" in result.stdout
        assert "dpt-2024-xK9mL3nP" in result.stdout


class TestCapacityAudit:
    """Test capacity audit role system state."""

    def test_groups_created(self):
        for group in ["sysops", "appteam", "dbteam"]:
            result = subprocess.run(
                ["getent", "group", group],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"Group '{group}' not found"

    def test_users_created(self):
        for user in ["svc_deploy", "svc_monitor", "svc_backup"]:
            result = subprocess.run(
                ["getent", "passwd", user],
                capture_output=True, text=True
            )
            assert result.returncode == 0, f"User '{user}' not found"

    def test_user_uids(self):
        expected = {
            "svc_deploy": "6001",
            "svc_monitor": "6002",
            "svc_backup": "6003",
        }
        for user, uid in expected.items():
            result = subprocess.run(
                ["id", "-u", user],
                capture_output=True, text=True
            )
            assert result.stdout.strip() == uid, \
                f"User {user} has UID {result.stdout.strip()}, expected {uid}"

    def test_user_group_membership(self):
        expected = {
            "svc_deploy": "appteam",
            "svc_monitor": "sysops",
            "svc_backup": "dbteam",
        }
        for user, group in expected.items():
            result = subprocess.run(
                ["id", "-Gn", user],
                capture_output=True, text=True
            )
            assert group in result.stdout, \
                f"User {user} not in group {group}. Groups: {result.stdout.strip()}"

    def test_sysctl_swappiness(self):
        assert os.path.isfile("/etc/sysctl.d/99-fleet-tuning.conf")
        with open("/etc/sysctl.d/99-fleet-tuning.conf") as f:
            content = f.read()
        assert "vm.swappiness" in content and "10" in content

    def test_sysctl_somaxconn(self):
        with open("/etc/sysctl.d/99-fleet-tuning.conf") as f:
            content = f.read()
        assert "net.core.somaxconn" in content and "65535" in content

    def test_sysctl_file_max(self):
        with open("/etc/sysctl.d/99-fleet-tuning.conf") as f:
            content = f.read()
        assert "fs.file-max" in content and "2097152" in content

    def test_motd_exists(self):
        assert os.path.isfile("/etc/motd")

    def test_motd_contains_masked_token(self):
        with open("/etc/motd") as f:
            content = f.read()
        # api_token "tok-9f8e7d6c5b4a3210" masked: "tok***************10"
        assert "tok" in content, "MOTD should contain start of masked API token"
        assert "*" * 5 in content, "MOTD should contain asterisks from mask_credential"


class TestComplianceCheck:
    """Test compliance check role system state."""

    def test_nginx_installed(self):
        result = subprocess.run(
            ["which", "nginx"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, "nginx not installed"

    def test_nginx_config_valid(self):
        result = subprocess.run(
            ["nginx", "-t"],
            capture_output=True, text=True
        )
        combined = result.stdout + result.stderr
        assert "successful" in combined or result.returncode == 0, \
            f"nginx config invalid: {combined}"

    def test_fleet_config_exists(self):
        assert os.path.isfile("/etc/app/fleet_config.yml")

    def test_fleet_config_contains_db_password(self):
        with open("/etc/app/fleet_config.yml") as f:
            content = f.read()
        assert "Pg_m4st3r_2024!" in content, "Fleet config missing db_master_password"

    def test_fleet_config_contains_api_token(self):
        with open("/etc/app/fleet_config.yml") as f:
            content = f.read()
        assert "tok-9f8e7d6c5b4a3210" in content, "Fleet config missing api_token"

    def test_fleet_config_contains_backup_key(self):
        with open("/etc/app/fleet_config.yml") as f:
            content = f.read()
        assert "bk-alpha-7742-omega" in content, "Fleet config missing backup_key"

    def test_nginx_http_fallback(self):
        config_path = "/etc/nginx/sites-available/fleet"
        assert os.path.isfile(config_path), f"{config_path} not found"
        with open(config_path) as f:
            content = f.read()
        assert "ssl_certificate" not in content, \
            "Nginx should use HTTP fallback (no SSL)"
        assert "8080" in content, \
            "Fallback config should listen on port 8080"

    def test_web_content(self):
        assert os.path.isfile("/var/www/fleet/index.html")


class TestComplianceReport:
    """Test the generated compliance report with computed values."""

    def _read_report(self):
        path = "/app/project/compliance_report.txt"
        assert os.path.isfile(path), "Compliance report not generated"
        with open(path) as f:
            return f.read()

    def test_report_exists(self):
        assert os.path.isfile("/app/project/compliance_report.txt")

    def test_report_localhost_capacity(self):
        """Verify computed capacity for localhost: 76.25%"""
        content = self._read_report()
        assert "76.25" in content, "Report missing localhost capacity 76.25"

    def test_report_db_primary_capacity(self):
        """Verify computed capacity for db-primary: 80.00%"""
        content = self._read_report()
        assert "80.00" in content, "Report missing db-primary capacity 80.00"

    def test_report_cache_node_capacity(self):
        """Verify computed capacity for cache-node: 25.00%"""
        content = self._read_report()
        assert "25.00" in content, "Report missing cache-node capacity 25.00"

    def test_report_app_worker_capacity(self):
        """Verify computed capacity for app-worker-01: 68.75%"""
        content = self._read_report()
        assert "68.75" in content, "Report missing app-worker-01 capacity 68.75"

    def test_report_monitor_capacity(self):
        """Verify computed capacity for monitor-srv: 50.00%"""
        content = self._read_report()
        assert "50.00" in content, "Report missing monitor-srv capacity 50.00"

    def test_report_capacity_statuses(self):
        content = self._read_report()
        assert "yellow" in content, "Report missing 'yellow' capacity status"
        assert "red" in content, "Report missing 'red' capacity status"
        assert "green" in content, "Report missing 'green' capacity status"

    def test_report_risk_grades(self):
        content = self._read_report()
        for grade in ["A", "B", "C", "D"]:
            assert grade in content, f"Report missing risk grade '{grade}'"

    def test_report_usable_hosts_values(self):
        content = self._read_report()
        assert "510" in content, "Report missing usable hosts 510 (localhost /23)"
        assert "1022" in content, "Report missing usable hosts 1022 (db-primary /22)"
        assert "4094" in content, "Report missing usable hosts 4094 (app-worker /20)"

    def test_report_excludes_decommissioned(self):
        content = self._read_report()
        assert "legacy-db" not in content, "Report should exclude decommissioned host"

    def test_report_masked_secrets(self):
        content = self._read_report()
        # db_master_password "Pg_m4st3r_2024!" -> "Pg_**********4!"
        assert "Pg_" in content and "4!" in content, \
            "Report missing masked db_master_password"
        assert "*" * 8 in content, "Report should contain asterisks from masking"

    def test_report_contains_all_active_hosts(self):
        content = self._read_report()
        for hostname in ["localhost", "db-primary", "cache-node",
                         "app-worker-01", "monitor-srv"]:
            assert hostname in content, \
                f"Report missing active host '{hostname}'"


class TestAnsibleConfig:
    """Test ansible.cfg configuration."""

    def test_ansible_cfg_exists(self):
        assert os.path.isfile("/app/project/ansible.cfg")

    def test_ansible_cfg_has_plugin_paths(self):
        with open("/app/project/ansible.cfg") as f:
            content = f.read().lower()
        assert "inventory_plugins" in content or "inventory_plugin" in content
        assert "filter_plugins" in content or "filter_plugin" in content

    def test_ansible_cfg_has_module_path(self):
        with open("/app/project/ansible.cfg") as f:
            content = f.read().lower()
        assert "library" in content, \
            "ansible.cfg must configure library path for custom modules"

    def test_ansible_cfg_has_callback_config(self):
        with open("/app/project/ansible.cfg") as f:
            content = f.read().lower()
        assert "callback_plugins" in content, \
            "ansible.cfg must configure callback_plugins path"
        assert "callbacks_enabled" in content or "callback_whitelist" in content, \
            "ansible.cfg must enable the fleet_audit callback"
