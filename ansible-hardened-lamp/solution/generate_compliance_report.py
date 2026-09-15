#!/usr/bin/env python3
"""Fallback compliance report generator.

Reads deployed configuration files and generates the JSON compliance
report at /var/log/security_compliance.json. Used when the Ansible
custom module's validate step does not produce the report.
"""


import json
import os
import re


def validate_ssh():
    """Validate SSH configuration against expected values."""
    checks = []
    with open('/etc/ssh/sshd_config') as f:
        content = f.read()

    port_match = re.search(r'^Port\s+(\S+)', content, re.MULTILINE)
    actual_port = port_match.group(1) if port_match else None
    checks.append({
        'name': 'ssh_port',
        'pass': actual_port == '2849',
        'expected': '2849',
        'actual': actual_port
    })

    root_match = re.search(r'^PermitRootLogin\s+(\S+)', content, re.MULTILINE)
    actual_root = root_match.group(1) if root_match else None
    checks.append({
        'name': 'permit_root_login',
        'pass': actual_root == 'no',
        'expected': 'no',
        'actual': actual_root
    })

    pw_match = re.search(r'^PasswordAuthentication\s+(\S+)', content, re.MULTILINE)
    actual_pw = pw_match.group(1) if pw_match else None
    checks.append({
        'name': 'password_authentication',
        'pass': actual_pw == 'no',
        'expected': 'no',
        'actual': actual_pw
    })

    mat_match = re.search(r'^MaxAuthTries\s+(\S+)', content, re.MULTILINE)
    actual_mat = mat_match.group(1) if mat_match else None
    checks.append({
        'name': 'max_auth_tries',
        'pass': actual_mat == '3',
        'expected': '3',
        'actual': actual_mat
    })

    cai_match = re.search(r'^ClientAliveInterval\s+(\S+)', content, re.MULTILINE)
    actual_cai = cai_match.group(1) if cai_match else None
    checks.append({
        'name': 'client_alive_interval',
        'pass': actual_cai is not None and int(actual_cai) > 0,
        'actual': actual_cai
    })

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def validate_firewall():
    """Validate firewall script content and rule ordering."""
    checks = []
    script_path = '/etc/network/iptables.sh'

    exists = os.path.isfile(script_path)
    checks.append({'name': 'script_exists', 'pass': exists})

    if exists:
        executable = os.access(script_path, os.X_OK)
        checks.append({'name': 'script_executable', 'pass': executable})

        with open(script_path) as f:
            content = f.read()

        for port in [2849, 80, 443]:
            found = f'--dport {port}' in content
            checks.append({'name': f'port_{port}_allowed', 'pass': found})

        accept_positions = [m.start() for m in
                            re.finditer(r'--dport\s+\d+.*-j\s+ACCEPT', content)]
        reject_positions = [m.start() for m in
                            re.finditer(r'-j\s+REJECT', content)]

        if accept_positions and reject_positions:
            ordering_ok = max(accept_positions) < min(reject_positions)
            checks.append({'name': 'accept_before_reject', 'pass': ordering_ok})

        for net in ['10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16']:
            found = net in content
            checks.append({
                'name': f'network_{net.split("/")[0].replace(".", "_")}',
                'pass': found
            })

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def validate_apache():
    """Validate Apache virtual host configuration."""
    checks = []
    with open('/etc/apache2/sites-available/webserver01.conf') as f:
        content = f.read()

    checks.append({
        'name': 'server_name',
        'pass': 'ServerName webserver01.example.com' in content,
        'expected': 'webserver01.example.com'
    })

    checks.append({
        'name': 'x_content_type_options',
        'pass': 'X-Content-Type-Options' in content
    })

    checks.append({
        'name': 'x_frame_options',
        'pass': 'X-Frame-Options' in content
    })

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def validate_fail2ban():
    """Validate fail2ban jail configuration."""
    checks = []
    with open('/etc/fail2ban/jail.local') as f:
        content = f.read()

    maxretry_match = re.search(r'^maxretry\s*=\s*(\S+)', content, re.MULTILINE)
    actual_maxretry = maxretry_match.group(1) if maxretry_match else None
    checks.append({
        'name': 'maxretry',
        'pass': actual_maxretry == '3',
        'expected': '3',
        'actual': actual_maxretry
    })

    bantime_match = re.search(r'^bantime\s*=\s*(\S+)', content, re.MULTILINE)
    actual_bantime = bantime_match.group(1) if bantime_match else None
    checks.append({
        'name': 'bantime',
        'pass': actual_bantime == '3600',
        'expected': '3600',
        'actual': actual_bantime
    })

    port_match = re.search(r'^port\s*=\s*(\S+)', content, re.MULTILINE)
    actual_port = port_match.group(1) if port_match else None
    checks.append({
        'name': 'ssh_port_monitored',
        'pass': actual_port is not None and '2849' in actual_port,
        'actual': actual_port
    })

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def main():
    results = {
        'ssh': validate_ssh(),
        'firewall': validate_firewall(),
        'apache': validate_apache(),
        'fail2ban': validate_fail2ban(),
    }

    overall = all(d['compliant'] for d in results.values())
    total = sum(len(d['checks']) for d in results.values())
    passed = sum(
        sum(1 for c in d['checks'] if c['pass'])
        for d in results.values()
    )

    report = {
        'overall_compliant': overall,
        'domains': results,
        'total_checks': total,
        'passed_checks': passed,
    }

    os.makedirs('/var/log', exist_ok=True)
    with open('/var/log/security_compliance.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Compliance report generated: overall_compliant={overall}, "
          f"total={total}, passed={passed}")


if __name__ == '__main__':
    main()
