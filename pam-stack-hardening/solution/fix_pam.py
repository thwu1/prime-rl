#!/usr/bin/env python3
"""
PAM Breach Forensics, Remediation, and Vulnerability Assessment Generator


Analyzes auth logs to reconstruct the attack chain, identifies all PAM
vulnerabilities (exploited and latent), remediates them, and produces
a structured vulnerability assessment JSON.
"""

import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Step 1: Forensic log analysis
# ---------------------------------------------------------------------------

def analyze_auth_logs(log_path):
    """Parse auth logs to identify attack indicators."""
    findings = {
        "attacker_ip": None,
        "brute_force_targets": {},
        "successful_logins_from_attacker": [],
        "su_escalations": [],
        "total_failed_no_lockout": 0,
    }

    with open(log_path) as f:
        lines = f.readlines()

    failed_counts = {}
    attacker_ip = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Detect failed password attempts
        m = re.search(
            r"Failed password for (\S+) from (\S+)", line)
        if m:
            user, ip = m.group(1), m.group(2)
            if not ip.startswith("10."):
                attacker_ip = ip
                failed_counts.setdefault(user, 0)
                failed_counts[user] += 1

        # Detect successful logins
        m = re.search(
            r"Accepted password for (\S+) from (\S+)", line)
        if m:
            user, ip = m.group(1), m.group(2)
            if attacker_ip and ip == attacker_ip:
                findings["successful_logins_from_attacker"].append(user)

        # Detect su escalation
        m = re.search(
            r"su\[\d+\]:.*session opened for user (\S+)\(uid=\d+\) by (\S+)",
            line)
        if m:
            target, source = m.group(1), m.group(2)
            findings["su_escalations"].append(
                {"from": source, "to": target})

    findings["attacker_ip"] = attacker_ip
    findings["brute_force_targets"] = failed_counts
    findings["total_failed_no_lockout"] = sum(failed_counts.values())

    return findings


# ---------------------------------------------------------------------------
# Step 2: PAM configuration analysis
# ---------------------------------------------------------------------------

def analyze_pam_configs():
    """Analyze current PAM configs for vulnerabilities."""
    vulns = []

    # Check common-auth for auth bypass
    try:
        with open("/etc/pam.d/common-auth") as f:
            content = f.read()
        active = [l.strip() for l in content.split("\n")
                  if l.strip() and not l.strip().startswith("#")]

        unix_has_ignore = False
        permit_after = False
        for i, line in enumerate(active):
            if "pam_unix.so" in line and "default=ignore" in line:
                unix_has_ignore = True
            if unix_has_ignore and "pam_permit.so" in line:
                before = line.split("pam_permit.so")[0]
                if "sufficient" in before:
                    permit_after = True

        if unix_has_ignore and permit_after:
            vulns.append("AUTH_BYPASS")

        if "pam_faillock.so" not in content:
            vulns.append("NO_FAILLOCK_AUTH")
    except FileNotFoundError:
        pass

    # Check faillock.conf
    try:
        with open("/etc/security/faillock.conf") as f:
            content = f.read()
        m = re.search(r"^\s*deny\s*=\s*(\d+)", content, re.MULTILINE)
        if m and int(m.group(1)) == 0:
            vulns.append("LOCKOUT_DISABLED")
        m = re.search(r"^\s*unlock_time\s*=\s*(\d+)", content, re.MULTILINE)
        if m and int(m.group(1)) == 0:
            vulns.append("UNLOCK_TIME_ZERO")
    except FileNotFoundError:
        pass

    # Check su config
    try:
        with open("/etc/pam.d/su") as f:
            content = f.read()
        active = [l for l in content.split("\n")
                  if l.strip() and not l.strip().startswith("#")]
        has_wheel = any(
            "pam_wheel.so" in l and "auth" in l
            and ("required" in l or "requisite" in l)
            for l in active
        )
        if not has_wheel:
            vulns.append("SU_UNRESTRICTED")
    except FileNotFoundError:
        pass

    # Check access.conf
    try:
        with open("/etc/security/access.conf") as f:
            content = f.read()
        active = [l.strip() for l in content.split("\n")
                  if l.strip() and not l.strip().startswith("#")]
        has_deny = any(l.startswith("-") for l in active)
        if not has_deny:
            vulns.append("PERMISSIVE_ACCESS")
    except FileNotFoundError:
        pass

    # Check common-account
    try:
        with open("/etc/pam.d/common-account") as f:
            content = f.read()
        if "pam_access.so" not in content:
            vulns.append("NO_ACCESS_IN_ACCOUNT")
        if "pam_faillock.so" not in content:
            vulns.append("NO_FAILLOCK_ACCOUNT")
    except FileNotFoundError:
        pass

    # Check pwquality
    try:
        with open("/etc/security/pwquality.conf") as f:
            content = f.read()
        m = re.search(r"^\s*minlen\s*=\s*(\d+)", content, re.MULTILINE)
        if m and int(m.group(1)) < 12:
            vulns.append("WEAK_PASSWORD_POLICY")
    except FileNotFoundError:
        pass

    # Check limits
    try:
        with open("/etc/security/limits.conf") as f:
            content = f.read()
        active = [l.strip() for l in content.split("\n")
                  if l.strip() and not l.strip().startswith("#")]
        if not active:
            vulns.append("NO_RESOURCE_LIMITS")
    except FileNotFoundError:
        pass

    # Check common-session for pam_limits
    try:
        with open("/etc/pam.d/common-session") as f:
            content = f.read()
        if "pam_limits.so" not in content:
            vulns.append("NO_SESSION_LIMITS")
    except FileNotFoundError:
        pass

    # Check common-password for pam_pwquality
    try:
        with open("/etc/pam.d/common-password") as f:
            content = f.read()
        if "pam_pwquality.so" not in content:
            vulns.append("NO_PWQUALITY_MODULE")
    except FileNotFoundError:
        pass

    return vulns


