"""
CIS Level 1 Hardening Verification Tests.

Tests verify that harden.sh correctly hardens the system and that
audit.sh produces a valid compliance report with all controls passing.
"""


import json
import os
import platform
import re
import stat
import subprocess

import pytest


# ===== Fixtures =====

@pytest.fixture(scope="session", autouse=True)
def run_hardening():
    """Run the hardening script before all tests."""
    result = subprocess.run(
        ["bash", "/app/harden.sh"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"harden.sh failed (rc={result.returncode}): {result.stderr}"
    return result


@pytest.fixture(scope="session")
def audit_report(run_hardening):
    """Run audit.sh after hardening and return parsed JSON report."""
    assert os.path.exists("/app/audit.sh"), "/app/audit.sh does not exist"
    assert os.access("/app/audit.sh", os.X_OK), "/app/audit.sh is not executable"

    result = subprocess.run(
        ["bash", "/app/audit.sh"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, f"audit.sh failed (rc={result.returncode}): {result.stderr}"
    assert os.path.exists("/app/compliance_report.json"), "/app/compliance_report.json not created"

    with open("/app/compliance_report.json") as f:
        return json.load(f)


# ===== Helpers =====

def get_sysctl_params():
    """Read all sysctl parameters from /etc/sysctl.d/*.conf files."""
    params = {}
    sysctl_dir = "/etc/sysctl.d"
    if not os.path.isdir(sysctl_dir):
        return params
    for fname in sorted(os.listdir(sysctl_dir)):
        if fname.endswith(".conf"):
            fpath = os.path.join(sysctl_dir, fname)
            with open(fpath) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        params[key.strip()] = val.strip()
    return params


def get_ssh_directives():
    """Parse SSH config directives from /etc/ssh/sshd_config."""
    directives = {}
    with open("/etc/ssh/sshd_config") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split(None, 1)
                if len(parts) == 2:
                    directives[parts[0]] = parts[1]
    return directives


def get_audit_rules():
    """Read all audit rules from /etc/audit/rules.d/."""
    rules = []
    rules_dir = "/etc/audit/rules.d"
    if not os.path.isdir(rules_dir):
        return rules
    for fname in sorted(os.listdir(rules_dir)):
        if fname.endswith(".rules"):
            with open(os.path.join(rules_dir, fname)) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        rules.append(line)
    return rules


def file_mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


# ===== Sysctl Configuration Tests =====

class TestSysctlConfig:
    """Verify sysctl hardening configuration in /etc/sysctl.d/."""

    def test_config_in_sysctl_d(self):
        """CIS params must be in /etc/sysctl.d/, not only /etc/sysctl.conf."""
        params = get_sysctl_params()
        assert "net.ipv4.ip_forward" in params, \
            "net.ipv4.ip_forward not found in /etc/sysctl.d/ config files"

    def test_correct_key_value_format(self):
        """Config lines must be 'key = value', not 'value = key'.

        The broken script writes 'value = key' (reversed). This puts
        numeric values (0, 1, 2) on the left side of '=', producing
        dict keys that start with digits instead of valid sysctl names.
        """
        params = get_sysctl_params()
        numeric_keys = [k for k in params if re.match(r"^\d", k)]
        assert not numeric_keys, \
            f"Found numeric keys {numeric_keys} — indicates reversed key=value format"

    def test_ip_forward_disabled(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.ip_forward") == "0"

    def test_send_redirects_disabled(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.conf.all.send_redirects") == "0"
        assert params.get("net.ipv4.conf.default.send_redirects") == "0"

    def test_accept_source_route_disabled(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.conf.all.accept_source_route") == "0"
        assert params.get("net.ipv4.conf.default.accept_source_route") == "0"

    def test_accept_redirects_plural(self):
        """Must use 'accept_redirects' (plural), not 'accept_redirect'."""
        params = get_sysctl_params()
        assert "net.ipv4.conf.all.accept_redirects" in params, \
            "Missing net.ipv4.conf.all.accept_redirects (note plural 's')"
        assert params["net.ipv4.conf.all.accept_redirects"] == "0"
        assert "net.ipv4.conf.default.accept_redirects" in params
        assert params["net.ipv4.conf.default.accept_redirects"] == "0"

    def test_secure_redirects_disabled(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.conf.all.secure_redirects") == "0"
        assert params.get("net.ipv4.conf.default.secure_redirects") == "0"

    def test_log_martians_enabled(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.conf.all.log_martians") == "1"
        assert params.get("net.ipv4.conf.default.log_martians") == "1"

    def test_icmp_echo_ignore_broadcasts(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.icmp_echo_ignore_broadcasts") == "1"

    def test_icmp_ignore_bogus_error_responses(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.icmp_ignore_bogus_error_responses") == "1"

    def test_rp_filter_strict_mode(self):
        """rp_filter must be 1 (strict), not 2 (loose)."""
        params = get_sysctl_params()
        assert params.get("net.ipv4.conf.all.rp_filter") == "1", \
            f"rp_filter should be 1 (strict), got {params.get('net.ipv4.conf.all.rp_filter')}"
        assert params.get("net.ipv4.conf.default.rp_filter") == "1"

    def test_tcp_syncookies_enabled(self):
        params = get_sysctl_params()
        assert params.get("net.ipv4.tcp_syncookies") == "1"


# ===== SSH Configuration Tests =====

class TestSSHConfig:
    """Verify SSH server hardening configuration."""

    def test_loglevel_not_debug(self):
        """LogLevel must be INFO or VERBOSE, not DEBUG."""
        d = get_ssh_directives()
        assert d.get("LogLevel") in ("INFO", "VERBOSE"), \
            f"LogLevel should be INFO or VERBOSE, got '{d.get('LogLevel')}'"

    def test_maxauthtries_directive(self):
        """Must use MaxAuthTries (not MaxAuthRetries)."""
        d = get_ssh_directives()
        assert "MaxAuthTries" in d, "MaxAuthTries directive missing (check spelling)"
        assert int(d["MaxAuthTries"]) <= 4

    def test_permit_root_login_no(self):
        """PermitRootLogin must be 'no'."""
        d = get_ssh_directives()
        assert d.get("PermitRootLogin") == "no", \
            f"PermitRootLogin should be 'no', got '{d.get('PermitRootLogin')}'"

    def test_client_alive_count_max_zero(self):
        """ClientAliveCountMax must be 0."""
        d = get_ssh_directives()
        assert d.get("ClientAliveCountMax") == "0", \
            f"ClientAliveCountMax should be 0, got '{d.get('ClientAliveCountMax')}'"

    def test_no_weak_ciphers(self):
        """No CBC-mode ciphers allowed."""
        d = get_ssh_directives()
        ciphers = d.get("Ciphers", "")
        weak = [c for c in ciphers.split(",") if "-cbc" in c]
        assert not weak, f"Weak CBC ciphers found: {weak}"

    def test_x11_forwarding_disabled(self):
        d = get_ssh_directives()
        assert d.get("X11Forwarding") == "no"

    def test_ignore_rhosts(self):
        d = get_ssh_directives()
        assert d.get("IgnoreRhosts") == "yes"

    def test_hostbased_auth_disabled(self):
        d = get_ssh_directives()
        assert d.get("HostbasedAuthentication") == "no"

    def test_permit_empty_passwords_no(self):
        d = get_ssh_directives()
        assert d.get("PermitEmptyPasswords") == "no"

    def test_permit_user_environment_no(self):
        d = get_ssh_directives()
        assert d.get("PermitUserEnvironment") == "no"

    def test_client_alive_interval(self):
        d = get_ssh_directives()
        assert int(d.get("ClientAliveInterval", "999")) <= 300

    def test_login_grace_time(self):
        d = get_ssh_directives()
        val = d.get("LoginGraceTime", "999")
        if val.endswith("m"):
            seconds = int(val[:-1]) * 60
        elif val.endswith("s"):
            seconds = int(val[:-1])
        else:
            seconds = int(val)
        assert seconds <= 60

    def test_use_pam(self):
        d = get_ssh_directives()
        assert d.get("UsePAM") == "yes"

    def test_banner_set(self):
        d = get_ssh_directives()
        assert d.get("Banner") is not None and d["Banner"] != "none"

    def test_strong_macs_only(self):
        d = get_ssh_directives()
        allowed = {
            "hmac-sha2-512-etm@openssh.com",
            "hmac-sha2-256-etm@openssh.com",
            "hmac-sha2-512",
            "hmac-sha2-256",
        }
        macs = set(d.get("MACs", "").split(","))
        invalid = macs - allowed
        assert not invalid, f"Non-approved MACs: {invalid}"

    def test_sshd_config_permissions(self):
        mode = file_mode("/etc/ssh/sshd_config")
        assert mode <= 0o600, f"sshd_config mode {oct(mode)} too permissive"


# ===== File Permission Tests =====

class TestFilePermissions:
    """Verify system file permissions per CIS 6.1."""

    def test_passwd_permissions(self):
        assert file_mode("/etc/passwd") == 0o644

    def test_shadow_permissions(self):
        """Shadow must be at most 0640, not 0644."""
        mode = file_mode("/etc/shadow")
        assert mode <= 0o640, f"/etc/shadow mode {oct(mode)}, must be <= 0640"

    def test_group_permissions(self):
        assert file_mode("/etc/group") == 0o644

    def test_gshadow_permissions(self):
        """gshadow must be remediated."""
        assert os.path.exists("/etc/gshadow"), "/etc/gshadow does not exist"
        mode = file_mode("/etc/gshadow")
        assert mode <= 0o640, f"/etc/gshadow mode {oct(mode)}, must be <= 0640"

    def test_passwd_backup_permissions(self):
        if os.path.exists("/etc/passwd-"):
            assert file_mode("/etc/passwd-") <= 0o600

    def test_shadow_backup_permissions(self):
        """Shadow backup must be at most 0600."""
        if os.path.exists("/etc/shadow-"):
            mode = file_mode("/etc/shadow-")
            assert mode <= 0o600, f"/etc/shadow- mode {oct(mode)}, must be <= 0600"

    def test_group_backup_permissions(self):
        if os.path.exists("/etc/group-"):
            assert file_mode("/etc/group-") <= 0o644

    def test_gshadow_backup_permissions(self):
        """gshadow backup must be remediated."""
        if os.path.exists("/etc/gshadow-"):
            mode = file_mode("/etc/gshadow-")
            assert mode <= 0o640, f"/etc/gshadow- mode {oct(mode)}, must be <= 0640"

    def test_shadow_owned_by_root(self):
        assert os.stat("/etc/shadow").st_uid == 0

    def test_passwd_owned_by_root(self):
        assert os.stat("/etc/passwd").st_uid == 0


# ===== Audit Rules Tests =====

class TestAuditRules:
    """Verify audit rules configuration per CIS 4.1."""

    def test_time_change_key_uses_hyphen(self):
        """Audit key must be 'time-change' (hyphen), not 'time_change' (underscore)."""
        rules = get_audit_rules()
        time_rules = [r for r in rules if "adjtimex" in r or "settimeofday" in r or "clock_settime" in r]
        assert time_rules, "No time-change audit rules found"
        for rule in time_rules:
            assert "-k time-change" in rule, \
                f"Audit rule uses wrong key: {rule} (expected '-k time-change')"

    def test_localtime_watch(self):
        rules = get_audit_rules()
        assert any("/etc/localtime" in r and "-k time-change" in r for r in rules)

    def test_identity_rules(self):
        rules = get_audit_rules()
        assert any("/etc/passwd" in r and "-k identity" in r for r in rules)
        assert any("/etc/shadow" in r and "-k identity" in r for r in rules)
        assert any("/etc/group" in r and "-k identity" in r for r in rules)

    def test_network_locale_rules(self):
        rules = get_audit_rules()
        assert any("sethostname" in r and "-k system-locale" in r for r in rules)

    def test_b64_arch_rules_on_64bit(self):
        """64-bit systems need arch=b64 rules."""
        if platform.machine() in ("x86_64", "aarch64"):
            rules = get_audit_rules()
            b64_rules = [r for r in rules if "arch=b64" in r]
            assert b64_rules, "Missing arch=b64 audit rules for 64-bit system"
            assert any(
                "arch=b64" in r and ("adjtimex" in r or "settimeofday" in r)
                for r in b64_rules
            ), "Missing b64 time-change rules"

    def test_module_rules(self):
        rules = get_audit_rules()
        assert any("/sbin/insmod" in r for r in rules)
        assert any("/sbin/rmmod" in r for r in rules)
        assert any("/sbin/modprobe" in r for r in rules)
        assert any("init_module" in r and "delete_module" in r for r in rules)

    def test_sudoers_rules(self):
        rules = get_audit_rules()
        assert any("/etc/sudoers" in r and "-k scope" in r for r in rules)

    def test_immutable_flag(self):
        rules = get_audit_rules()
        assert any(r.strip() == "-e 2" for r in rules)


# ===== Audit Script and Report Tests =====

class TestAuditScript:
    """Verify the audit script and its JSON output."""

    def test_report_has_timestamp(self, audit_report):
        assert "timestamp" in audit_report
        assert isinstance(audit_report["timestamp"], str)
        assert len(audit_report["timestamp"]) > 0

    def test_report_has_controls(self, audit_report):
        assert "controls" in audit_report
        assert isinstance(audit_report["controls"], list)
        assert len(audit_report["controls"]) >= 20, \
            f"Report has {len(audit_report['controls'])} controls, need at least 20"

    def test_control_structure(self, audit_report):
        for ctrl in audit_report["controls"]:
            assert "id" in ctrl, f"Control missing 'id': {ctrl}"
            assert "title" in ctrl, f"Control missing 'title': {ctrl}"
            assert "status" in ctrl, f"Control missing 'status': {ctrl}"
            assert ctrl["status"] in ("pass", "fail"), \
                f"Invalid status '{ctrl['status']}' for control {ctrl.get('id')}"
            assert "detail" in ctrl, f"Control missing 'detail': {ctrl}"

    def test_report_has_summary(self, audit_report):
        assert "summary" in audit_report
        summary = audit_report["summary"]
        assert "total" in summary
        assert "pass" in summary
        assert "fail" in summary

    def test_summary_consistency(self, audit_report):
        summary = audit_report["summary"]
        controls = audit_report["controls"]
        assert summary["total"] == len(controls), \
            f"summary.total ({summary['total']}) != len(controls) ({len(controls)})"
        assert summary["pass"] + summary["fail"] == summary["total"], \
            f"pass ({summary['pass']}) + fail ({summary['fail']}) != total ({summary['total']})"

    def test_all_controls_pass(self, audit_report):
        failed = [c for c in audit_report["controls"] if c["status"] != "pass"]
        assert not failed, \
            f"{len(failed)} controls failed: " + \
            ", ".join(f"{c['id']}: {c['detail']}" for c in failed[:5])
