#!/usr/bin/env python3
"""STIG Compliance Validator

Checks 8 STIG-derived security controls by modeling the actual configuration
resolution behavior of each Linux subsystem. Detects override-based failures
that surface-level checks would miss.

"""

import json
import os
import re
import sys


def _read_file(path):
    with open(path, "r") as f:
        return f.read()


def check_stig_ssh_001():
    """PermitRootLogin must be effectively 'no'.
    SSH processes Include directives before subsequent config lines.
    Drop-in files are read in sorted order. First-match semantics apply:
    once a directive is set, later occurrences in other files are ignored.
    """
    effective = None
    source = None

    # Drop-in files processed first via Include (sorted order, first match wins)
    dropin_dir = "/etc/ssh/sshd_config.d/"
    if os.path.isdir(dropin_dir):
        for fname in sorted(os.listdir(dropin_dir)):
            if not fname.endswith(".conf"):
                continue
            content = _read_file(os.path.join(dropin_dir, fname))
            match = re.search(r"^\s*PermitRootLogin\s+(\S+)", content, re.MULTILINE)
            if match and effective is None:
                effective = match.group(1).lower()
                source = f"sshd_config.d/{fname}"

    # Then main config (only if not already set by a drop-in)
    content = _read_file("/etc/ssh/sshd_config")
    match = re.search(r"^\s*PermitRootLogin\s+(\S+)", content, re.MULTILINE)
    if match and effective is None:
        effective = match.group(1).lower()
        source = "sshd_config"

    if effective is None:
        effective = "yes"  # OpenSSH default when unspecified
        source = "default (unspecified)"

    status = "PASS" if effective == "no" else "FAIL"
    explanation = (
        f"Effective PermitRootLogin='{effective}' resolved from {source}. "
        f"SSH Include directive causes drop-in files in sshd_config.d/ to be "
        f"processed before the main config. First-match semantics mean the "
        f"earliest PermitRootLogin setting across all sources takes effect."
    )

    return {
        "id": "STIG-SSH-001",
        "status": status,
        "effective_value": effective,
        "expected_value": "no",
        "explanation": explanation,
    }


def check_stig_ssh_002():
    """SSH idle timeout requires both ClientAliveInterval and ClientAliveCountMax
    to be correctly configured. ClientAliveCountMax=0 disables keepalive
    messages entirely, making ClientAliveInterval meaningless.
    """
    config_text = ""
    dropin_dir = "/etc/ssh/sshd_config.d/"
    if os.path.isdir(dropin_dir):
        for fname in sorted(os.listdir(dropin_dir)):
            if fname.endswith(".conf"):
                config_text += _read_file(os.path.join(dropin_dir, fname)) + "\n"
    config_text += _read_file("/etc/ssh/sshd_config")

    # First-match for each directive
    interval_match = re.search(
        r"^\s*ClientAliveInterval\s+(\d+)", config_text, re.MULTILINE
    )
    count_match = re.search(
        r"^\s*ClientAliveCountMax\s+(\d+)", config_text, re.MULTILINE
    )

    interval = int(interval_match.group(1)) if interval_match else 0
    count = int(count_match.group(1)) if count_match else 3  # SSH default

    issues = []
    if interval <= 0 or interval > 600:
        issues.append(f"ClientAliveInterval={interval} (must be 1-600)")
    if count == 0:
        issues.append(
            "ClientAliveCountMax=0 disables client alive messages entirely"
        )

    effective = f"ClientAliveInterval={interval}, ClientAliveCountMax={count}"
    status = "PASS" if not issues else "FAIL"

    if issues:
        explanation = (
            f"Effective: {effective}. Issues: {'; '.join(issues)}. "
            f"When ClientAliveCountMax is 0, the server never sends keepalive "
            f"probes, making ClientAliveInterval meaningless for idle timeout."
        )
    else:
        explanation = (
            f"Effective: {effective}. Both settings correctly configured. "
            f"ClientAliveInterval defines the probe interval and "
            f"ClientAliveCountMax must be >0 for probes to be sent."
        )

    return {
        "id": "STIG-SSH-002",
        "status": status,
        "effective_value": effective,
        "expected_value": "ClientAliveInterval<=600 and ClientAliveCountMax>0",
        "explanation": explanation,
    }


