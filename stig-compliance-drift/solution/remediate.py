#!/usr/bin/env python3
"""Diagnose and remediate 8 subtly broken STIG controls.


Each control appears correctly hardened on superficial inspection but has
a configuration override that renders it ineffective. This script identifies
the root cause of each failure and applies the minimal fix.
"""

import json
import os
import re


def read(path):
    with open(path) as f:
        return f.read()


def write(path, content):
    with open(path, "w") as f:
        f.write(content)


report = []


# ── STIG-SSH-001: PermitRootLogin drop-in override ──────────────────────────
# The main sshd_config has PermitRootLogin no, but the Include directive at the
# top of the file causes drop-in files to be processed first.  OpenSSH uses
# first-match semantics, so 50-cloud-init.conf's PermitRootLogin yes wins.

dropin_dir = "/etc/ssh/sshd_config.d/"
modified = []
for fname in os.listdir(dropin_dir):
    if not fname.endswith(".conf"):
        continue
    fpath = os.path.join(dropin_dir, fname)
    content = read(fpath)
    if re.search(r"^\s*PermitRootLogin\s+yes", content, re.MULTILINE):
        new = re.sub(
            r"^(\s*PermitRootLogin\s+)yes",
            r"\g<1>no",
            content,
            flags=re.MULTILINE,
        )
        write(fpath, new)
        modified.append(fpath)

report.append({
    "id": "STIG-SSH-001",
    "root_cause": (
        "sshd_config.d/50-cloud-init.conf sets PermitRootLogin yes. Because the "
        "Include directive appears before PermitRootLogin no in the main config "
        "and OpenSSH uses first-match semantics, the drop-in value takes effect."
    ),
    "files_modified": modified,
    "fixed": True,
})

# ── STIG-SSH-002: ClientAliveCountMax = 0 disables keepalives ────────────────
# ClientAliveInterval is 600 (correct) but ClientAliveCountMax is 0, which
# means the server never sends client-alive messages at all.

sshd_config = "/etc/ssh/sshd_config"
content = read(sshd_config)
content = re.sub(
    r"^(\s*ClientAliveCountMax\s+)0\s*$",
    r"\g<1>1",
    content,
    flags=re.MULTILINE,
)
write(sshd_config, content)

report.append({
    "id": "STIG-SSH-002",
    "root_cause": (
        "ClientAliveCountMax is set to 0, which disables client alive messages "
        "entirely rather than allowing zero missed responses. This makes "
        "ClientAliveInterval ineffective and sessions never time out."
    ),
    "files_modified": [sshd_config],
    "fixed": True,
})

# ── STIG-PAM-001: Inline deny=99 overrides faillock.conf ────────────────────
# faillock.conf correctly has deny=3, but pam_faillock.so lines in common-auth
# carry inline deny=99 which takes precedence over the config file value.

pam_auth = "/etc/pam.d/common-auth"
content = read(pam_auth)
content = re.sub(r"\s*deny=\d+", "", content)
write(pam_auth, content)

report.append({
    "id": "STIG-PAM-001",
    "root_cause": (
        "pam_faillock.so lines in /etc/pam.d/common-auth have inline deny=99 "
        "arguments. Inline PAM module arguments take precedence over settings "
        "in /etc/security/faillock.conf, so the conf file's deny=3 is ignored."
    ),
    "files_modified": [pam_auth],
    "fixed": True,
})

# ── STIG-PAM-002: Inline minlen=4 overrides pwquality.conf ──────────────────
# pwquality.conf has minlen=15 but the pam_pwquality.so line in common-password
# has an inline minlen=4 that overrides it.

pam_passwd = "/etc/pam.d/common-password"
content = read(pam_passwd)
content = re.sub(r"\s*minlen=\d+", "", content)
write(pam_passwd, content)

report.append({
    "id": "STIG-PAM-002",
    "root_cause": (
        "pam_pwquality.so line in /etc/pam.d/common-password has inline minlen=4. "
        "Inline PAM module arguments override /etc/security/pwquality.conf, so "
        "the conf file's minlen=15 is never applied."
    ),
    "files_modified": [pam_passwd],
    "fixed": True,
})