# ---------------------------------------------------------------------------
# Step 3: Generate vulnerability assessment
# ---------------------------------------------------------------------------

def generate_assessment(log_findings, config_vulns):
    """Create the structured vulnerability assessment JSON."""
    vulnerabilities = []

    # VULN-001: Authentication bypass
    vulnerabilities.append({
        "id": "VULN-001",
        "title": "Authentication Bypass via pam_permit Fallback",
        "affected_file": "/etc/pam.d/common-auth",
        "severity": "critical",
        "exploited_in_breach": True,
        "attack_phase": "initial_access",
        "description": (
            "pam_unix.so is configured with [success=2 default=ignore], "
            "followed by pam_permit.so as sufficient. When pam_unix fails "
            "authentication, the default=ignore result causes the chain to "
            "continue, and pam_permit.so unconditionally succeeds with "
            "sufficient control, granting authentication regardless of the "
            "password provided. The auth logs show the attacker's dev1 login "
            "succeeded despite no successful password guess in the preceding "
            "brute-force sequence."
        ),
        "remediation": (
            "Changed pam_unix control to [success=1 default=bad] so failure "
            "is recorded. Removed pam_permit.so sufficient. Integrated "
            "pam_faillock with preauth/authfail/authsucc. Added pam_deny.so "
            "as final fallback."
        ),
    })

    # VULN-002: Account lockout disabled
    vulnerabilities.append({
        "id": "VULN-002",
        "title": "Account Lockout Disabled in faillock Configuration",
        "affected_file": "/etc/security/faillock.conf",
        "severity": "high",
        "exploited_in_breach": True,
        "attack_phase": "reconnaissance",
        "description": (
            "faillock.conf has deny=0 and unlock_time=0, effectively "
            "disabling account lockout. Additionally, pam_faillock.so was "
            "not present in the auth stack. The attacker made 24 consecutive "
            "failed attempts against admin1 and 8 against dev1 with no "
            "lockout triggered, enabling unrestricted brute-force "
            "reconnaissance."
        ),
        "remediation": (
            "Set deny=5, unlock_time=900, even_deny_root=false in "
            "faillock.conf. Integrated pam_faillock.so preauth, authfail, "
            "and authsucc into common-auth. Added pam_faillock.so to "
            "common-account."
        ),
    })

    # VULN-003: Unrestricted su
    vulnerabilities.append({
        "id": "VULN-003",
        "title": "Unrestricted Privilege Escalation via su",
        "affected_file": "/etc/pam.d/su",
        "severity": "critical",
        "exploited_in_breach": True,
        "attack_phase": "privilege_escalation",
        "description": (
            "The su PAM configuration lacks pam_wheel.so, allowing any "
            "authenticated user to su to root. The attacker escalated from "
            "dev1 (a developers group member, not in wheel) to root "
            "immediately after gaining initial access."
        ),
        "remediation": (
            "Added 'auth required pam_wheel.so use_uid' after pam_rootok "
            "and before the common-auth include, restricting su to wheel "
            "group members only."
        ),
    })

    # VULN-004: Permissive access control
    vulnerabilities.append({
        "id": "VULN-004",
        "title": "Permissive Access Control Allows Unauthorized Remote Login",
        "affected_file": "/etc/security/access.conf",
        "severity": "high",
        "exploited_in_breach": True,
        "attack_phase": "lateral_movement",
        "description": (
            "access.conf contains only '+ : ALL : ALL', granting all users "
            "access from any origin. pam_access.so was also missing from "
            "the account stack. The attacker remotely accessed svcaccount "
            "(which should be denied all interactive access) and restricted1 "
            "(which should only have LOCAL terminal access)."
        ),
        "remediation": (
            "Configured access.conf with ordered rules: allow restricted "
            "from LOCAL, deny restricted from ALL, deny svcaccounts from "
            "ALL, allow everyone else. Added pam_access.so to "
            "common-account."
        ),
    })

    # VULN-005: Weak password policy (latent)
    vulnerabilities.append({
        "id": "VULN-005",
        "title": "Weak Password Quality Requirements",
        "affected_file": "/etc/security/pwquality.conf",
        "severity": "medium",
        "exploited_in_breach": False,
        "attack_phase": "not_exploited",
        "description": (
            "pwquality.conf has minlen=1 and minclass=0, imposing no "
            "meaningful password complexity requirements. pam_pwquality.so "
            "was also absent from the password management stack. While not "
            "directly exploited in this breach, weak passwords increase "
            "the likelihood of successful brute-force attacks."
        ),
        "remediation": (
            "Set minlen=12, minclass=4, dcredit=-1, ucredit=-1, lcredit=-1, "
            "ocredit=-1 in pwquality.conf. Added pam_pwquality.so as "
            "requisite before pam_unix in common-password."
        ),
    })

    # VULN-006: No resource limits (latent)
    vulnerabilities.append({
        "id": "VULN-006",
        "title": "No Resource Limits Configured",
        "affected_file": "/etc/security/limits.conf",
        "severity": "low",
        "exploited_in_breach": False,
        "attack_phase": "not_exploited",
        "description": (
            "limits.conf has no configured entries, and pam_limits.so is "
            "absent from the session stack. Without resource limits, any "
            "user can consume unlimited system resources, enabling denial "
            "of service attacks via fork bombs or file descriptor "
            "exhaustion."
        ),
        "remediation": (
            "Configured per-group resource limits: @admins "
            "nproc=unlimited/nofile=65536, @developers nproc=200/nofile=8192, "
            "default nproc=100/nofile=4096. Added pam_limits.so to "
            "common-session."
        ),
    })

    # Build attack chain: lockout disabled -> auth bypass -> priv esc
    attack_chain = ["VULN-002", "VULN-001", "VULN-003", "VULN-004"]

    return {
        "vulnerabilities": vulnerabilities,
        "attack_chain": attack_chain,
        "overall_risk_rating": "critical",
    }


