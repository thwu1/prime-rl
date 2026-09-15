#!/bin/bash

set -euo pipefail

# ===========================================================================
# SECTION 1: SUDO REMEDIATION
# ===========================================================================

# 1.4 Remove dangerous dynamic linker variables from sudo env_keep
echo 'Defaults env_keep += "DISPLAY XAUTHORITY"' > /etc/sudoers.d/env-config
chmod 0440 /etc/sudoers.d/env-config

# 1.2 Fix developers sudo: replace unscoped vim wildcard with sudoedit
# vim * allows :!bash shell escape -> root; use sudoedit which prevents this
echo '%developers ALL=(ALL) NOPASSWD: /usr/bin/sudoedit /etc/app/*.conf, /usr/bin/git pull' > /etc/sudoers.d/developers
chmod 0440 /etc/sudoers.d/developers

# 1.3 Fix monitoring sudo: replace unrestricted ALL with specific monitoring commands
echo '%monitoring ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *, /usr/bin/journalctl, /usr/bin/top, /usr/bin/ps aux' > /etc/sudoers.d/monitoring
chmod 0440 /etc/sudoers.d/monitoring

# 1.2 + 1.5 Fix deploy sudo: remove docker wildcard, fix permissions from 0644 to 0440
echo '%deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart app, /usr/bin/systemctl status app' > /etc/sudoers.d/deploy
chmod 0440 /etc/sudoers.d/deploy

# 1.5 Ensure all sudoers files are root-owned
chown root:root /etc/sudoers.d/*

# ===========================================================================
# SECTION 2: FILE SYSTEM SECURITY REMEDIATION
# ===========================================================================

# 2.1 + 2.5 Remove SUID and excessive permissions from deploy.sh
chmod 0750 /opt/scripts/deploy.sh

# 2.5 Fix /opt/scripts ownership (was admin:admin, should be root:root)
chown -R root:root /opt/scripts

# 2.2 Fix shadow backup permissions
chmod 0600 /var/backups/shadow.bak

# 2.3 Fix log directory (was 1777 world-writable, policy says max 0750)
chmod 0750 /var/log/app
chown root:root /var/log/app

# 2.4 Fix orphaned file (owned by non-existent UID 1337)
chown root:root /opt/data/config.dat

# ===========================================================================
# SECTION 3: SERVICE ACCOUNT REMEDIATION
# ===========================================================================

# 3.1 Fix service account shells to non-interactive
usermod -s /usr/sbin/nologin svc_monitor
usermod -s /usr/sbin/nologin svc_backup

# 3.2 Remove svc_deploy from wheel group (privilege escalation path)
gpasswd -d svc_deploy wheel 2>/dev/null || true

# ===========================================================================
# SECTION 4: SCHEDULED TASK REMEDIATION
# ===========================================================================

# 4.1 Create backup script at secure location (replaces /tmp/run_backup.sh)
printf '#!/bin/bash\ntar czf /var/backups/full.tar.gz /opt/ 2>/dev/null\n' > /opt/scripts/backup.sh
chmod 0750 /opt/scripts/backup.sh
chown root:root /opt/scripts/backup.sh

# Update the cron entry to reference the secure location
printf '0 2 * * * root /opt/scripts/backup.sh\n' > /etc/cron.d/system-backup
chmod 0644 /etc/cron.d/system-backup

# Clean up the insecure copy if it exists
rm -f /tmp/run_backup.sh

# 4.2 Create cron.allow — only root and wheel members (admin)
printf 'root\nadmin\n' > /etc/cron.allow
chmod 0644 /etc/cron.allow

# 4.3 Remove admin's insecure crontab (chmod -R 777 /var/log/app/)
crontab -r -u admin 2>/dev/null || true

# 4.1 + 4.4 Create maintenance script at secure location (replaces /home/admin/scripts/maintenance.sh)
printf '#!/bin/bash\nfind /var/log -name "*.old" -delete 2>/dev/null\n' > /opt/scripts/maintenance.sh
chmod 0750 /opt/scripts/maintenance.sh
chown root:root /opt/scripts/maintenance.sh

# Update systemd service to reference secure location
sed -i 's|/home/admin/scripts/maintenance.sh|/opt/scripts/maintenance.sh|' \
    /etc/systemd/system/app-maintenance.service

# ===========================================================================
# SECTION 5: AUTHENTICATION POLICY REMEDIATION
# ===========================================================================

# 5.1-5.3 Fix system-wide password policies in login.defs
sed -i 's/^PASS_MAX_DAYS.*/PASS_MAX_DAYS\t90/' /etc/login.defs
sed -i 's/^PASS_MIN_DAYS.*/PASS_MIN_DAYS\t7/' /etc/login.defs
sed -i 's/^PASS_WARN_AGE.*/PASS_WARN_AGE\t14/' /etc/login.defs

