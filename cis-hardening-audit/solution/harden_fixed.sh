#!/bin/bash
# CIS Distribution Independent Linux Benchmark - Level 1 Hardening Script (Fixed)
#

LOG_FILE="/var/log/cis-hardening.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ============================================================
# Helper: Set a sysctl parameter persistently
# FIX 1: Write to /etc/sysctl.d/ drop-in file, not /etc/sysctl.conf
# FIX 2: Correct key=value format (was reversed)
# ============================================================
sysctl_set() {
    local key="$1"
    local value="$2"
    local conf_file="/etc/sysctl.d/99-cis-hardening.conf"

    touch "$conf_file"
    sed -i "/^${key}\s*=/d" "$conf_file" 2>/dev/null || true
    echo "$key = $value" >> "$conf_file"
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
# FIX 3: accept_redirect -> accept_redirects (plural)
# FIX 4: rp_filter = 1 (strict), not 2 (loose)
# ============================================================
harden_sysctl_router() {
    log "Applying CIS 3.2 - Network Parameters (Host and Router)"

    # 3.2.1 - Ensure source routed packets are not accepted
    sysctl_set "net.ipv4.conf.all.accept_source_route" "0"
    sysctl_set "net.ipv4.conf.default.accept_source_route" "0"

    # 3.2.2 - Ensure ICMP redirects are not accepted
    sysctl_set "net.ipv4.conf.all.accept_redirects" "0"
    sysctl_set "net.ipv4.conf.default.accept_redirects" "0"

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

    # 3.2.7 - Ensure Reverse Path Filtering is enabled (strict mode)
    sysctl_set "net.ipv4.conf.all.rp_filter" "1"
    sysctl_set "net.ipv4.conf.default.rp_filter" "1"

    # 3.2.8 - Ensure TCP SYN Cookies is enabled
    sysctl_set "net.ipv4.tcp_syncookies" "1"
}

# ============================================================
# Apply sysctl settings
# FIX 5: Actually invoke sysctl to load the configuration
# ============================================================
apply_sysctl() {
    log "Loading sysctl configuration"
    sysctl --system 2>/dev/null || true
    log "Sysctl settings applied"
}

# ============================================================
# 5.2 SSH Server Configuration
# FIX 6: LogLevel INFO (not DEBUG)
# FIX 7: MaxAuthTries (not MaxAuthRetries)
# FIX 8: PermitRootLogin no (not without-password)
# FIX 9: ClientAliveCountMax 0 (not 3)
# FIX 10: Removed aes256-cbc from Ciphers
# ============================================================
harden_ssh() {
    log "Applying CIS 5.2 - SSH Server Configuration"

    local sshd_conf="/etc/ssh/sshd_config"
    cp "$sshd_conf" "${sshd_conf}.orig" 2>/dev/null || true

    cat > "$sshd_conf" << 'SSHEOF'
# CIS Hardened SSH Server Configuration

Port 22
Protocol 2

LogLevel INFO

X11Forwarding no
MaxAuthTries 4
IgnoreRhosts yes
HostbasedAuthentication no
PermitRootLogin no
PermitEmptyPasswords no
PermitUserEnvironment no

ClientAliveInterval 300
ClientAliveCountMax 0

LoginGraceTime 60

UsePAM yes
AllowTcpForwarding no
MaxStartups 10:30:60
MaxSessions 4

Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr
MACs hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,hmac-sha2-512,hmac-sha2-256
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group-exchange-sha256,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512,diffie-hellman-group14-sha256

Banner /etc/issue.net
AllowUsers sshuser
SSHEOF

    chmod 0600 "$sshd_conf"
    chown root:root "$sshd_conf"
}

# ============================================================
# 6.1 System File Permissions
# FIX 11: /etc/shadow 0640 (not 0644)
# FIX 12: Added /etc/gshadow remediation
# FIX 13: /etc/shadow- 0600 (not 0644)
# FIX 14: Added /etc/gshadow- remediation
# ============================================================
harden_file_permissions() {
    log "Applying CIS 6.1 - System File Permissions"

    # 6.1.2 - /etc/passwd
    chmod 0644 /etc/passwd
    chown root:root /etc/passwd

    # 6.1.3 - /etc/shadow
    chmod 0640 /etc/shadow
    chown root:root /etc/shadow

    # 6.1.4 - /etc/group
    chmod 0644 /etc/group
    chown root:root /etc/group

    # 6.1.5 - /etc/gshadow
    chmod 0640 /etc/gshadow
    chown root:root /etc/gshadow

    # 6.1.6 - /etc/passwd-
    chmod 0600 /etc/passwd-
    chown root:root /etc/passwd-

    # 6.1.7 - /etc/shadow-
    chmod 0600 /etc/shadow-
    chown root:root /etc/shadow-

    # 6.1.8 - /etc/group-
    chmod 0644 /etc/group-
    chown root:root /etc/group-

    # 6.1.9 - /etc/gshadow-
    chmod 0640 /etc/gshadow-
    chown root:root /etc/gshadow-
}

# ============================================================
# 4.1 Configure System Accounting (auditd)
# FIX 15: Audit key 'time-change' (hyphen, not underscore)
# FIX 16: Added arch=b64 rules for 64-bit systems
# ============================================================
harden_auditd() {
    log "Applying CIS 4.1 - Audit Configuration"

    local rules_file="/etc/audit/rules.d/cis-hardening.rules"
    local arch
    arch=$(uname -m)

    cat > "$rules_file" << 'AUDITEOF'
# CIS Benchmark Audit Rules

# 4.1.5 - Events that modify date and time information
-a always,exit -F arch=b32 -S adjtimex -S settimeofday -S stime -k time-change
-a always,exit -F arch=b32 -S clock_settime -k time-change
-w /etc/localtime -p wa -k time-change
AUDITEOF

    if [ "$arch" = "x86_64" ] || [ "$arch" = "aarch64" ]; then
        cat >> "$rules_file" << 'B64EOF'
-a always,exit -F arch=b64 -S adjtimex -S settimeofday -k time-change
-a always,exit -F arch=b64 -S clock_settime -k time-change
B64EOF
    fi

    cat >> "$rules_file" << 'AUDITEOF2'

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
AUDITEOF2

    if [ "$arch" = "x86_64" ] || [ "$arch" = "aarch64" ]; then
        echo "-a always,exit -F arch=b64 -S sethostname -S setdomainname -k system-locale" >> "$rules_file"
    fi

    cat >> "$rules_file" << 'AUDITEOF3'

# 4.1.8 - MAC events
-w /etc/apparmor/ -p wa -k MAC-policy
-w /etc/apparmor.d/ -p wa -k MAC-policy

# 4.1.9 - Login/logout events
-w /var/log/faillog -p wa -k logins
-w /var/log/lastlog -p wa -k logins
-w /var/log/tallylog -p wa -k logins

# 4.1.10 - Session initiation
-w /var/run/utmp -p wa -k session
-w /var/log/wtmp -p wa -k logins
-w /var/log/btmp -p wa -k logins

# 4.1.16 - Sudoers changes
-w /etc/sudoers -p wa -k scope
-w /etc/sudoers.d/ -p wa -k scope

# 4.1.17 - Sudo log
-w /var/log/sudo.log -p wa -k actions

# 4.1.18 - Kernel module loading
-w /sbin/insmod -p x -k modules
-w /sbin/rmmod -p x -k modules
-w /sbin/modprobe -p x -k modules
AUDITEOF3

    if [ "$arch" = "x86_64" ] || [ "$arch" = "aarch64" ]; then
        echo "-a always,exit -F arch=b64 -S init_module -S delete_module -k modules" >> "$rules_file"
    else
        echo "-a always,exit -F arch=b32 -S init_module -S delete_module -k modules" >> "$rules_file"
    fi

    echo "" >> "$rules_file"
    echo "# 4.1.19 - Immutable" >> "$rules_file"
    echo "-e 2" >> "$rules_file"

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
