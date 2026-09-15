#!/bin/bash
# CIS Distribution Independent Linux Benchmark - Level 1 Hardening Script
# This script applies security hardening per CIS benchmark recommendations.
#
# IMPORTANT: This script must correctly harden all four areas:
#   - Kernel network parameters (sysctl)
#   - SSH server configuration
#   - System file permissions
#   - Audit system rules

LOG_FILE="/var/log/cis-hardening.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ============================================================
# Helper: Set a sysctl parameter persistently
# ============================================================
sysctl_set() {
    local key="$1"
    local value="$2"
    local conf_file="/etc/sysctl.conf"

    # Remove any existing entry for this parameter
    sed -i "/^${key}\s*=/d" "$conf_file" 2>/dev/null || true

    # Append the new setting
    echo "$value = $key" >> "$conf_file"
}

# ============================================================
# 3.1 Network Parameters (Host Only)
# ============================================================
harden_sysctl_host() {
    log "Applying CIS 3.1 - Network Parameters (Host Only)"

    # 3.1.1 - Ensure IP forwarding is disabled
    sysctl_set "net.ipv4.ip_forward" "0"

    # 3.1.2 - Ensure packet redirect sending is disabled
    sysctl_set "net.ipv4.conf.all.send_redirects" "0"
    sysctl_set "net.ipv4.conf.default.send_redirects" "0"
}

# ============================================================
# 3.2 Network Parameters (Host and Router)
# ============================================================
harden_sysctl_router() {
    log "Applying CIS 3.2 - Network Parameters (Host and Router)"

    # 3.2.1 - Ensure source routed packets are not accepted
    sysctl_set "net.ipv4.conf.all.accept_source_route" "0"
    sysctl_set "net.ipv4.conf.default.accept_source_route" "0"

    # 3.2.2 - Ensure ICMP redirects are not accepted
    sysctl_set "net.ipv4.conf.all.accept_redirect" "0"
    sysctl_set "net.ipv4.conf.default.accept_redirect" "0"

    # 3.2.3 - Ensure secure ICMP redirects are not accepted
    sysctl_set "net.ipv4.conf.all.secure_redirects" "0"
    sysctl_set "net.ipv4.conf.default.secure_redirects" "0"

    # 3.2.4 - Ensure suspicious packets are logged
    sysctl_set "net.ipv4.conf.all.log_martians" "1"
    sysctl_set "net.ipv4.conf.default.log_martians" "1"

    # 3.2.5 - Ensure broadcast ICMP requests are ignored
    sysctl_set "net.ipv4.icmp_echo_ignore_broadcasts" "1"

    # 3.2.6 - Ensure bogus ICMP responses are ignored
    sysctl_set "net.ipv4.icmp_ignore_bogus_error_responses" "1"

    # 3.2.7 - Ensure Reverse Path Filtering is enabled
    sysctl_set "net.ipv4.conf.all.rp_filter" "2"
    sysctl_set "net.ipv4.conf.default.rp_filter" "2"

    # 3.2.8 - Ensure TCP SYN Cookies is enabled
    sysctl_set "net.ipv4.tcp_syncookies" "1"
}

# ============================================================
# Apply sysctl settings
# ============================================================
apply_sysctl() {
    log "Loading sysctl configuration"
    log "Sysctl settings written successfully"
}

# ============================================================
# 5.2 SSH Server Configuration
# ============================================================
harden_ssh() {
    log "Applying CIS 5.2 - SSH Server Configuration"

    local sshd_conf="/etc/ssh/sshd_config"

    # Backup original
    cp "$sshd_conf" "${sshd_conf}.orig" 2>/dev/null || true

    cat > "$sshd_conf" << 'SSHEOF'
# CIS Hardened SSH Server Configuration

Port 22
Protocol 2

LogLevel DEBUG

X11Forwarding no
MaxAuthRetries 4
IgnoreRhosts yes
HostbasedAuthentication no
PermitRootLogin without-password
PermitEmptyPasswords no
PermitUserEnvironment no

ClientAliveInterval 300
ClientAliveCountMax 3

LoginGraceTime 60

UsePAM yes
AllowTcpForwarding no
MaxStartups 10:30:60
MaxSessions 4

Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr,aes256-cbc
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-512,hmac-sha2-256
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group-exchange-sha256,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512,diffie-hellman-group14-sha256

Banner /etc/issue.net
AllowUsers sshuser
SSHEOF

    # 5.2.1 - Ensure permissions on sshd_config
    chmod 0600 "$sshd_conf"
    chown root:root "$sshd_conf"
}