def check_stig_pam_001():
    """Effective pam_faillock deny threshold must be <= 3.
    Inline arguments on pam_faillock.so lines in PAM config files take
    precedence over settings in /etc/security/faillock.conf.
    """
    content = _read_file("/etc/pam.d/common-auth")

    # Check for inline deny= on pam_faillock.so lines (takes precedence)
    inline_deny = None
    for line in content.splitlines():
        if line.strip().startswith("#") or "pam_faillock.so" not in line:
            continue
        m = re.search(r"\bdeny=(\d+)", line)
        if m:
            inline_deny = int(m.group(1))
            break

    # Check faillock.conf
    conf_deny = None
    conf = _read_file("/etc/security/faillock.conf")
    m = re.search(r"^\s*deny\s*=\s*(\d+)", conf, re.MULTILINE)
    if m:
        conf_deny = int(m.group(1))

    # Inline takes precedence over conf file
    effective = inline_deny if inline_deny is not None else conf_deny
    if effective is None:
        effective = 3  # Default

    source = "inline PAM argument" if inline_deny is not None else "faillock.conf"
    status = "PASS" if 0 < effective <= 3 else "FAIL"

    explanation = (
        f"Effective deny={effective} from {source}. "
        f"faillock.conf has deny={conf_deny}. "
    )
    if inline_deny is not None:
        explanation += (
            f"Inline deny={inline_deny} on pam_faillock.so overrides "
            f"faillock.conf value. "
        )
    explanation += (
        "Inline PAM module arguments take precedence over settings "
        "in the conf file."
    )

    return {
        "id": "STIG-PAM-001",
        "status": status,
        "effective_value": str(effective),
        "expected_value": "<=3",
        "explanation": explanation,
    }


def check_stig_pam_002():
    """Effective pam_pwquality minlen must be >= 15.
    Inline arguments on pam_pwquality.so in PAM config take precedence
    over settings in /etc/security/pwquality.conf.
    """
    content = _read_file("/etc/pam.d/common-password")

    inline_minlen = None
    for line in content.splitlines():
        if line.strip().startswith("#") or "pam_pwquality.so" not in line:
            continue
        m = re.search(r"\bminlen=(\d+)", line)
        if m:
            inline_minlen = int(m.group(1))
            break

    conf_minlen = None
    conf = _read_file("/etc/security/pwquality.conf")
    m = re.search(r"^\s*minlen\s*=\s*(\d+)", conf, re.MULTILINE)
    if m:
        conf_minlen = int(m.group(1))

    effective = inline_minlen if inline_minlen is not None else conf_minlen
    if effective is None:
        effective = 8  # Default

    source = "inline PAM argument" if inline_minlen is not None else "pwquality.conf"
    status = "PASS" if effective >= 15 else "FAIL"

    explanation = (
        f"Effective minlen={effective} from {source}. "
        f"pwquality.conf has minlen={conf_minlen}. "
    )
    if inline_minlen is not None:
        explanation += (
            f"Inline minlen={inline_minlen} on pam_pwquality.so overrides "
            f"pwquality.conf value. "
        )
    explanation += (
        "Inline PAM module arguments take precedence over conf file settings."
    )

    return {
        "id": "STIG-PAM-002",
        "status": status,
        "effective_value": str(effective),
        "expected_value": ">=15",
        "explanation": explanation,
    }


def check_stig_audit_001():
    """max_log_file_action must be ROTATE, SYSLOG, or HALT.
    IGNORE causes audit logs to be silently discarded at max size.
    """
    content = _read_file("/etc/audit/auditd.conf")
    match = re.search(
        r"^\s*max_log_file_action\s*=\s*(\S+)", content, re.MULTILINE
    )

    action = match.group(1).upper() if match else "UNKNOWN"
    acceptable = {"ROTATE", "SYSLOG", "HALT"}
    status = "PASS" if action in acceptable else "FAIL"

    explanation = f"max_log_file_action={action}. "
    if status == "PASS":
        explanation += f"Value is in the acceptable set: {', '.join(sorted(acceptable))}."
    else:
        explanation += (
            f"Value must be one of {', '.join(sorted(acceptable))}. "
            f"'{action}' causes audit logs to be silently discarded or "
            f"ignored when they reach maximum configured size."
        )

    return {
        "id": "STIG-AUDIT-001",
        "status": status,
        "effective_value": action,
        "expected_value": "ROTATE|SYSLOG|HALT",
        "explanation": explanation,
    }


