#!/bin/bash
# CIS Compliance Audit Script
# Verifies system configuration against CIS Level 1 requirements
# and writes a JSON compliance report.
#

REPORT_FILE="/app/compliance_report.json"
TMPFILE=$(mktemp)
echo '[]' > "$TMPFILE"

add_result() {
    local id="$1" title="$2" status="$3" detail="$4"
    detail=$(echo "$detail" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g')
    local entry
    entry=$(jq -n --arg id "$id" --arg title "$title" --arg status "$status" --arg detail "$detail" \
        '{id:$id,title:$title,status:$status,detail:$detail}')
    jq --argjson entry "$entry" '. += [$entry]' "$TMPFILE" > "${TMPFILE}.new"
    mv "${TMPFILE}.new" "$TMPFILE"
}

# ===== Sysctl helpers =====

get_sysctl_param() {
    local key="$1"
    local value=""
    for conf in /etc/sysctl.d/*.conf; do
        [ -f "$conf" ] || continue
        local v
        v=$(grep -E "^\s*${key}\s*=" "$conf" 2>/dev/null | tail -1 | sed 's/.*=\s*//' | tr -d ' ')
        if [ -n "$v" ]; then
            value="$v"
        fi
    done
    echo "$value"
}

check_sysctl() {
    local id="$1" title="$2" key="$3" expected="$4"
    local actual
    actual=$(get_sysctl_param "$key")
    if [ "$actual" = "$expected" ]; then
        add_result "$id" "$title" "pass" "$key = $actual"
    else
        add_result "$id" "$title" "fail" "$key = '$actual' (expected '$expected')"
    fi
}

# ===== SSH helpers =====

get_ssh_directive() {
    local directive="$1"
    grep -i "^${directive}\b" /etc/ssh/sshd_config 2>/dev/null | head -1 | awk '{print $2}'
}

check_ssh() {
    local id="$1" title="$2" directive="$3" expected="$4"
    local actual
    actual=$(get_ssh_directive "$directive")
    if [ "$actual" = "$expected" ]; then
        add_result "$id" "$title" "pass" "$directive = $actual"
    else
        add_result "$id" "$title" "fail" "$directive = '$actual' (expected '$expected')"
    fi
}

check_ssh_lte() {
    local id="$1" title="$2" directive="$3" max_val="$4"
    local actual
    actual=$(get_ssh_directive "$directive")
    if [ -n "$actual" ] && [ "$actual" -le "$max_val" ] 2>/dev/null; then
        add_result "$id" "$title" "pass" "$directive = $actual (<= $max_val)"
    else
        add_result "$id" "$title" "fail" "$directive = '$actual' (expected <= $max_val)"
    fi
}

# ===== File permission helpers =====

check_file_perms() {
    local id="$1" title="$2" filepath="$3" max_mode="$4"
    if [ ! -e "$filepath" ]; then
        add_result "$id" "$title" "fail" "$filepath does not exist"
        return
    fi
    local mode
    mode=$(stat -c '%a' "$filepath")
    local mode_oct=$((8#$mode))
    local max_oct=$((8#$max_mode))
    if [ "$mode_oct" -le "$max_oct" ]; then
        add_result "$id" "$title" "pass" "$filepath mode $mode (<= $max_mode)"
    else
        add_result "$id" "$title" "fail" "$filepath mode $mode (expected <= $max_mode)"
    fi
}

check_file_owner() {
    local id="$1" title="$2" filepath="$3" expected_owner="$4"
    if [ ! -e "$filepath" ]; then
        add_result "$id" "$title" "fail" "$filepath does not exist"
        return
    fi
    local owner
    owner=$(stat -c '%U' "$filepath")
    if [ "$owner" = "$expected_owner" ]; then
        add_result "$id" "$title" "pass" "$filepath owned by $owner"
    else
        add_result "$id" "$title" "fail" "$filepath owned by $owner (expected $expected_owner)"
    fi
}

# ===== Audit rule helpers =====

check_audit_rule() {
    local id="$1" title="$2" pattern="$3"
    local found=0
    for rf in /etc/audit/rules.d/*.rules; do
        [ -f "$rf" ] || continue
        if grep -qE "$pattern" "$rf" 2>/dev/null; then
            found=1
            break
        fi
    done
    if [ "$found" -eq 1 ]; then
        add_result "$id" "$title" "pass" "Rule matching pattern found"
    else
        add_result "$id" "$title" "fail" "No rule matching pattern found"
    fi
}

# ========================================================================
# Run all checks
# ========================================================================

# --- CIS 3.1 Sysctl: Host-Only Network Parameters ---
check_sysctl "3.1.1" "IP forwarding disabled" "net.ipv4.ip_forward" "0"
check_sysctl "3.1.2a" "Send redirects disabled (all)" "net.ipv4.conf.all.send_redirects" "0"
check_sysctl "3.1.2b" "Send redirects disabled (default)" "net.ipv4.conf.default.send_redirects" "0"

# --- CIS 3.2 Sysctl: Host and Router Network Parameters ---
check_sysctl "3.2.1a" "Source route disabled (all)" "net.ipv4.conf.all.accept_source_route" "0"
check_sysctl "3.2.1b" "Source route disabled (default)" "net.ipv4.conf.default.accept_source_route" "0"
check_sysctl "3.2.2a" "ICMP redirects disabled (all)" "net.ipv4.conf.all.accept_redirects" "0"
check_sysctl "3.2.2b" "ICMP redirects disabled (default)" "net.ipv4.conf.default.accept_redirects" "0"
check_sysctl "3.2.3a" "Secure redirects disabled (all)" "net.ipv4.conf.all.secure_redirects" "0"
check_sysctl "3.2.3b" "Secure redirects disabled (default)" "net.ipv4.conf.default.secure_redirects" "0"
check_sysctl "3.2.4a" "Log martians enabled (all)" "net.ipv4.conf.all.log_martians" "1"
check_sysctl "3.2.4b" "Log martians enabled (default)" "net.ipv4.conf.default.log_martians" "1"
check_sysctl "3.2.5" "ICMP broadcast ignored" "net.ipv4.icmp_echo_ignore_broadcasts" "1"
check_sysctl "3.2.6" "Bogus ICMP responses ignored" "net.ipv4.icmp_ignore_bogus_error_responses" "1"
check_sysctl "3.2.7a" "Reverse path filtering (all)" "net.ipv4.conf.all.rp_filter" "1"
check_sysctl "3.2.7b" "Reverse path filtering (default)" "net.ipv4.conf.default.rp_filter" "1"
check_sysctl "3.2.8" "TCP SYN Cookies enabled" "net.ipv4.tcp_syncookies" "1"

# --- CIS 5.2 SSH Server Configuration ---
check_file_perms "5.2.1" "sshd_config permissions" "/etc/ssh/sshd_config" "0600"

ID="5.2.5"
TITLE="SSH LogLevel appropriate"
LOGLEVEL=$(get_ssh_directive "LogLevel")
if [ "$LOGLEVEL" = "INFO" ] || [ "$LOGLEVEL" = "VERBOSE" ]; then
    add_result "$ID" "$TITLE" "pass" "LogLevel = $LOGLEVEL"
else
    add_result "$ID" "$TITLE" "fail" "LogLevel = '$LOGLEVEL' (expected INFO or VERBOSE)"
fi

check_ssh "5.2.6" "X11 forwarding disabled" "X11Forwarding" "no"
check_ssh_lte "5.2.7" "MaxAuthTries <= 4" "MaxAuthTries" "4"
check_ssh "5.2.8" "IgnoreRhosts enabled" "IgnoreRhosts" "yes"
check_ssh "5.2.9" "HostbasedAuthentication disabled" "HostbasedAuthentication" "no"
check_ssh "5.2.10" "Root login disabled" "PermitRootLogin" "no"
check_ssh "5.2.11" "Empty passwords disabled" "PermitEmptyPasswords" "no"
check_ssh "5.2.12" "User environment disabled" "PermitUserEnvironment" "no"

# 5.2.13 - Strong ciphers only
ID="5.2.13"
TITLE="Only strong ciphers"
CIPHERS=$(get_ssh_directive "Ciphers")
WEAK_FOUND=""
for c in $(echo "$CIPHERS" | tr ',' ' '); do
    case "$c" in
        *-cbc*|*arcfour*|*blowfish*|*cast128*|*3des*) WEAK_FOUND="$WEAK_FOUND $c" ;;
    esac
done
if [ -z "$WEAK_FOUND" ]; then
    add_result "$ID" "$TITLE" "pass" "No weak ciphers found"
else
    add_result "$ID" "$TITLE" "fail" "Weak ciphers:$WEAK_FOUND"
fi

# 5.2.14 - Strong MACs only
ID="5.2.14"
TITLE="Only strong MACs"
MACS=$(get_ssh_directive "MACs")
ALLOWED_MACS="hmac-sha2-512-etm@openssh.com hmac-sha2-256-etm@openssh.com hmac-sha2-512 hmac-sha2-256"
WEAK_MAC=""
for m in $(echo "$MACS" | tr ',' ' '); do
    FOUND=0
    for a in $ALLOWED_MACS; do
        if [ "$m" = "$a" ]; then FOUND=1; break; fi
    done
    if [ "$FOUND" -eq 0 ]; then WEAK_MAC="$WEAK_MAC $m"; fi
done
if [ -z "$WEAK_MAC" ]; then
    add_result "$ID" "$TITLE" "pass" "All MACs are approved"
else
    add_result "$ID" "$TITLE" "fail" "Non-approved MACs:$WEAK_MAC"
fi

check_ssh_lte "5.2.16a" "ClientAliveInterval <= 300" "ClientAliveInterval" "300"
check_ssh_lte "5.2.16b" "ClientAliveCountMax <= 0" "ClientAliveCountMax" "0"
check_ssh_lte "5.2.17" "LoginGraceTime <= 60" "LoginGraceTime" "60"

ID="5.2.19"
TITLE="SSH warning banner configured"
BANNER=$(get_ssh_directive "Banner")
if [ -n "$BANNER" ] && [ "$BANNER" != "none" ]; then
    add_result "$ID" "$TITLE" "pass" "Banner = $BANNER"
else
    add_result "$ID" "$TITLE" "fail" "No banner configured"
fi

check_ssh "5.2.20" "UsePAM enabled" "UsePAM" "yes"

# --- CIS 6.1 System File Permissions ---
check_file_perms "6.1.2" "passwd permissions" "/etc/passwd" "0644"
check_file_owner "6.1.2b" "passwd ownership" "/etc/passwd" "root"
check_file_perms "6.1.3" "shadow permissions" "/etc/shadow" "0640"
check_file_owner "6.1.3b" "shadow ownership" "/etc/shadow" "root"
check_file_perms "6.1.4" "group permissions" "/etc/group" "0644"
check_file_perms "6.1.5" "gshadow permissions" "/etc/gshadow" "0640"
check_file_perms "6.1.6" "passwd- permissions" "/etc/passwd-" "0600"
check_file_perms "6.1.7" "shadow- permissions" "/etc/shadow-" "0600"
check_file_perms "6.1.8" "group- permissions" "/etc/group-" "0644"
check_file_perms "6.1.9" "gshadow- permissions" "/etc/gshadow-" "0640"

# --- CIS 4.1 Audit Rules ---
check_audit_rule "4.1.5" "Time change audit rules" "adjtimex.*-k time-change"
check_audit_rule "4.1.6" "Identity audit rules" "/etc/passwd.*-k identity"
check_audit_rule "4.1.7" "Network environment audit rules" "sethostname.*-k system-locale"
check_audit_rule "4.1.16" "Sudoers audit rules" "/etc/sudoers.*-k scope"
check_audit_rule "4.1.18" "Kernel module audit rules" "/sbin/insmod.*-k modules"
check_audit_rule "4.1.19" "Audit config immutable" "^-e 2"

# ========================================================================
# Build the JSON report
# ========================================================================
TOTAL=$(jq 'length' "$TMPFILE")
PASS=$(jq '[.[] | select(.status=="pass")] | length' "$TMPFILE")
FAIL=$(jq '[.[] | select(.status=="fail")] | length' "$TMPFILE")

jq -n --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --argjson controls "$(cat "$TMPFILE")" \
      --argjson total "$TOTAL" \
      --argjson pass "$PASS" \
      --argjson fail "$FAIL" \
    '{timestamp:$ts,controls:$controls,summary:{total:$total,pass:$pass,fail:$fail}}' \
    > "$REPORT_FILE"

rm -f "$TMPFILE"

echo "Compliance report written to $REPORT_FILE"
echo "Total: $TOTAL, Pass: $PASS, Fail: $FAIL"

exit 0
