#!/usr/bin/env python3
"""Custom Ansible module: security_baseline_check

Validates deployed security configurations against expected policy values
and generates a structured JSON compliance report.
"""


import json
import os
import re

from ansible.module_utils.basic import AnsibleModule


def validate_ssh(config_path, expected_port, expected_root_login,
                 expected_password_auth, expected_max_auth_tries):
    """Validate SSH configuration against expected values."""
    checks = []
    try:
        with open(config_path) as f:
            content = f.read()

        port_match = re.search(r'^Port\s+(\S+)', content, re.MULTILINE)
        actual_port = port_match.group(1) if port_match else None
        checks.append({
            'name': 'ssh_port',
            'pass': actual_port == str(expected_port),
            'expected': str(expected_port),
            'actual': actual_port
        })

        root_match = re.search(r'^PermitRootLogin\s+(\S+)', content, re.MULTILINE)
        actual_root = root_match.group(1) if root_match else None
        checks.append({
            'name': 'permit_root_login',
            'pass': actual_root == expected_root_login,
            'expected': expected_root_login,
            'actual': actual_root
        })

        pw_match = re.search(r'^PasswordAuthentication\s+(\S+)', content, re.MULTILINE)
        actual_pw = pw_match.group(1) if pw_match else None
        checks.append({
            'name': 'password_authentication',
            'pass': actual_pw == expected_password_auth,
            'expected': expected_password_auth,
            'actual': actual_pw
        })

        mat_match = re.search(r'^MaxAuthTries\s+(\S+)', content, re.MULTILINE)
        actual_mat = mat_match.group(1) if mat_match else None
        checks.append({
            'name': 'max_auth_tries',
            'pass': actual_mat == str(expected_max_auth_tries),
            'expected': str(expected_max_auth_tries),
            'actual': actual_mat
        })

        cai_match = re.search(r'^ClientAliveInterval\s+(\S+)', content, re.MULTILINE)
        actual_cai = cai_match.group(1) if cai_match else None
        checks.append({
            'name': 'client_alive_interval',
            'pass': actual_cai is not None and int(actual_cai) > 0,
            'actual': actual_cai
        })

    except (IOError, OSError) as e:
        checks.append({'name': 'file_readable', 'pass': False, 'error': str(e)})

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def validate_firewall(script_path):
    """Validate firewall script content and rule ordering."""
    checks = []
    try:
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

    except (IOError, OSError) as e:
        checks.append({'name': 'file_readable', 'pass': False, 'error': str(e)})

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def validate_apache(config_path, expected_server_name):
    """Validate Apache virtual host configuration."""
    checks = []
    try:
        with open(config_path) as f:
            content = f.read()

        checks.append({
            'name': 'server_name',
            'pass': f'ServerName {expected_server_name}' in content,
            'expected': expected_server_name
        })

        checks.append({
            'name': 'x_content_type_options',
            'pass': 'X-Content-Type-Options' in content
        })

        checks.append({
            'name': 'x_frame_options',
            'pass': 'X-Frame-Options' in content
        })

    except (IOError, OSError) as e:
        checks.append({'name': 'file_readable', 'pass': False, 'error': str(e)})

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def validate_fail2ban(config_path, expected_maxretry, expected_bantime):
    """Validate fail2ban jail configuration."""
    checks = []
    try:
        with open(config_path) as f:
            content = f.read()

        maxretry_match = re.search(r'^maxretry\s*=\s*(\S+)', content, re.MULTILINE)
        actual_maxretry = maxretry_match.group(1) if maxretry_match else None
        checks.append({
            'name': 'maxretry',
            'pass': actual_maxretry == str(expected_maxretry),
            'expected': str(expected_maxretry),
            'actual': actual_maxretry
        })

        bantime_match = re.search(r'^bantime\s*=\s*(\S+)', content, re.MULTILINE)
        actual_bantime = bantime_match.group(1) if bantime_match else None
        checks.append({
            'name': 'bantime',
            'pass': actual_bantime == str(expected_bantime),
            'expected': str(expected_bantime),
            'actual': actual_bantime
        })

        port_match = re.search(r'^port\s*=\s*(\S+)', content, re.MULTILINE)
        actual_port = port_match.group(1) if port_match else None
        checks.append({
            'name': 'ssh_port_monitored',
            'pass': actual_port is not None and '2849' in actual_port,
            'actual': actual_port
        })

    except (IOError, OSError) as e:
        checks.append({'name': 'file_readable', 'pass': False, 'error': str(e)})

    return {
        'compliant': all(c['pass'] for c in checks),
        'checks': checks
    }


def main():
    argument_spec = dict(
        ssh_config=dict(type='str', required=True),
        firewall_script=dict(type='str', required=True),
        apache_vhost=dict(type='str', required=True),
        fail2ban_jail=dict(type='str', required=True),
        expected_ssh_port=dict(type='int', required=True),
        expected_root_login=dict(type='str', required=True),
        expected_password_auth=dict(type='str', required=True),
        expected_max_auth_tries=dict(type='int', required=True),
        expected_fail2ban_maxretry=dict(type='int', required=True),
        expected_fail2ban_bantime=dict(type='int', required=True),
        expected_server_name=dict(type='str', required=True),
        report_path=dict(type='str', default='/var/log/security_compliance.json'),
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
    )

    params = module.params

    results = {
        'ssh': validate_ssh(
            params['ssh_config'],
            params['expected_ssh_port'],
            params['expected_root_login'],
            params['expected_password_auth'],
            params['expected_max_auth_tries']
        ),
        'firewall': validate_firewall(params['firewall_script']),
        'apache': validate_apache(
            params['apache_vhost'],
            params['expected_server_name']
        ),
        'fail2ban': validate_fail2ban(
            params['fail2ban_jail'],
            params['expected_fail2ban_maxretry'],
            params['expected_fail2ban_bantime']
        ),
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

    report_path = params['report_path']
    report_dir = os.path.dirname(report_path)
    if report_dir:
        os.makedirs(report_dir, exist_ok=True)
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)

    if overall:
        module.exit_json(changed=False,
                         msg="Security baseline validated — all checks passed",
                         report=report)
    else:
        module.fail_json(msg="Security baseline violations detected",
                         report=report)


if __name__ == '__main__':
    main()
