#!/usr/bin/env python3
"""Generate risk assessment for 8 STIG controls.

Evaluates each misconfiguration's real-world security impact, assigns
severity scores, analyzes cascading effects, and produces a priority-
ordered remediation plan.

"""

import json

assessment = [
    {
        "id": "STIG-KERN-001",
        "severity_score": 10,
        "attack_scenario": (
            "With ASLR disabled (kernel.randomize_va_space=0), the memory "
            "layout of every process on the system becomes deterministic. An "
            "attacker exploiting a buffer overflow or use-after-free in any "
            "network-facing service (SSH, web server, etc.) can reliably "
            "craft ROP chains or return-to-libc attacks without needing to "
            "defeat address randomization, reducing exploit complexity from "
            "probabilistic to near-certain."
        ),
        "cascading_impacts": [
            "All processes system-wide lose ASLR protection, not just a single service",
            "Exploits against any memory corruption vulnerability become trivially reliable",
            "Stack-based and heap-based exploitation techniques succeed on first attempt",
            "Defense-in-depth is fundamentally undermined at the kernel level",
        ],
        "remediation_priority": 1,
        "justification": (
            "CAT I finding (highest DISA severity category). ASLR is a "
            "foundational kernel-level defense-in-depth mechanism that protects "
            "every process on the system. Disabling it via a sysctl.d drop-in "
            "labeled as 'performance tuning' creates a system-wide vulnerability "
            "that amplifies the impact of any memory corruption bug in any "
            "running service. Must be remediated first as it multiplies the "
            "risk of all other vulnerabilities."
        ),
    },
    {
        "id": "STIG-SSH-001",
        "severity_score": 9,
        "attack_scenario": (
            "With PermitRootLogin effectively set to 'yes' via a cloud-init "
            "drop-in file, an attacker who obtains or brute-forces the root "
            "password gains immediate unrestricted access to the entire system "
            "over SSH. There is no privilege escalation step required. The "
            "attacker can read all data, modify configurations, install "
            "backdoors, and pivot to other systems on the network."
        ),
        "cascading_impacts": [
            "Direct root access bypasses all privilege separation mechanisms",
            "Attacker can disable other security controls (auditd, PAM, firewall)",
            "Credential harvesting enables lateral movement across the network",
        ],
        "remediation_priority": 2,
        "justification": (
            "Direct remote root login is one of the highest-impact SSH "
            "misconfigurations. The defect is particularly dangerous because "
            "the main sshd_config appears correct (PermitRootLogin no) but the "
            "cloud-init drop-in file silently overrides it via Include "
            "first-match semantics. Administrators checking only the main "
            "config would believe the system is hardened."
        ),
    },
    {
        "id": "STIG-PAM-001",
        "severity_score": 7,
        "attack_scenario": (
            "With the effective account lockout threshold at deny=99 (due to "
            "inline PAM arguments overriding faillock.conf), an attacker can "
            "make up to 99 consecutive failed login attempts before triggering "
            "account lockout. This effectively disables brute-force protection, "
            "allowing automated password guessing attacks against all local "
            "accounts via SSH, console, or any PAM-authenticated service."
        ),
        "cascading_impacts": [
            "Brute-force attacks against all PAM-authenticated services become viable",
            "Combined with weak password policies, account compromise is accelerated",
            "Failed login attempts may still be audited but not prevented",
        ],
        "remediation_priority": 3,
        "justification": (
            "Account lockout is a critical brute-force deterrent. The defect "
            "is subtle because faillock.conf correctly shows deny=3, but the "
            "inline deny=99 on pam_faillock.so in common-auth takes precedence. "
            "This makes the system appear hardened while offering near-zero "
            "protection against automated password attacks."
        ),
    },
    {
        "id": "STIG-AUDIT-001",
        "severity_score": 7,
        "attack_scenario": (
            "With max_log_file_action set to IGNORE, when audit logs reach "
            "their maximum configured size the audit daemon silently stops "
            "recording events. An attacker who has achieved initial access "
            "can generate noise to fill audit logs to capacity, after which "
            "all subsequent actions (privilege escalation, data exfiltration, "
            "lateral movement) proceed unrecorded, eliminating forensic "
            "evidence of the intrusion."
        ),
        "cascading_impacts": [
            "Loss of audit trail eliminates ability to detect and investigate breaches",
            "Compliance frameworks (FedRAMP, FISMA) require continuous audit logging",
            "Incident response is severely hampered without complete audit records",
        ],
        "remediation_priority": 4,
        "justification": (
            "Audit log preservation is essential for breach detection and "
            "forensic investigation. The IGNORE action silently discards events "
            "when logs are full, creating a blind spot that attackers can "
            "deliberately trigger. Unlike ROTATE or SYSLOG, IGNORE provides "
            "no fallback mechanism for preserving audit continuity."
        ),
    },
    {
        "id": "STIG-SSH-002",
        "severity_score": 6,
        "attack_scenario": (
            "With ClientAliveCountMax set to 0, the SSH server never sends "
            "keepalive probes, meaning idle sessions remain open indefinitely. "
            "An attacker who gains physical access to an unattended terminal "
            "with an active SSH session can immediately execute commands with "
            "the privileges of the session owner. In shared environments, "
            "this creates a persistent session hijacking vector."
        ),
        "cascading_impacts": [
            "Unattended SSH sessions remain exploitable for the duration of the connection",
            "Session hijacking bypasses authentication entirely",
            "Stale sessions consume server resources and file descriptor limits",
        ],
        "remediation_priority": 5,
        "justification": (
            "The defect is counterintuitive: ClientAliveCountMax=0 does not "
            "mean 'disconnect immediately after zero missed keepalives' but "
            "rather 'never send keepalive probes at all.' This makes the "
            "ClientAliveInterval=600 setting completely ineffective. The "
            "timeout mechanism silently fails without any error or log entry."
        ),
    },
    {
        "id": "STIG-PAM-002",
        "severity_score": 6,
        "attack_scenario": (
            "With the effective minimum password length reduced to 4 characters "
            "(due to inline pam_pwquality.so argument overriding pwquality.conf's "
            "minlen=15), users can set extremely short passwords. An attacker "
            "can crack 4-character passwords offline in seconds using hashcat "
            "or john, or online via brute-force if account lockout is also "
            "ineffective (compounding with STIG-PAM-001)."
        ),
        "cascading_impacts": [
            "Weak passwords are trivially crackable via offline or online attacks",
            "Combined with broken lockout (PAM-001), password attacks are unimpeded",
            "All password-authenticated services are affected (SSH, su, sudo, console)",
        ],
        "remediation_priority": 6,
        "justification": (
            "Password length is the single most important factor in password "
            "strength. Reducing minlen from 15 to 4 via an inline PAM argument "
            "makes the pwquality.conf settings decorative. The defect compounds "
            "with the broken faillock (PAM-001) to create a highly exploitable "
            "authentication weakness."
        ),
    },
    {
        "id": "STIG-AUDIT-002",
        "severity_score": 5,
        "attack_scenario": (
            "With audit rules using the legacy auid>=500 threshold instead of "
            "auid>=1000, actions performed by UIDs 500-999 (system service "
            "accounts) are captured in audit logs. While this creates log "
            "noise, the real issue is that the rules were written for an "
            "obsolete UID scheme. On modern systems this mismatch indicates "
            "the audit rules were copied from an older system and may have "
            "other unreviewed gaps in coverage for current system accounts."
        ),
        "cascading_impacts": [
            "Audit rules may not correctly match the actual UID allocation scheme",
            "Excessive audit events from service accounts create log noise obscuring real threats",
            "Rules copied from legacy systems may have additional undiscovered gaps",
        ],
        "remediation_priority": 7,
        "justification": (
            "While this is a correctness issue rather than a direct security "
            "bypass, incorrect UID thresholds indicate the audit configuration "
            "was not reviewed for the current system. The functional impact is "
            "lower than other controls but the mismatch undermines confidence "
            "in the audit rule set as a whole."
        ),
    },
    {
        "id": "STIG-SESS-001",
        "severity_score": 5,
        "attack_scenario": (
            "With TMOUT unset by a later profile.d script, interactive shell "
            "sessions never automatically terminate. An attacker who gains "
            "physical access to an unattended workstation with an open terminal "
            "can execute commands with the logged-in user's full privileges. "
            "In server environments, forgotten SSH sessions to production "
            "systems remain open indefinitely, expanding the attack window."
        ),
        "cascading_impacts": [
            "Unattended shell sessions remain exploitable indefinitely",
            "Complements SSH-002: both console and SSH sessions lack timeout protection",
            "Increases the window for session hijacking and unauthorized access",
        ],
        "remediation_priority": 8,
        "justification": (
            "Shell session timeout is a defense-in-depth measure against "
            "physical access and session hijacking. The defect is caused by "
            "profile.d execution ordering: 99-custom.sh runs after "
            "00-security-tmout.sh and unsets the TMOUT variable. The impact "
            "is limited compared to other controls because it requires "
            "physical or existing session access to exploit."
        ),
    },
]

with open("/app/risk_assessment.json", "w") as f:
    json.dump(assessment, f, indent=2)

print("Risk assessment written to /app/risk_assessment.json")
