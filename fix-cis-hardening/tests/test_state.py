"""
CIS Benchmark compliance verification tests.

Checks system state after running harden.sh against CIS Distribution
Independent Linux Benchmark controls for sysctl, SSH, file permissions,
login.defs, PAM password quality, kernel module blacklisting, and core dumps.
"""


import glob
import os
import re
import stat

import pytest


def resolve_sysctl_effective():
    """
    Resolve effective sysctl values from config files.

    Resolution order (matching procps-ng sysctl --system behavior):
    1. /etc/sysctl.conf
    2. /etc/sysctl.d/*.conf in lexicographic order
    Last assignment for each parameter wins.
    """
    effective = {}

    sysctl_conf = "/etc/sysctl.conf"
    if os.path.exists(sysctl_conf):
        _parse_sysctl_file(sysctl_conf, effective)

    for f in sorted(glob.glob("/etc/sysctl.d/*.conf")):
        _parse_sysctl_file(f, effective)

    return effective


def _parse_sysctl_file(filepath, params):
    """Parse a sysctl config file, updating params dict (last value wins)."""
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                params[key.strip()] = value.strip()


def _parse_sshd_recursive(filepath, directives, visited):
    """Recursively parse sshd_config, following Include directives inline."""
    real = os.path.realpath(filepath)
    if real in visited:
        return
    visited.add(real)

    if not os.path.exists(filepath):
        return

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()
            # Stop at first Match block (case-insensitive)
            if re.match(r"(?i)^\s*match\s", stripped):
                return
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                key, value = parts
                if key.lower() == "include":
                    # Process included files in sorted order
                    for inc_path in sorted(glob.glob(value)):
                        _parse_sshd_recursive(inc_path, directives, visited)
                elif key not in directives:
                    # First occurrence wins (OpenSSH behavior)
                    directives[key] = value


def parse_sshd_config_global():
    """
    Parse /etc/ssh/sshd_config and return effective global-scope directives.

    Processes Include directives inline. For each directive, the first
    occurrence wins (matching OpenSSH behavior). Stops at Match blocks.
    """
    directives = {}
    _parse_sshd_recursive("/etc/ssh/sshd_config", directives, set())
    return directives


def get_file_info(path):
    """Return (octal_mode, owner_name, group_name) for a file."""
    import grp
    import pwd

    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    owner = pwd.getpwuid(st.st_uid).pw_name
    group = grp.getgrgid(st.st_gid).gr_name
    return mode, owner, group


def parse_login_defs():
    """Parse /etc/login.defs into a key-value dict (last occurrence wins)."""
    result = {}
    with open("/etc/login.defs") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split(None, 1)
            if len(parts) == 2:
                result[parts[0]] = parts[1].strip()
    return result


def parse_pwquality_conf():
    """Parse /etc/security/pwquality.conf into a key-value dict."""
    result = {}
    path = "/etc/security/pwquality.conf"
    if not os.path.exists(path):
        return result
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                result[key.strip()] = value.strip()
    return result


def load_modprobe_directives():
    """Load all directives from /etc/modprobe.d/*.conf files."""
    directives = []
    for f in sorted(glob.glob("/etc/modprobe.d/*.conf")):
        with open(f) as fh:
            for line in fh:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    directives.append(stripped)
    return directives


def parse_limits_conf():
    """Parse /etc/security/limits.conf and return list of active entries."""
    entries = []
    path = "/etc/security/limits.conf"
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                entries.append(stripped)
    return entries


# ---------------------------------------------------------------------------
# Sysctl tests (CIS 3.1.x, 3.2.x + 1.5.1)
# ---------------------------------------------------------------------------