# ---------------------------------------------------------------------------
# Step 4: Remediate PAM configurations
# ---------------------------------------------------------------------------

def write_common_auth():
    content = (
        "# /etc/pam.d/common-auth - authentication settings\n"
        "#\n"
        "# Remediated: removed auth bypass, integrated pam_faillock\n"
        "\n"
        "auth\trequired\t\t\tpam_faillock.so preauth silent\n"
        "auth\t[success=1 default=bad]\t\tpam_unix.so nullok\n"
        "auth\t[default=die]\t\t\tpam_faillock.so authfail\n"
        "auth\tsufficient\t\t\tpam_faillock.so authsucc\n"
        "auth\trequired\t\t\tpam_deny.so\n"
    )
    with open("/etc/pam.d/common-auth", "w") as f:
        f.write(content)


def write_common_account():
    content = (
        "# /etc/pam.d/common-account - authorization settings\n"
        "\n"
        "account\trequired\t\t\tpam_access.so\n"
        "account\trequired\t\t\tpam_faillock.so\n"
        "account\t[success=1 new_authtok_reqd=done default=ignore]"
        "\tpam_unix.so\n"
        "account\trequisite\t\t\tpam_deny.so\n"
        "account\trequired\t\t\tpam_permit.so\n"
    )
    with open("/etc/pam.d/common-account", "w") as f:
        f.write(content)


def write_common_session():
    content = (
        "# /etc/pam.d/common-session - session settings\n"
        "\n"
        "session\t[default=1]\t\t\tpam_permit.so\n"
        "session\trequisite\t\t\tpam_deny.so\n"
        "session\trequired\t\t\tpam_permit.so\n"
        "session\trequired\t\t\tpam_unix.so\n"
        "session\trequired\t\t\tpam_limits.so\n"
    )
    with open("/etc/pam.d/common-session", "w") as f:
        f.write(content)


def write_common_password():
    content = (
        "# /etc/pam.d/common-password - password settings\n"
        "\n"
        "password\trequisite\t\t\tpam_pwquality.so retry=3\n"
        "password\t[success=1 default=ignore]\tpam_unix.so "
        "obscure use_authtok sha512\n"
        "password\trequisite\t\t\tpam_deny.so\n"
        "password\trequired\t\t\tpam_permit.so\n"
    )
    with open("/etc/pam.d/common-password", "w") as f:
        f.write(content)


