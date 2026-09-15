#!/bin/bash


# Write the corrected harden.sh that fixes all bugs in the original

cat > /app/harden.sh <<'SCRIPT_EOF'
#!/bin/bash
# CIS Benchmark Hardening Script for Ubuntu 24.04 (corrected)
set -euo pipefail

echo "[*] CIS Hardening - Starting..."

###############################################################################
# Section 3 + 1.5: Sysctl Parameters (network + core dumps)
###############################################################################
echo "[+] Applying sysctl hardening..."

# FIX: Remove insecure drop-in files that would override our settings
# (sysctl.d files take precedence over sysctl.conf via last-assignment-wins)
rm -f /etc/sysctl.d/99-insecure.conf
rm -f /etc/sysctl.d/50-network.conf

# FIX: Clean any leftover entries from sysctl.conf (from previous buggy runs)
sed -i '/# CIS Hardening/,$d' /etc/sysctl.conf 2>/dev/null || true
sed -i '/^fs\.suid_dumpable/d' /etc/sysctl.conf 2>/dev/null || true

# FIX: Write to sysctl.d instead of sysctl.conf for proper precedence
# FIX: accept_redirect → accept_redirects (trailing 's')
# FIX: icmp_echo_ignore_broadcast → icmp_echo_ignore_broadcasts (trailing 's')
# FIX: Add missing icmp_ignore_bogus_error_responses
# FIX: Add fs.suid_dumpable = 0 (was 2)
cat > /etc/sysctl.d/60-cis-hardening.conf <<'EOF'
# CIS Hardening - Network Parameters and Core Dumps
net.ipv4.ip_forward = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.tcp_syncookies = 1
fs.suid_dumpable = 0
EOF

echo "[+] Sysctl parameters written to /etc/sysctl.d/60-cis-hardening.conf"

###############################################################################
# Section 5.2: SSH Server Configuration
###############################################################################
echo "[+] Hardening SSH server configuration..."

SSHD_CONFIG="/etc/ssh/sshd_config"

# FIX: Remove SSH drop-in that overrides MaxAuthTries via Include first-match-wins
rm -f /etc/ssh/sshd_config.d/90-override.conf

chmod 0600 "$SSHD_CONFIG"
chown root:root "$SSHD_CONFIG"

# FIX: Helper function to set directives in global scope (before Match block)
# instead of sed that doesn't handle Include or Match block scope
set_ssh_directive() {
    local key="$1"
    local value="$2"
    # Remove any existing (commented or uncommented) instance of this key
    sed -i "/^[[:space:]]*#\?[[:space:]]*${key}[[:space:]]/d" "$SSHD_CONFIG"
    # Insert before first Match block to stay in global scope
    if grep -qiE "^[[:space:]]*Match[[:space:]]" "$SSHD_CONFIG"; then
        local match_line
        match_line=$(grep -niE "^[[:space:]]*Match[[:space:]]" "$SSHD_CONFIG" | head -1 | cut -d: -f1)
        sed -i "${match_line}i\\${key} ${value}" "$SSHD_CONFIG"
    else
        echo "${key} ${value}" >> "$SSHD_CONFIG"
    fi
}

set_ssh_directive "LogLevel" "VERBOSE"
set_ssh_directive "X11Forwarding" "no"
set_ssh_directive "MaxAuthTries" "4"
set_ssh_directive "PermitRootLogin" "no"
# FIX: Add missing PermitEmptyPasswords directive
set_ssh_directive "PermitEmptyPasswords" "no"
set_ssh_directive "PermitUserEnvironment" "no"
set_ssh_directive "ClientAliveInterval" "300"
# FIX: ClientAliveCountMax 3 → 0
set_ssh_directive "ClientAliveCountMax" "0"
# FIX: Banner placed before Match block (was appended after)
set_ssh_directive "Banner" "/etc/issue.net"

echo "[+] SSH configuration hardened"

###############################################################################
# Section 6.1: System File Permissions
###############################################################################
echo "[+] Setting system file permissions..."

chmod 0644 /etc/passwd
chown root:root /etc/passwd
# FIX: chmod 0644 → 0640 for /etc/shadow
chmod 0640 /etc/shadow
chown root:shadow /etc/shadow
chmod 0644 /etc/group
chown root:root /etc/group
chmod 0640 /etc/gshadow
# FIX: Add missing chown root:shadow for /etc/gshadow
chown root:shadow /etc/gshadow

echo "[+] File permissions configured"

###############################################################################
# Section 5.4: Password Policy (login.defs)
###############################################################################
echo "[+] Configuring password policies..."

# FIX: PASS_MAX_DAY → PASS_MAX_DAYS (typo in sed pattern)
sed -i 's/^PASS_MAX_DAYS[[:space:]].*/PASS_MAX_DAYS 365/' /etc/login.defs
sed -i 's/^PASS_MIN_DAYS[[:space:]].*/PASS_MIN_DAYS 7/' /etc/login.defs
sed -i 's/^PASS_WARN_AGE[[:space:]].*/PASS_WARN_AGE 7/' /etc/login.defs
sed -i 's/^UMASK[[:space:]].*/UMASK 027/' /etc/login.defs

echo "[+] Password policies configured"

###############################################################################
# Section 5.3: PAM Password Quality
###############################################################################
echo "[+] Configuring PAM password quality..."

# FIX: min_len → minlen, value 8 → 14
# FIX: Add missing dcredit/ucredit/ocredit/lcredit
cat > /etc/security/pwquality.conf <<'EOF'
# CIS password quality requirements
minlen = 14
dcredit = -1
ucredit = -1
ocredit = -1
lcredit = -1
retry = 3
EOF

echo "[+] PAM password quality configured"

###############################################################################
# Section 1.1: Kernel Module Blacklisting
###############################################################################
echo "[+] Blacklisting unused kernel modules..."

# FIX: Write to /etc/modprobe.d/ not /etc/modprobe.conf
# FIX: Use 'blacklist module' syntax not 'blacklist=module'
# FIX: Add install directives to prevent loading
rm -f /etc/modprobe.conf
cat > /etc/modprobe.d/cis-hardening.conf <<'EOF'
blacklist cramfs
install cramfs /bin/true
blacklist squashfs
install squashfs /bin/true
blacklist udf
install udf /bin/true
EOF

echo "[+] Kernel modules blacklisted"

###############################################################################
# Section 1.5: Core Dumps Restriction (limits.conf)
###############################################################################
echo "[+] Restricting core dumps..."

# FIX: core 1 → core 0, and make idempotent
sed -i '/^\*[[:space:]]*hard[[:space:]]*core/d' /etc/security/limits.conf
echo "* hard core 0" >> /etc/security/limits.conf

echo "[+] Core dumps restricted"

echo "[*] CIS Hardening complete."
SCRIPT_EOF

chmod +x /app/harden.sh
echo "[+] Fixed harden.sh written to /app/harden.sh"

# Run the corrected script
bash /app/harden.sh