class TestSysctlHardening:
    """Verify sysctl parameters have correct effective values via config files."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.effective = resolve_sysctl_effective()

    @pytest.mark.parametrize(
        "param,expected",
        [
            ("net.ipv4.ip_forward", "0"),
            ("net.ipv4.conf.all.send_redirects", "0"),
            ("net.ipv4.conf.default.send_redirects", "0"),
            ("net.ipv4.conf.all.accept_source_route", "0"),
            ("net.ipv4.conf.default.accept_source_route", "0"),
            ("net.ipv4.conf.all.accept_redirects", "0"),
            ("net.ipv4.conf.default.accept_redirects", "0"),
            ("net.ipv4.conf.all.secure_redirects", "0"),
            ("net.ipv4.conf.default.secure_redirects", "0"),
            ("net.ipv4.conf.all.log_martians", "1"),
            ("net.ipv4.conf.default.log_martians", "1"),
            ("net.ipv4.icmp_echo_ignore_broadcasts", "1"),
            ("net.ipv4.icmp_ignore_bogus_error_responses", "1"),
            ("net.ipv4.tcp_syncookies", "1"),
            ("fs.suid_dumpable", "0"),
        ],
    )
    def test_sysctl_param(self, param, expected):
        """Each sysctl parameter must have the CIS-compliant effective value."""
        assert param in self.effective, (
            f"Parameter {param} not found in any sysctl config "
            f"(/etc/sysctl.conf or /etc/sysctl.d/*.conf)"
        )
        assert self.effective[param] == expected, (
            f"Parameter {param}: expected={expected}, got={self.effective[param]}"
        )


# ---------------------------------------------------------------------------
# SSH tests (CIS 5.2.x)
# ---------------------------------------------------------------------------

class TestSSHHardening:
    """Verify SSH server configuration meets CIS requirements."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.directives = parse_sshd_config_global()
        self.config_mode, self.config_owner, self.config_group = get_file_info(
            "/etc/ssh/sshd_config"
        )

    def test_sshd_config_mode(self):
        """CIS 5.2.1: sshd_config must have mode 0600."""
        assert self.config_mode == 0o600, (
            f"sshd_config mode: expected 0600, got {oct(self.config_mode)}"
        )

    def test_sshd_config_owner(self):
        """CIS 5.2.1: sshd_config must be owned by root."""
        assert self.config_owner == "root"

    def test_sshd_config_group(self):
        """CIS 5.2.1: sshd_config must have group root."""
        assert self.config_group == "root"

    def test_log_level(self):
        """CIS 5.2.5: LogLevel must be INFO or VERBOSE."""
        assert "LogLevel" in self.directives, "LogLevel not set in global scope"
        assert self.directives["LogLevel"] in ("INFO", "VERBOSE"), (
            f"LogLevel: expected INFO or VERBOSE, got {self.directives['LogLevel']}"
        )

    def test_x11_forwarding(self):
        """CIS 5.2.6: X11Forwarding must be disabled."""
        assert "X11Forwarding" in self.directives
        assert self.directives["X11Forwarding"] == "no"

    def test_max_auth_tries(self):
        """CIS 5.2.7: MaxAuthTries must be 4 or less."""
        assert "MaxAuthTries" in self.directives, (
            "MaxAuthTries not set in global scope"
        )
        assert int(self.directives["MaxAuthTries"]) <= 4

    def test_permit_root_login(self):
        """CIS 5.2.10: PermitRootLogin must be no."""
        assert "PermitRootLogin" in self.directives
        assert self.directives["PermitRootLogin"] == "no"

    def test_permit_empty_passwords(self):
        """CIS 5.2.11: PermitEmptyPasswords must be no."""
        assert "PermitEmptyPasswords" in self.directives, (
            "PermitEmptyPasswords not set in global scope"
        )
        assert self.directives["PermitEmptyPasswords"] == "no"

    def test_permit_user_environment(self):
        """CIS 5.2.12: PermitUserEnvironment must be no."""
        assert "PermitUserEnvironment" in self.directives
        assert self.directives["PermitUserEnvironment"] == "no"

    def test_client_alive_interval(self):
        """CIS 5.2.16: ClientAliveInterval must be between 1 and 300."""
        assert "ClientAliveInterval" in self.directives, (
            "ClientAliveInterval not set in global scope"
        )
        val = int(self.directives["ClientAliveInterval"])
        assert 1 <= val <= 300, (
            f"ClientAliveInterval: expected 1-300, got {val}"
        )

    def test_client_alive_count_max(self):
        """CIS 5.2.16: ClientAliveCountMax must be 0."""
        assert "ClientAliveCountMax" in self.directives, (
            "ClientAliveCountMax not set in global scope"
        )
        assert int(self.directives["ClientAliveCountMax"]) == 0, (
            f"ClientAliveCountMax: expected 0, got "
            f"{self.directives['ClientAliveCountMax']}"
        )

    def test_banner(self):
        """CIS 5.2.19: Banner must point to /etc/issue.net in global scope."""
        assert "Banner" in self.directives, (
            "Banner not set in global SSH scope (may be inside Match block)"
        )
        assert self.directives["Banner"] == "/etc/issue.net", (
            f"Banner: expected /etc/issue.net, got {self.directives['Banner']}"
        )