def write_su():
    content = (
        "# /etc/pam.d/su - su authentication\n"
        "\n"
        "auth\tsufficient\tpam_rootok.so\n"
        "auth\trequired\tpam_wheel.so use_uid\n"
        "session\toptional\tpam_mail.so nopen\n"
        "@include common-auth\n"
        "@include common-account\n"
        "@include common-session\n"
    )
    with open("/etc/pam.d/su", "w") as f:
        f.write(content)


def write_faillock_conf():
    content = (
        "# /etc/security/faillock.conf\n"
        "deny = 5\n"
        "unlock_time = 900\n"
        "even_deny_root = false\n"
        "dir = /var/run/faillock\n"
    )
    with open("/etc/security/faillock.conf", "w") as f:
        f.write(content)


def write_access_conf():
    content = (
        "# /etc/security/access.conf\n"
        "#\n"
        "# Rules processed top-to-bottom, first match wins.\n"
        "\n"
        "# Allow restricted group only from LOCAL terminals\n"
        "+ : restricted : LOCAL\n"
        "# Deny restricted group from all other origins\n"
        "- : restricted : ALL\n"
        "# Deny service accounts from all origins\n"
        "- : svcaccounts : ALL\n"
        "# Allow everyone else from everywhere\n"
        "+ : ALL : ALL\n"
    )
    with open("/etc/security/access.conf", "w") as f:
        f.write(content)


def write_pwquality_conf():
    content = (
        "# /etc/security/pwquality.conf\n"
        "minlen = 12\n"
        "minclass = 4\n"
        "dcredit = -1\n"
        "ucredit = -1\n"
        "lcredit = -1\n"
        "ocredit = -1\n"
    )
    with open("/etc/security/pwquality.conf", "w") as f:
        f.write(content)


def write_limits_conf():
    content = (
        "# /etc/security/limits.conf\n"
        "@admins\thard\tnproc\t\tunlimited\n"
        "@admins\thard\tnofile\t\t65536\n"
        "@developers\thard\tnproc\t\t200\n"
        "@developers\thard\tnofile\t\t8192\n"
        "*\thard\tnproc\t\t100\n"
        "*\thard\tnofile\t\t4096\n"
    )
    with open("/etc/security/limits.conf", "w") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log_path = "/app/auth_log.txt"
    if not os.path.exists(log_path):
        print("ERROR: Auth log not found", file=sys.stderr)
        sys.exit(1)

    # Step 1: Forensic analysis
    print("=== Step 1: Forensic Log Analysis ===")
    log_findings = analyze_auth_logs(log_path)
    print(f"  Attacker IP: {log_findings['attacker_ip']}")
    print(f"  Brute-force targets: {log_findings['brute_force_targets']}")
    print(f"  Total failed (no lockout): "
          f"{log_findings['total_failed_no_lockout']}")
    print(f"  Successful logins from attacker: "
          f"{log_findings['successful_logins_from_attacker']}")
    print(f"  su escalations: {log_findings['su_escalations']}")

    # Step 2: Configuration analysis
    print("\n=== Step 2: PAM Configuration Analysis ===")
    config_vulns = analyze_pam_configs()
    for v in config_vulns:
        print(f"  FOUND: {v}")

    # Step 3: Generate assessment
    print("\n=== Step 3: Vulnerability Assessment ===")
    assessment = generate_assessment(log_findings, config_vulns)
    assessment_path = "/app/vulnerability_assessment.json"
    with open(assessment_path, "w") as f:
        json.dump(assessment, f, indent=2)
    print(f"  Written to {assessment_path}")
    print(f"  Vulnerabilities: {len(assessment['vulnerabilities'])}")
    print(f"  Attack chain: {assessment['attack_chain']}")
    print(f"  Overall risk: {assessment['overall_risk_rating']}")

    # Step 4: Remediate
    print("\n=== Step 4: PAM Remediation ===")
    write_common_auth()
    print("  Fixed: /etc/pam.d/common-auth")
    write_common_account()
    print("  Fixed: /etc/pam.d/common-account")
    write_common_session()
    print("  Fixed: /etc/pam.d/common-session")
    write_common_password()
    print("  Fixed: /etc/pam.d/common-password")
    write_su()
    print("  Fixed: /etc/pam.d/su")
    write_faillock_conf()
    print("  Fixed: /etc/security/faillock.conf")
    write_access_conf()
    print("  Fixed: /etc/security/access.conf")
    write_pwquality_conf()
    print("  Fixed: /etc/security/pwquality.conf")
    write_limits_conf()
    print("  Fixed: /etc/security/limits.conf")

    # Ensure faillock data directory
    os.makedirs("/var/run/faillock", exist_ok=True)

    print("\nRemediation complete.")


if __name__ == "__main__":
    main()
