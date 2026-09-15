#!/bin/bash
# CIS Benchmark Hardening Script for Ubuntu 24.04
# Applies security controls from CIS Distribution Independent Linux Benchmark
#
# Controls covered:
#   - 1.1.x: Kernel module blacklisting
#   - 1.5.x: Core dumps restriction
#   - 3.1.x, 3.2.x: Sysctl network parameters
#   - 5.2.x: SSH server configuration
#   - 5.3.x: PAM password quality
#   - 5.4.x: Password policies (login.defs)
#   - 6.1.x: System file permissions
#
# Usage: bash /app/harden.sh


set -euo pipefail

echo "[*] CIS Hardening - Starting..."

###############################################################################
# Section 3: Network Parameters (sysctl)
# CIS 3.1.1 - 3.2.8: Disable forwarding, redirects, source routing, etc.
###############################################################################
echo "[+] Applying sysctl hardening..."

# Write hardened sysctl parameters for persistence
cat >> /etc/sysctl.conf <<'EOF'
# CIS Hardening
net.ipv4.ip_forward = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv4.conf.all.accept_redirect = 0
net.ipv4.conf.default.accept_redirect = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.default.secure_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.default.log_martians = 1
net.ipv4.icmp_echo_ignore_broadcast = 1
net.ipv4.tcp_syncookies = 1
EOF

echo "[+] Sysctl parameters written to /etc/sysctl.conf"

###############################################################################
# Section 5.2: SSH Server Configuration
# CIS 5.2.1 - 5.2.19: Harden SSH daemon settings
###############################################################################
echo "[+] Hardening SSH server configuration..."

SSHD_CONFIG="/etc/ssh/sshd_config"

# Fix sshd_config file permissions (CIS 5.2.1)
chmod 0600 "$SSHD_CONFIG"
chown root:root "$SSHD_CONFIG"

# Set SSH directives via sed
sed -i 's/^#\?LogLevel.*/LogLevel VERBOSE/' "$SSHD_CONFIG"
sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' "$SSHD_CONFIG"
sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 4/' "$SSHD_CONFIG"
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "$SSHD_CONFIG"
sed -i 's/^#\?PermitUserEnvironment.*/PermitUserEnvironment no/' "$SSHD_CONFIG"
sed -i 's/^#\?ClientAliveInterval.*/ClientAliveInterval 300/' "$SSHD_CONFIG"
sed -i 's/^#\?ClientAliveCountMax.*/ClientAliveCountMax 3/' "$SSHD_CONFIG"
echo "Banner /etc/issue.net" >> "$SSHD_CONFIG"

echo "[+] SSH configuration hardened"

###############################################################################
# Section 6.1: System File Permissions
# CIS 6.1.2 - 6.1.5: Secure critical system files
###############################################################################
echo "[+] Setting system file permissions..."

chmod 0644 /etc/passwd
chown root:root /etc/passwd
chmod 0644 /etc/shadow
chown root:shadow /etc/shadow
chmod 0644 /etc/group
chown root:root /etc/group
chmod 0640 /etc/gshadow

echo "[+] File permissions configured"

###############################################################################
# Section 5.4: Password Policy (login.defs)
# CIS 5.4.1.1 - 5.4.4: Password aging and umask
###############################################################################
echo "[+] Configuring password policies in login.defs..."

sed -i 's/^PASS_MAX_DAY[[:space:]].*/PASS_MAX_DAYS 365/' /etc/login.defs
sed -i 's/^PASS_MIN_DAYS[[:space:]].*/PASS_MIN_DAYS 7/' /etc/login.defs
sed -i 's/^PASS_WARN_AGE[[:space:]].*/PASS_WARN_AGE 7/' /etc/login.defs
sed -i 's/^UMASK[[:space:]].*/UMASK 027/' /etc/login.defs

echo "[+] Password policies configured"

###############################################################################
# Section 5.3: PAM Password Quality
# CIS 5.3.1: Password creation requirements
###############################################################################
echo "[+] Configuring PAM password quality..."

cat > /etc/security/pwquality.conf <<'EOF'
# CIS password quality requirements
min_len = 8
retry = 3
EOF

echo "[+] PAM password quality configured"

###############################################################################
# Section 1.1: Kernel Module Blacklisting
# CIS 1.1.1.x: Disable unused filesystems
###############################################################################
echo "[+] Blacklisting unused kernel modules..."

cat > /etc/modprobe.conf <<'EOF'
blacklist=cramfs
blacklist=squashfs
blacklist=udf
EOF

echo "[+] Kernel modules blacklisted"

###############################################################################
# Section 1.5: Core Dumps Restriction
# CIS 1.5.1: Ensure core dumps are restricted
###############################################################################
echo "[+] Restricting core dumps..."

echo "* hard core 1" >> /etc/security/limits.conf

cat >> /etc/sysctl.conf <<'EOF'
fs.suid_dumpable = 2
EOF

echo "[+] Core dumps restricted"

echo "[*] CIS Hardening complete."
