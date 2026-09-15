The file `/app/harden.sh` is a CIS Distribution Independent Linux Benchmark Level 1 security hardening script. It remediates controls across four areas: kernel network parameters (sysctl 3.x), SSH server configuration (5.2.x), system file permissions (6.1.x), and audit system rules (4.1.x). The system starts with deliberately insecure defaults. The script contains multiple bugs that prevent correct hardening.

Fix all bugs in `/app/harden.sh` so that running it produces a correctly hardened configuration per CIS Level 1 requirements.

Create `/app/audit.sh` that verifies the hardened state and writes a JSON compliance report to `/app/compliance_report.json` with this structure:

```json
{
  "timestamp": "<ISO 8601>",
  "controls": [
    {"id": "<CIS ID>", "title": "<title>", "status": "pass"|"fail", "detail": "<description>"}
  ],
  "summary": {"total": <int>, "pass": <int>, "fail": <int>}
}
```

The audit must check at minimum:
- Sysctl parameters in `/etc/sysctl.d/` for CIS 3.1.x and 3.2.x (IP forwarding, ICMP redirects, source routing, reverse path filtering, SYN cookies, martian logging)
- SSH directives in `/etc/ssh/sshd_config` for CIS 5.2.x (log level, authentication limits, root login, idle timeout, ciphers, MACs, key exchange, banner)
- File modes and ownership for `/etc/passwd`, `/etc/shadow`, `/etc/group`, `/etc/gshadow` and their backup files per CIS 6.1.2-6.1.9
- Audit rules in `/etc/audit/rules.d/` for CIS 4.1.x (time-change, identity, system-locale, scope, modules, immutable flag)

Success criteria:
- Both scripts executable, exit 0
- All controls in the report show `"status": "pass"`
- `summary.total == len(controls)` and `summary.pass + summary.fail == summary.total`
- Report contains at least 20 distinct controls
- Sysctl uses `/etc/sysctl.d/` drop-in files, not `/etc/sysctl.conf`
- Cipher/MAC lists contain only CIS-approved algorithms (no CBC-mode, no weak MACs)
- Audit rules include architecture-appropriate variants