# 5.4 Apply password aging to all existing accounts
for user in admin developer1 developer2 webadmin svc_monitor svc_deploy svc_backup; do
    chage -M 90 -m 7 -W 14 "$user"
done

# ===========================================================================
# SECTION 6: COMPLIANCE MONITORING — Create compliance-check.sh
# ===========================================================================

mkdir -p /app/scripts

cat > /app/scripts/compliance-check.sh << 'COMPLIANCE_EOF'
#!/bin/bash
# TechCorp Security Policy v3.2 — Automated Compliance Check
PASS=0
FAIL=0

check_pass() {
    echo "[PASS] $1"
    PASS=$((PASS + 1))
}

check_fail() {
    echo "[FAIL] $1"
    FAIL=$((FAIL + 1))
}

echo "============================================"
echo "Security Policy Compliance Report"
echo "Server: $(hostname)"
echo "Date:   $(date -Iseconds)"
echo "============================================"
echo ""

# --- Section 1: Sudo and Privilege Management ---
echo "--- Section 1: Sudo Configuration ---"

if grep -qri 'ld_preload\|ld_library_path' /etc/sudoers /etc/sudoers.d/ 2>/dev/null; then
    check_fail "1.4 Dangerous dynamic linker variables in sudo env_keep"
else
    check_pass "1.4 No dangerous env_keep variables"
fi

if grep -qr 'vim \*' /etc/sudoers.d/ 2>/dev/null; then
    check_fail "1.2 Unscoped vim wildcard in sudoers"
else
    check_pass "1.2 No unscoped vim wildcards"
fi

if grep -qr 'docker \*' /etc/sudoers.d/ 2>/dev/null; then
    check_fail "1.2 Unscoped docker wildcard in sudoers"
else
    check_pass "1.2 No unscoped docker wildcards"
fi

NON_WHEEL_ALL=$(grep -r 'NOPASSWD: ALL' /etc/sudoers.d/ 2>/dev/null | grep -v '%wheel' | grep -v '^#' || true)
if [ -n "$NON_WHEEL_ALL" ]; then
    check_fail "1.3 Non-admin group has unrestricted sudo access"
else
    check_pass "1.3 No non-admin group has unrestricted sudo"
fi

BAD_PERMS=$(find /etc/sudoers.d/ -type f -not -name 'README*' ! -perm 0440 2>/dev/null)
if [ -n "$BAD_PERMS" ]; then
    check_fail "1.5 Sudoers files with incorrect permissions: $BAD_PERMS"
else
    check_pass "1.5 All sudoers.d files have mode 0440"
fi

BAD_OWNER=$(find /etc/sudoers.d/ -type f -not -name 'README*' ! -user root 2>/dev/null)
if [ -n "$BAD_OWNER" ]; then
    check_fail "1.5 Sudoers files not owned by root: $BAD_OWNER"
else
    check_pass "1.5 All sudoers.d files owned by root"
fi

if visudo -c >/dev/null 2>&1; then
    check_pass "1.6 Sudoers syntax validation passed"
else
    check_fail "1.6 Sudoers syntax validation failed"
fi

# --- Section 2: File System Security ---
echo ""
echo "--- Section 2: File System Security ---"

SUID_WRITABLE=$(find /opt -perm -4000 -writable 2>/dev/null || true)
if [ -n "$SUID_WRITABLE" ]; then
    check_fail "2.1 SUID binaries in writable locations: $SUID_WRITABLE"
else
    check_pass "2.1 No SUID in writable locations"
fi

if [ -f /var/backups/shadow.bak ]; then
    SHADOW_PERM=$(stat -c '%a' /var/backups/shadow.bak)
    if [ "$SHADOW_PERM" = "600" ]; then
        check_pass "2.2 Shadow backup properly restricted"
    else
        check_fail "2.2 Shadow backup has mode $SHADOW_PERM (expected 600)"
    fi
fi