def check_stig_audit_002():
    """All auid filters in audit rules must use >= 1000.
    Legacy auid>=500 fails to audit actions by UIDs 500-999 which are
    assigned to system service accounts on modern Linux.
    """
    rules_dir = "/etc/audit/rules.d/"
    issues = []

    if os.path.isdir(rules_dir):
        for fname in sorted(os.listdir(rules_dir)):
            if not fname.endswith(".rules"):
                continue
            content = _read_file(os.path.join(rules_dir, fname))
            for lineno, line in enumerate(content.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                for m in re.finditer(r"auid>=(\d+)", line):
                    uid = int(m.group(1))
                    if uid < 1000:
                        issues.append(f"{fname}:{lineno} uses auid>={uid}")

    status = "PASS" if not issues else "FAIL"
    effective = (
        "all auid>=1000"
        if not issues
        else f"legacy thresholds: {'; '.join(issues[:5])}"
    )

    explanation = (
        f"{'All' if not issues else 'Not all'} auid filters use >=1000. "
    )
    if issues:
        explanation += f"Issues found: {'; '.join(issues)}. "
    explanation += (
        "Modern Linux assigns UIDs 500-999 to system service accounts; "
        "using auid>=500 fails to audit service account actions."
    )

    return {
        "id": "STIG-AUDIT-002",
        "status": status,
        "effective_value": effective,
        "expected_value": "all auid>=1000",
        "explanation": explanation,
    }


def check_stig_sess_001():
    """TMOUT must be set and not overridden by later profile.d scripts.
    Scripts in /etc/profile.d/ execute in lexicographic order; a later
    script can unset or zero TMOUT, negating an earlier setting.
    """
    tmout_value = None
    tmout_source = None
    tmout_unset = False
    unset_source = None

    profiled = "/etc/profile.d/"
    if os.path.isdir(profiled):
        for fname in sorted(os.listdir(profiled)):
            if not fname.endswith(".sh"):
                continue
            content = _read_file(os.path.join(profiled, fname))
            for line in content.splitlines():
                if line.strip().startswith("#"):
                    continue
                m = re.search(r"(?:export\s+)?TMOUT=(\d+)", line)
                if m:
                    val = int(m.group(1))
                    if val > 0:
                        tmout_value = val
                        tmout_source = fname
                        tmout_unset = False
                if "unset TMOUT" in line:
                    tmout_unset = True
                    unset_source = fname
                if re.search(r"\bTMOUT\s*=\s*0\b", line):
                    tmout_unset = True
                    unset_source = fname

    effective = 0 if tmout_unset else (tmout_value or 0)
    status = "PASS" if effective > 0 and not tmout_unset else "FAIL"

    explanation = f"TMOUT={'unset' if tmout_unset else tmout_value or 'not set'}. "
    if tmout_source:
        explanation += f"Set to {tmout_value} in {tmout_source}. "
    else:
        explanation += "Not set in any profile.d script. "
    if tmout_unset:
        explanation += (
            f"Overridden by {unset_source} which unsets TMOUT. "
        )
    explanation += (
        "Profile.d scripts execute in lexicographic order; "
        "later scripts can override earlier ones."
    )

    return {
        "id": "STIG-SESS-001",
        "status": status,
        "effective_value": str(effective) if not tmout_unset else "unset",
        "expected_value": "<=600 and >0",
        "explanation": explanation,
    }


def check_stig_kern_001():
    """kernel.randomize_va_space must be effectively 2.
    Sysctl parameters are resolved across /etc/sysctl.conf and /etc/sysctl.d/
    drop-in files. Drop-in files are processed in lexicographic order and
    override sysctl.conf values. Within sysctl.d, later files (higher
    lexicographic names) override earlier ones. Last assignment wins.
    """
    effective = None
    source = None

    # Read main sysctl.conf first
    content = _read_file("/etc/sysctl.conf")
    m = re.search(
        r"^\s*kernel\.randomize_va_space\s*=\s*(\d+)", content, re.MULTILINE
    )
    if m:
        effective = int(m.group(1))
        source = "sysctl.conf"

    # Then sysctl.d drop-ins (sorted, last wins — overrides sysctl.conf)
    sysctl_d = "/etc/sysctl.d/"
    if os.path.isdir(sysctl_d):
        for fname in sorted(os.listdir(sysctl_d)):
            if not fname.endswith(".conf"):
                continue
            content = _read_file(os.path.join(sysctl_d, fname))
            m = re.search(
                r"^\s*kernel\.randomize_va_space\s*=\s*(\d+)",
                content,
                re.MULTILINE,
            )
            if m:
                effective = int(m.group(1))
                source = f"sysctl.d/{fname}"

    if effective is None:
        effective = 2  # Kernel default
        source = "kernel default"

    status = "PASS" if effective == 2 else "FAIL"
    explanation = (
        f"Effective kernel.randomize_va_space={effective} from {source}. "
        f"Sysctl.d drop-in files with higher lexicographic names override "
        f"both earlier drop-ins and /etc/sysctl.conf. Last assignment wins."
    )

    return {
        "id": "STIG-KERN-001",
        "status": status,
        "effective_value": str(effective),
        "expected_value": "2",
        "explanation": explanation,
    }


def main():
    results = [
        check_stig_ssh_001(),
        check_stig_ssh_002(),
        check_stig_pam_001(),
        check_stig_pam_002(),
        check_stig_audit_001(),
        check_stig_audit_002(),
        check_stig_sess_001(),
        check_stig_kern_001(),
    ]

    with open("/app/validator_results.json", "w") as f:
        json.dump(results, f, indent=2)

    all_pass = all(r["status"] == "PASS" for r in results)
    for r in results:
        marker = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"[{marker}] {r['id']}: {r['effective_value']}")

    print(f"\nOverall: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")
    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