# ---------------------------------------------------------------------------
# File permission tests (CIS 6.1.x)
# ---------------------------------------------------------------------------

class TestFilePermissions:
    """Verify critical system file permissions and ownership."""

    @pytest.mark.parametrize(
        "path,expected_mode,expected_owner,expected_group",
        [
            ("/etc/passwd", 0o644, "root", "root"),
            ("/etc/shadow", 0o640, "root", "shadow"),
            ("/etc/group", 0o644, "root", "root"),
            ("/etc/gshadow", 0o640, "root", "shadow"),
        ],
    )
    def test_file_permissions(
        self, path, expected_mode, expected_owner, expected_group
    ):
        mode, owner, group = get_file_info(path)
        assert mode == expected_mode, (
            f"{path} mode: expected {oct(expected_mode)}, got {oct(mode)}"
        )
        assert owner == expected_owner, (
            f"{path} owner: expected {expected_owner}, got {owner}"
        )
        assert group == expected_group, (
            f"{path} group: expected {expected_group}, got {group}"
        )


# ---------------------------------------------------------------------------
# login.defs tests (CIS 5.4.x)
# ---------------------------------------------------------------------------

class TestLoginDefs:
    """Verify password policy settings in /etc/login.defs."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.defs = parse_login_defs()

    def test_pass_max_days(self):
        """CIS 5.4.1.1: PASS_MAX_DAYS must be 365 or less."""
        assert "PASS_MAX_DAYS" in self.defs, "PASS_MAX_DAYS not set in login.defs"
        assert int(self.defs["PASS_MAX_DAYS"]) <= 365, (
            f"PASS_MAX_DAYS: expected <= 365, got {self.defs['PASS_MAX_DAYS']}"
        )

    def test_pass_min_days(self):
        """CIS 5.4.1.2: PASS_MIN_DAYS must be 7 or more."""
        assert "PASS_MIN_DAYS" in self.defs
        assert int(self.defs["PASS_MIN_DAYS"]) >= 7, (
            f"PASS_MIN_DAYS: expected >= 7, got {self.defs['PASS_MIN_DAYS']}"
        )

    def test_pass_warn_age(self):
        """CIS 5.4.1.3: PASS_WARN_AGE must be 7 or more."""
        assert "PASS_WARN_AGE" in self.defs
        assert int(self.defs["PASS_WARN_AGE"]) >= 7, (
            f"PASS_WARN_AGE: expected >= 7, got {self.defs['PASS_WARN_AGE']}"
        )

    def test_umask(self):
        """CIS 5.4.4: UMASK must be 027 or more restrictive."""
        assert "UMASK" in self.defs, "UMASK not set in login.defs"
        umask_val = int(self.defs["UMASK"], 8)
        # Each octal digit must be at least as restrictive as 027
        u_other = umask_val & 7
        u_group = (umask_val >> 3) & 7
        assert u_other >= 7, (
            f"UMASK other digit not restrictive enough: {oct(umask_val)}"
        )
        assert u_group >= 2, (
            f"UMASK group digit not restrictive enough: {oct(umask_val)}"
        )


# ---------------------------------------------------------------------------
# PAM password quality tests (CIS 5.3.x)
# ---------------------------------------------------------------------------

class TestPAMPasswordQuality:
    """Verify PAM password quality configuration meets CIS requirements."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.pwquality = parse_pwquality_conf()

    def test_minlen(self):
        """CIS 5.3.1: Minimum password length must be >= 14."""
        assert "minlen" in self.pwquality, (
            "minlen not set in /etc/security/pwquality.conf "
            "(check for typos like 'min_len')"
        )
        assert int(self.pwquality["minlen"]) >= 14, (
            f"minlen: expected >= 14, got {self.pwquality['minlen']}"
        )

    def test_dcredit(self):
        """CIS 5.3.1: dcredit must be set to -1 or less (require digit)."""
        assert "dcredit" in self.pwquality, (
            "dcredit not set in /etc/security/pwquality.conf"
        )
        assert int(self.pwquality["dcredit"]) <= -1, (
            f"dcredit: expected <= -1, got {self.pwquality['dcredit']}"
        )

    def test_ucredit(self):
        """CIS 5.3.1: ucredit must be set to -1 or less (require uppercase)."""
        assert "ucredit" in self.pwquality, (
            "ucredit not set in /etc/security/pwquality.conf"
        )
        assert int(self.pwquality["ucredit"]) <= -1, (
            f"ucredit: expected <= -1, got {self.pwquality['ucredit']}"
        )

    def test_ocredit(self):
        """CIS 5.3.1: ocredit must be set to -1 or less (require special)."""
        assert "ocredit" in self.pwquality, (
            "ocredit not set in /etc/security/pwquality.conf"
        )
        assert int(self.pwquality["ocredit"]) <= -1, (
            f"ocredit: expected <= -1, got {self.pwquality['ocredit']}"
        )

    def test_lcredit(self):
        """CIS 5.3.1: lcredit must be set to -1 or less (require lowercase)."""
        assert "lcredit" in self.pwquality, (
            "lcredit not set in /etc/security/pwquality.conf"
        )
        assert int(self.pwquality["lcredit"]) <= -1, (
            f"lcredit: expected <= -1, got {self.pwquality['lcredit']}"
        )


