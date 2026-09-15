
import subprocess
import os
import pytest


def run(cmd):
    """Run a shell command and return (stdout, returncode)."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.returncode


def get_shadow_field(user, field_index):
    """Get a specific field from /etc/shadow for a user.
    Fields: 0=name, 1=password, 2=lastchange, 3=min, 4=max, 5=warn,
            6=inactive, 7=expire
    """
    output, rc = run(f"getent shadow {user}")
    if rc != 0:
        return None
    fields = output.split(":")
    if len(fields) > field_index:
        return fields[field_index]
    return None


HUMAN_USERS = ["admin", "developer1", "developer2", "webadmin"]
SERVICE_ACCOUNTS = ["svc_monitor", "svc_deploy", "svc_backup"]
ALL_USERS = HUMAN_USERS + SERVICE_ACCOUNTS


# ===========================================================================
# SECTION 1: SUDO SECURITY
# ===========================================================================
class TestSudoSecurity:
    def test_no_dangerous_env_keep(self):
        """Policy 1.4: sudo must not pass through LD_PRELOAD or LD_LIBRARY_PATH"""
        output, _ = run(
            "cat /etc/sudoers /etc/sudoers.d/* 2>/dev/null || true"
        )
        output_lower = output.lower()
        assert "ld_preload" not in output_lower, (
            "LD_PRELOAD found in sudoers — allows library injection via sudo"
        )
        assert "ld_library_path" not in output_lower, (
            "LD_LIBRARY_PATH found in sudoers — allows library injection via sudo"
        )

    def test_no_unscoped_vim_wildcard(self):
        """Policy 1.2: vim with unscoped wildcard enables shell escape to root"""
        output, _ = run("cat /etc/sudoers.d/* 2>/dev/null || true")
        assert "/usr/bin/vim *" not in output, (
            "Unscoped 'vim *' in sudoers allows privilege escalation via :!bash"
        )

    def test_no_unscoped_docker_wildcard(self):
        """Policy 1.2: docker with unscoped wildcard allows host filesystem access"""
        output, _ = run("cat /etc/sudoers.d/* 2>/dev/null || true")
        assert "docker *" not in output, (
            "Unscoped 'docker *' in sudoers allows arbitrary host access"
        )

    def test_monitoring_not_unrestricted(self):
        """Policy 1.3: non-admin groups must not have NOPASSWD: ALL"""
        output, _ = run("cat /etc/sudoers.d/* 2>/dev/null || true")
        for line in output.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and "%monitoring" in line:
                assert "NOPASSWD: ALL" not in line, (
                    f"monitoring group has unrestricted sudo: {line}"
                )

    def test_all_sudoers_files_correct_permissions(self):
        """Policy 1.5: all sudoers.d files must have mode 0440"""
        output, rc = run(
            "find /etc/sudoers.d/ -type f -not -name 'README*' "
            "-exec stat -c '%n %a' {} \\;"
        )
        if rc != 0 or not output.strip():
            return
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.rsplit(" ", 1)
            filename = parts[0]
            mode = parts[1]
            assert mode == "440", (
                f"{filename} has mode {mode}, expected 440"
            )

    def test_all_sudoers_files_root_owned(self):
        """Policy 1.5: all sudoers.d files must be owned root:root"""
        output, rc = run(
            "find /etc/sudoers.d/ -type f -not -name 'README*' "
            "-exec stat -c '%n %U:%G' {} \\;"
        )
        if rc != 0 or not output.strip():
            return
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.rsplit(" ", 1)
            filename = parts[0]
            ownership = parts[1]
            assert ownership == "root:root", (
                f"{filename} owned by {ownership}, expected root:root"
            )

    def test_visudo_syntax_valid(self):
        """Policy 1.6: all sudoers config must pass syntax validation"""
        _, rc = run("visudo -c 2>&1")
        assert rc == 0, "sudoers files must pass visudo -c syntax check"


# ===========================================================================
# SECTION 2: FILE SYSTEM SECURITY
# ===========================================================================
class TestFilePermissions:
    def test_deploy_script_no_suid(self):
        """Policy 2.1: no SUID on writable files"""
        output, _ = run("stat -c '%a' /opt/scripts/deploy.sh 2>/dev/null")
        if not output:
            return
        # SUID would make first digit 4+ (e.g., 4777)
        assert len(output) <= 3 or output[0] in "0123", (
            f"deploy.sh has SUID bit set (mode {output})"
        )

    def test_deploy_script_not_world_writable(self):
        """Policy 2.5: scripts must not be world-writable"""
        output, _ = run("stat -c '%a' /opt/scripts/deploy.sh 2>/dev/null")
        if not output:
            return
        last_digit = int(output[-1])
        assert last_digit & 2 == 0, (
            f"deploy.sh is world-writable (mode {output})"
        )

    def test_shadow_backup_restricted(self):
        """Policy 2.2: sensitive backups must be mode 0600 or less"""
        if not os.path.isfile("/var/backups/shadow.bak"):
            return
        output, _ = run("stat -c '%a' /var/backups/shadow.bak")
        assert output == "600", (
            f"shadow.bak has mode {output}, expected 600"
        )

    def test_log_dir_not_world_writable(self):
        """Policy 2.3: log directories must not be world-writable"""
        output, _ = run("stat -c '%a' /var/log/app")
        last_digit = int(output[-1])
        assert last_digit & 2 == 0, (
            f"/var/log/app is world-writable (mode {output})"
        )

    def test_log_dir_mode_reasonable(self):
        """Policy 2.3: log directory mode shall not exceed 0750"""
        output, _ = run("stat -c '%a' /var/log/app")
        mode_int = int(output)
        assert mode_int <= 750, (
            f"/var/log/app mode is {output}, expected <= 750"
        )

    def test_no_orphaned_files_in_opt(self):
        """Policy 2.4: no files owned by non-existent users"""
        output, _ = run("find /opt -nouser 2>/dev/null || true")
        assert output.strip() == "", (
            f"Orphaned files found: {output}"
        )

    def test_opt_scripts_owned_by_root(self):
        """Policy 2.5: /opt/scripts/ must be owned by root:root"""
        output, _ = run("stat -c '%U:%G' /opt/scripts")
        assert output == "root:root", (
            f"/opt/scripts owned by {output}, expected root:root"
        )


# ===========================================================================
# SECTION 3: SERVICE ACCOUNT CONFIGURATION
# ===========================================================================
class TestServiceAccounts:
    def test_svc_monitor_nologin(self):
        """Policy 3.1: service accounts must have non-interactive shell"""
        output, rc = run("getent passwd svc_monitor")
        assert rc == 0, "svc_monitor user does not exist"
        shell = output.split(":")[6]
        assert shell in ("/usr/sbin/nologin", "/bin/false"), (
            f"svc_monitor has shell {shell}, expected nologin"
        )

    def test_svc_backup_nologin(self):
        """Policy 3.1: service accounts must have non-interactive shell"""
        output, rc = run("getent passwd svc_backup")
        assert rc == 0, "svc_backup user does not exist"
        shell = output.split(":")[6]
        assert shell in ("/usr/sbin/nologin", "/bin/false"), (
            f"svc_backup has shell {shell}, expected nologin"
        )

    def test_svc_deploy_not_in_wheel(self):
        """Policy 3.2: service accounts must not be in wheel group"""
        output, _ = run("id -Gn svc_deploy")
        groups = output.split()
        assert "wheel" not in groups, (
            f"svc_deploy is in wheel group — privilege escalation risk"
        )


# ===========================================================================
# SECTION 4: SCHEDULED TASK SECURITY
# ===========================================================================
class TestScheduledTasks:
    def test_no_cron_d_references_tmp(self):
        """Policy 4.1: root cron jobs must not run scripts from /tmp"""
        output, _ = run("grep -rl '/tmp/' /etc/cron.d/ 2>/dev/null || true")
        assert output.strip() == "", (
            f"Cron entries reference /tmp: {output}"
        )

    def test_cron_allow_exists(self):
        """Policy 4.2: cron access must be controlled via /etc/cron.allow"""
        assert os.path.isfile("/etc/cron.allow"), (
            "/etc/cron.allow must exist for cron access control"
        )

    def test_cron_allow_contains_admin(self):
        """Policy 4.2: wheel group members (admin) must be allowed cron"""
        with open("/etc/cron.allow") as f:
            users = {line.strip() for line in f if line.strip()}
        assert "admin" in users, (
            "admin (wheel member) should be in /etc/cron.allow"
        )

    def test_cron_allow_excludes_svc_accounts(self):
        """Policy 4.2: service accounts should not have cron access"""
        if not os.path.isfile("/etc/cron.allow"):
            pytest.skip("cron.allow not found")
        with open("/etc/cron.allow") as f:
            users = {line.strip() for line in f if line.strip()}
        for svc in SERVICE_ACCOUNTS:
            assert svc not in users, (
                f"service account {svc} should not be in cron.allow"
            )

    def test_admin_crontab_no_insecure_chmod(self):
        """Policy 4.3: user crontab must not modify system permissions"""
        output, _ = run("crontab -l -u admin 2>/dev/null || echo 'no crontab'")
        assert "777" not in output, (
            f"Admin crontab contains insecure chmod 777: {output}"
        )

    def test_no_systemd_services_reference_home(self):
        """Policy 4.1/4.4: systemd services must not run scripts from /home"""
        output, _ = run(
            "grep -rl '/home/' /etc/systemd/system/*.service 2>/dev/null || true"
        )
        assert output.strip() == "", (
            f"Systemd services reference /home/: {output}"
        )


# ===========================================================================
# SECTION 5: AUTHENTICATION POLICY
# ===========================================================================
class TestPasswordPolicy:
    def test_login_defs_max_days_90(self):
        """Policy 5.1: PASS_MAX_DAYS must be 90"""
        output, _ = run("grep '^PASS_MAX_DAYS' /etc/login.defs")
        parts = output.split()
        assert len(parts) >= 2 and parts[1] == "90", (
            f"PASS_MAX_DAYS is '{output}', expected 90"
        )

    def test_login_defs_min_days_7(self):
        """Policy 5.2: PASS_MIN_DAYS must be 7"""
        output, _ = run("grep '^PASS_MIN_DAYS' /etc/login.defs")
        parts = output.split()
        assert len(parts) >= 2 and parts[1] == "7", (
            f"PASS_MIN_DAYS is '{output}', expected 7"
        )

    def test_login_defs_warn_age_14(self):
        """Policy 5.3: PASS_WARN_AGE must be 14"""
        output, _ = run("grep '^PASS_WARN_AGE' /etc/login.defs")
        parts = output.split()
        assert len(parts) >= 2 and parts[1] == "14", (
            f"PASS_WARN_AGE is '{output}', expected 14"
        )

    @pytest.mark.parametrize("user", ALL_USERS)
    def test_max_password_age_90(self, user):
        """Policy 5.4: all users must have max password age of 90"""
        val = get_shadow_field(user, 4)
        assert val == "90", (
            f"{user} max password age is {val}, expected 90"
        )

    @pytest.mark.parametrize("user", HUMAN_USERS)
    def test_min_password_age_7(self, user):
        """Policy 5.4: human users must have min password age of 7"""
        val = get_shadow_field(user, 3)
        assert val == "7", (
            f"{user} min password age is {val}, expected 7"
        )

    @pytest.mark.parametrize("user", HUMAN_USERS)
    def test_warn_period_14(self, user):
        """Policy 5.4: human users must have warning period of 14"""
        val = get_shadow_field(user, 5)
        assert val == "14", (
            f"{user} warning period is {val}, expected 14"
        )


# ===========================================================================
# SECTION 6: COMPLIANCE MONITORING
# ===========================================================================
class TestComplianceScript:
    def test_compliance_script_exists(self):
        """Policy 6.1: compliance script must exist"""
        assert os.path.isfile("/app/scripts/compliance-check.sh"), (
            "/app/scripts/compliance-check.sh not found"
        )

    def test_compliance_script_executable(self):
        """Policy 6.5: compliance script must be executable"""
        assert os.access("/app/scripts/compliance-check.sh", os.X_OK), (
            "compliance-check.sh is not executable"
        )

    def test_compliance_script_has_shebang(self):
        """Policy 6.5: compliance script must have valid shebang"""
        with open("/app/scripts/compliance-check.sh") as f:
            first_line = f.readline().strip()
        assert first_line.startswith("#!/"), (
            f"compliance-check.sh shebang: '{first_line}'"
        )

    def test_compliance_script_exits_zero(self):
        """Policy 6.3: script must exit 0 when system is compliant"""
        _, rc = run("/app/scripts/compliance-check.sh >/dev/null 2>&1")
        assert rc == 0, (
            "compliance-check.sh exited non-zero — system may not be compliant"
        )

    def test_compliance_script_produces_output(self):
        """Policy 6.4: script must produce human-readable output"""
        output, _ = run("/app/scripts/compliance-check.sh 2>&1")
        lines = [l for l in output.split("\n") if l.strip()]
        assert len(lines) >= 5, (
            f"compliance script produced only {len(lines)} lines of output"
        )

    def test_compliance_script_is_substantial(self):
        """Policy 6.2: script must check all policy sections"""
        with open("/app/scripts/compliance-check.sh") as f:
            lines = f.readlines()
        assert len(lines) >= 20, (
            f"compliance script has only {len(lines)} lines — "
            "must substantively check all policy sections"
        )
