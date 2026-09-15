The system is an Ubuntu 24.04 host with deliberate CIS benchmark violations. A hardening script at `/app/harden.sh` attempts to remediate these violations but contains bugs that cause it to silently produce incorrect or incomplete configurations. Fix the script so that running `bash /app/harden.sh` brings the system into full compliance.

**Sysctl Parameters** — the following must have correct effective values in the system's sysctl configuration:

| Parameter | Value |
|---|---|
| net.ipv4.ip_forward | 0 |
| net.ipv4.conf.all.send_redirects | 0 |
| net.ipv4.conf.default.send_redirects | 0 |
| net.ipv4.conf.all.accept_source_route | 0 |
| net.ipv4.conf.default.accept_source_route | 0 |
| net.ipv4.conf.all.accept_redirects | 0 |
| net.ipv4.conf.default.accept_redirects | 0 |
| net.ipv4.conf.all.secure_redirects | 0 |
| net.ipv4.conf.default.secure_redirects | 0 |
| net.ipv4.conf.all.log_martians | 1 |
| net.ipv4.conf.default.log_martians | 1 |
| net.ipv4.icmp_echo_ignore_broadcasts | 1 |
| net.ipv4.icmp_ignore_bogus_error_responses | 1 |
| net.ipv4.tcp_syncookies | 1 |
| fs.suid_dumpable | 0 |

**SSH Configuration** — the following directives must be effective in the global scope of `/etc/ssh/sshd_config`:

LogLevel VERBOSE, X11Forwarding no, MaxAuthTries <=4, PermitRootLogin no, PermitEmptyPasswords no, PermitUserEnvironment no, ClientAliveInterval 300, ClientAliveCountMax 0, Banner /etc/issue.net. The config file must be owned by root:root with mode 0600.

**File Permissions**:

| Path | Mode | Owner:Group |
|---|---|---|
| /etc/passwd | 0644 | root:root |
| /etc/shadow | 0640 | root:shadow |
| /etc/group | 0644 | root:root |
| /etc/gshadow | 0640 | root:shadow |

**Password Policy** (`/etc/login.defs`): PASS_MAX_DAYS <= 365, PASS_MIN_DAYS >= 7, PASS_WARN_AGE >= 7, UMASK >= 027.

**PAM Password Quality** (`/etc/security/pwquality.conf`): minlen >= 14, dcredit <= -1, ucredit <= -1, ocredit <= -1, lcredit <= -1.

**Kernel Module Blacklisting**: Modules `cramfs`, `squashfs`, and `udf` must each have a `blacklist` entry and an `install` entry (redirecting to `/bin/true`) in configuration files under `/etc/modprobe.d/`.

**Core Dumps**: `/etc/security/limits.conf` must contain `* hard core 0`. The `fs.suid_dumpable` sysctl parameter is included in the table above.

The script must be idempotent (produce identical results when run consecutively). Verification restores the insecure baseline from `/app/.baseline/`, runs `harden.sh` twice, then checks all controls.