# ============================================================
# 6.1 System File Permissions
# ============================================================
harden_file_permissions() {
    log "Applying CIS 6.1 - System File Permissions"

    # 6.1.2 - /etc/passwd
    chmod 0644 /etc/passwd
    chown root:root /etc/passwd

    # 6.1.3 - /etc/shadow
    chmod 0644 /etc/shadow
    chown root:root /etc/shadow

    # 6.1.4 - /etc/group
    chmod 0644 /etc/group
    chown root:root /etc/group

    # 6.1.5 - /etc/gshadow
    # (not remediated)

    # 6.1.6 - /etc/passwd-
    chmod 0600 /etc/passwd-
    chown root:root /etc/passwd-

    # 6.1.7 - /etc/shadow-
    chmod 0644 /etc/shadow-
    chown root:root /etc/shadow-

    # 6.1.8 - /etc/group-
    chmod 0644 /etc/group-
    chown root:root /etc/group-

    # 6.1.9 - /etc/gshadow-
    # (not remediated)
}

# ============================================================
# 4.1 Configure System Accounting (auditd)
# ============================================================
harden_auditd() {
    log "Applying CIS 4.1 - Audit Configuration"

    local rules_file="/etc/audit/rules.d/cis-hardening.rules"

    cat > "$rules_file" << 'AUDITEOF'
# CIS Benchmark Audit Rules

# 4.1.5 - Events that modify date and time information
-a always,exit -F arch=b32 -S adjtimex -S settimeofday -S stime -k time_change
-a always,exit -F arch=b32 -S clock_settime -k time_change
-w /etc/localtime -p wa -k time_change

# 4.1.6 - Events that modify user/group information
-w /etc/group -p wa -k identity
-w /etc/passwd -p wa -k identity
-w /etc/gshadow -p wa -k identity
-w /etc/shadow -p wa -k identity
-w /etc/security/opasswd -p wa -k identity

# 4.1.7 - Events that modify the system's network environment
-a always,exit -F arch=b32 -S sethostname -S setdomainname -k system-locale
-w /etc/issue -p wa -k system-locale
-w /etc/issue.net -p wa -k system-locale
-w /etc/hosts -p wa -k system-locale
-w /etc/sysconfig/network -p wa -k system-locale

# 4.1.8 - Events that modify the system's Mandatory Access Controls
-w /etc/apparmor/ -p wa -k MAC-policy
-w /etc/apparmor.d/ -p wa -k MAC-policy

# 4.1.9 - Login and logout events
-w /var/log/faillog -p wa -k logins
-w /var/log/lastlog -p wa -k logins
-w /var/log/tallylog -p wa -k logins

# 4.1.10 - Session initiation information
-w /var/run/utmp -p wa -k session
-w /var/log/wtmp -p wa -k logins
-w /var/log/btmp -p wa -k logins

# 4.1.16 - Changes to system administration scope (sudoers)
-w /etc/sudoers -p wa -k scope
-w /etc/sudoers.d/ -p wa -k scope

# 4.1.17 - System administrator actions (sudolog)
-w /var/log/sudo.log -p wa -k actions

# 4.1.18 - Kernel module loading and unloading
-w /sbin/insmod -p x -k modules
-w /sbin/rmmod -p x -k modules
-w /sbin/modprobe -p x -k modules
-a always,exit -F arch=b32 -S init_module -S delete_module -k modules

# 4.1.19 - Ensure the audit configuration is immutable
-e 2
AUDITEOF

    log "Audit rules configured"
}

# ============================================================
# Main
# ============================================================
main() {
    log "=== CIS Level 1 Security Hardening Started ==="

    harden_sysctl_host
    harden_sysctl_router
    apply_sysctl
    harden_ssh
    harden_file_permissions
    harden_auditd

    log "=== CIS Level 1 Security Hardening Complete ==="
}

main "$@"