# ── STIG-AUDIT-001: max_log_file_action = IGNORE ────────────────────────────
# IGNORE causes audit logs to be silently discarded at max size.

auditd_conf = "/etc/audit/auditd.conf"
content = read(auditd_conf)
content = re.sub(
    r"^(\s*max_log_file_action\s*=\s*)IGNORE",
    r"\g<1>ROTATE",
    content,
    flags=re.MULTILINE,
)
write(auditd_conf, content)

report.append({
    "id": "STIG-AUDIT-001",
    "root_cause": (
        "max_log_file_action is set to IGNORE in auditd.conf, causing audit logs "
        "to be silently discarded when they reach max size instead of being "
        "rotated. This can lead to loss of audit evidence."
    ),
    "files_modified": [auditd_conf],
    "fixed": True,
})

# ── STIG-AUDIT-002: auid>=500 (legacy) instead of auid>=1000 ────────────────
# Modern Linux allocates UIDs 500-999 to system service accounts. Using the
# legacy threshold of 500 fails to audit actions by these service UIDs.

rules_dir = "/etc/audit/rules.d/"
modified = []
for fname in os.listdir(rules_dir):
    if not fname.endswith(".rules"):
        continue
    fpath = os.path.join(rules_dir, fname)
    content = read(fpath)
    new = content.replace("auid>=500", "auid>=1000")
    if new != content:
        write(fpath, new)
        modified.append(fpath)

report.append({
    "id": "STIG-AUDIT-002",
    "root_cause": (
        "Audit rules in privileged.rules use legacy auid>=500 filter threshold. "
        "Modern Linux distributions assign UIDs 500-999 to system service "
        "accounts, so the threshold must be auid>=1000 to correctly filter "
        "only human user activity."
    ),
    "files_modified": modified,
    "fixed": True,
})

# ── STIG-SESS-001: TMOUT unset by profile.d/99-custom.sh ────────────────────
# 00-security-tmout.sh sets TMOUT=600, but profile.d scripts run in
# lexicographic order and 99-custom.sh runs after, doing "unset TMOUT".

custom_script = "/etc/profile.d/99-custom.sh"
content = read(custom_script)
lines = content.splitlines()
cleaned = [l for l in lines if "TMOUT" not in l or l.strip().startswith("#")]
write(custom_script, "\n".join(cleaned) + "\n")

report.append({
    "id": "STIG-SESS-001",
    "root_cause": (
        "/etc/profile.d/99-custom.sh contains 'unset TMOUT'. Profile.d scripts "
        "run in lexicographic order, so 99-custom.sh executes after "
        "00-security-tmout.sh and undoes the TMOUT=600 setting."
    ),
    "files_modified": [custom_script],
    "fixed": True,
})

# ── STIG-KERN-001: sysctl.d drop-in overrides ASLR to 0 ────────────────────
# sysctl.conf has kernel.randomize_va_space=2 but 99-override.conf in sysctl.d
# sets it to 0. Drop-in files with higher lexicographic names take precedence.

override_file = "/etc/sysctl.d/99-override.conf"
content = read(override_file)
content = re.sub(
    r"^(\s*kernel\.randomize_va_space\s*=\s*)0",
    r"\g<1>2",
    content,
    flags=re.MULTILINE,
)
write(override_file, content)

report.append({
    "id": "STIG-KERN-001",
    "root_cause": (
        "/etc/sysctl.d/99-override.conf sets kernel.randomize_va_space=0 "
        "(labeled as 'performance tuning'). Sysctl.d drop-in files with higher "
        "lexicographic names override /etc/sysctl.conf, so ASLR is disabled "
        "despite sysctl.conf having the correct value of 2."
    ),
    "files_modified": [override_file],
    "fixed": True,
})

# ── Write report ─────────────────────────────────────────────────────────────

write("/app/remediation_report.json", json.dumps(report, indent=2))
print("Remediation complete. 8 controls fixed.")
print("Report: /app/remediation_report.json")