# ---------------------------------------------------------------------------
# Kernel module blacklisting tests (CIS 1.1.1.x)
# ---------------------------------------------------------------------------

class TestKernelModuleBlacklist:
    """Verify kernel modules are properly blacklisted via modprobe.d."""

    MODULES = ["cramfs", "squashfs", "udf"]

    @pytest.fixture(autouse=True)
    def setup(self):
        self.directives = load_modprobe_directives()

    @pytest.mark.parametrize("module", MODULES)
    def test_module_blacklisted(self, module):
        """Each module must have a blacklist entry in /etc/modprobe.d/."""
        expected = f"blacklist {module}"
        assert any(d == expected for d in self.directives), (
            f"Missing 'blacklist {module}' in /etc/modprobe.d/*.conf "
            f"(check path and syntax — 'blacklist=module' is invalid)"
        )

    @pytest.mark.parametrize("module", MODULES)
    def test_module_install_redirect(self, module):
        """Each module must have an install redirect to /bin/true."""
        expected = f"install {module} /bin/true"
        assert any(d == expected for d in self.directives), (
            f"Missing 'install {module} /bin/true' in /etc/modprobe.d/*.conf"
        )

    def test_no_modprobe_conf_file(self):
        """Configuration must be in /etc/modprobe.d/, not /etc/modprobe.conf."""
        assert not os.path.exists("/etc/modprobe.conf"), (
            "/etc/modprobe.conf should not exist; "
            "use files under /etc/modprobe.d/ instead"
        )


# ---------------------------------------------------------------------------
# Core dumps tests (CIS 1.5.1)
# ---------------------------------------------------------------------------

class TestCoreDumps:
    """Verify core dumps are properly restricted."""

    def test_limits_hard_core(self):
        """CIS 1.5.1: limits.conf must set * hard core 0."""
        entries = parse_limits_conf()
        last_core = None
        for entry in entries:
            parts = entry.split()
            if (
                len(parts) >= 4
                and parts[0] == "*"
                and parts[1] == "hard"
                and parts[2] == "core"
            ):
                last_core = parts[3]
        assert last_core is not None, (
            "'* hard core' entry not found in /etc/security/limits.conf"
        )
        assert last_core == "0", (
            f"* hard core: expected 0, got {last_core}"
        )

    def test_suid_dumpable(self):
        """CIS 1.5.1: fs.suid_dumpable must be 0 in sysctl config."""
        effective = resolve_sysctl_effective()
        assert "fs.suid_dumpable" in effective, (
            "fs.suid_dumpable not found in sysctl configuration"
        )
        assert effective["fs.suid_dumpable"] == "0", (
            f"fs.suid_dumpable: expected 0, got {effective['fs.suid_dumpable']}"
        )