LOG_PERM=$(stat -c '%a' /var/log/app 2>/dev/null || echo "missing")
if [ "$LOG_PERM" != "missing" ]; then
    LAST_DIGIT=$((LOG_PERM % 10))
    if [ $((LAST_DIGIT & 2)) -ne 0 ]; then
        check_fail "2.3 /var/log/app is world-writable (mode $LOG_PERM)"
    else
        check_pass "2.3 /var/log/app not world-writable"
    fi
fi

ORPHANED=$(find /opt -nouser 2>/dev/null || true)
if [ -n "$ORPHANED" ]; then
    check_fail "2.4 Orphaned files in /opt: $ORPHANED"
else
    check_pass "2.4 No orphaned files"
fi

SCRIPTS_OWNER=$(stat -c '%U:%G' /opt/scripts 2>/dev/null)
if [ "$SCRIPTS_OWNER" = "root:root" ]; then
    check_pass "2.5 /opt/scripts owned by root:root"
else
    check_fail "2.5 /opt/scripts owned by $SCRIPTS_OWNER (expected root:root)"
fi

# --- Section 3: Service Account Configuration ---
echo ""
echo "--- Section 3: Service Accounts ---"

for svc in svc_monitor svc_deploy svc_backup; do
    SHELL_PATH=$(getent passwd "$svc" 2>/dev/null | cut -d: -f7)
    if [ "$SHELL_PATH" = "/usr/sbin/nologin" ] || [ "$SHELL_PATH" = "/bin/false" ]; then
        check_pass "3.1 $svc has non-interactive shell"
    else
        check_fail "3.1 $svc has shell $SHELL_PATH (expected nologin)"
    fi
done

if id -Gn svc_deploy 2>/dev/null | grep -qw wheel; then
    check_fail "3.2 svc_deploy is in wheel group"
else
    check_pass "3.2 svc_deploy not in wheel group"
fi

# --- Section 4: Scheduled Task Security ---
echo ""
echo "--- Section 4: Scheduled Tasks ---"

if grep -qrl '/tmp/' /etc/cron.d/ 2>/dev/null; then
    check_fail "4.1 Cron entries reference /tmp"
else
    check_pass "4.1 No cron entries reference /tmp"
fi

if grep -qrl '/home/' /etc/systemd/system/*.service 2>/dev/null; then
    check_fail "4.1 Systemd services reference /home"
else
    check_pass "4.1 No systemd services reference /home"
fi

if [ -f /etc/cron.allow ]; then
    check_pass "4.2 /etc/cron.allow exists"
else
    check_fail "4.2 /etc/cron.allow missing"
fi

ADMIN_CRON=$(crontab -l -u admin 2>/dev/null || echo "no crontab")
if echo "$ADMIN_CRON" | grep -q '777'; then
    check_fail "4.3 Admin crontab contains insecure chmod"
else
    check_pass "4.3 Admin crontab clean"
fi

# --- Section 5: Authentication Policy ---
echo ""
echo "--- Section 5: Authentication ---"

MAX_DAYS=$(grep '^PASS_MAX_DAYS' /etc/login.defs | awk '{print $2}')
if [ "$MAX_DAYS" = "90" ]; then
    check_pass "5.1 PASS_MAX_DAYS is 90"
else
    check_fail "5.1 PASS_MAX_DAYS is $MAX_DAYS (expected 90)"
fi

MIN_DAYS=$(grep '^PASS_MIN_DAYS' /etc/login.defs | awk '{print $2}')
if [ "$MIN_DAYS" = "7" ]; then
    check_pass "5.2 PASS_MIN_DAYS is 7"
else
    check_fail "5.2 PASS_MIN_DAYS is $MIN_DAYS (expected 7)"
fi

WARN_AGE=$(grep '^PASS_WARN_AGE' /etc/login.defs | awk '{print $2}')
if [ "$WARN_AGE" = "14" ]; then
    check_pass "5.3 PASS_WARN_AGE is 14"
else
    check_fail "5.3 PASS_WARN_AGE is $WARN_AGE (expected 14)"
fi

echo ""
echo "============================================"
TOTAL=$((PASS + FAIL))
echo "Results: $PASS passed, $FAIL failed (of $TOTAL checks)"
echo "============================================"

if [ $FAIL -eq 0 ]; then
    echo "STATUS: COMPLIANT"
    exit 0
else
    echo "STATUS: NON-COMPLIANT"
    exit 1
fi
COMPLIANCE_EOF

chmod +x /app/scripts/compliance-check.sh

echo "Security audit remediation complete."
