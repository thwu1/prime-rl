"""Tests for the hardened web server Ansible configuration.

Verify that all configuration files reflect the intended security posture
after the Ansible playbook has been successfully run, and that the custom
security_baseline_check module was properly implemented.
"""


import importlib.util
import json
import os
import re
import subprocess

import pytest


class TestSSHHardening:
    """Verify SSH configuration is properly hardened."""

    def test_sshd_config_exists(self):
        assert os.path.isfile('/etc/ssh/sshd_config'), \
            "sshd_config was not deployed"

    def test_ssh_port_2849(self):
        with open('/etc/ssh/sshd_config') as f:
            content = f.read()
        assert re.search(r'^Port\s+2849\s*$', content, re.MULTILINE), \
            "SSH must listen on port 2849"

    def test_no_root_login(self):
        with open('/etc/ssh/sshd_config') as f:
            content = f.read()
        assert re.search(r'^PermitRootLogin\s+no\s*$', content, re.MULTILINE), \
            "Root login must be disabled"

    def test_no_password_auth(self):
        with open('/etc/ssh/sshd_config') as f:
            content = f.read()
        assert re.search(r'^PasswordAuthentication\s+no\s*$', content, re.MULTILINE), \
            "Password authentication must be disabled"

    def test_max_auth_tries(self):
        with open('/etc/ssh/sshd_config') as f:
            content = f.read()
        assert re.search(r'^MaxAuthTries\s+3\s*$', content, re.MULTILINE), \
            "MaxAuthTries must be set to 3"

    def test_client_alive_interval(self):
        with open('/etc/ssh/sshd_config') as f:
            content = f.read()
        assert re.search(r'^ClientAliveInterval\s+300\s*$', content, re.MULTILINE), \
            "ClientAliveInterval must be set to 300"


class TestFirewallScript:
    """Verify the iptables firewall script content and rule ordering."""

    def test_iptables_script_exists(self):
        assert os.path.isfile('/etc/network/iptables.sh'), \
            "Firewall script was not generated"

    def test_iptables_script_executable(self):
        assert os.access('/etc/network/iptables.sh', os.X_OK), \
            "Firewall script must be executable"

    def test_port_accept_before_reject(self):
        """All port-specific ACCEPT rules must appear before the REJECT rule."""
        with open('/etc/network/iptables.sh') as f:
            content = f.read()

        port_accepts = list(re.finditer(r'--dport\s+\d+\s+.*-j\s+ACCEPT', content))
        rejects = list(re.finditer(r'-j\s+REJECT', content))

        assert len(port_accepts) > 0, "No port ACCEPT rules found"
        assert len(rejects) > 0, "No REJECT rule found"

        last_accept_pos = port_accepts[-1].start()
        first_reject_pos = rejects[0].start()

        assert last_accept_pos < first_reject_pos, \
            "Port ACCEPT rules must come before REJECT rule (iptables chain ordering)"

    def test_network_accept_before_reject(self):
        """Trusted network ACCEPT rules must appear before the REJECT rule."""
        with open('/etc/network/iptables.sh') as f:
            content = f.read()

        net_accepts = list(re.finditer(r'-s\s+\S+\s+-j\s+ACCEPT', content))
        rejects = list(re.finditer(r'-j\s+REJECT', content))

        assert len(net_accepts) > 0, "No network ACCEPT rules found"
        assert len(rejects) > 0, "No REJECT rule found"

        last_net_accept = net_accepts[-1].start()
        first_reject = rejects[0].start()

        assert last_net_accept < first_reject, \
            "Network ACCEPT rules must come before REJECT rule"

    def test_correct_network_10(self):
        """10.0.0.0/8 must appear correctly (not byte-reversed)."""
        with open('/etc/network/iptables.sh') as f:
            content = f.read()
        assert '10.0.0.0/8' in content, \
            "10.0.0.0/8 network missing or byte-reversed in firewall script"

    def test_correct_network_172(self):
        """172.16.0.0/12 must appear correctly (not byte-reversed)."""
        with open('/etc/network/iptables.sh') as f:
            content = f.read()
        assert '172.16.0.0/12' in content, \
            "172.16.0.0/12 network missing or byte-reversed in firewall script"

    def test_correct_network_192(self):
        """192.168.0.0/16 must appear correctly (not byte-reversed)."""
        with open('/etc/network/iptables.sh') as f:
            content = f.read()
        assert '192.168.0.0/16' in content, \
            "192.168.0.0/16 network missing or byte-reversed in firewall script"

    def test_allowed_port_ssh(self):
        with open('/etc/network/iptables.sh') as f:
            content = f.read()
        assert '--dport 2849' in content, "SSH port 2849 must be allowed"

    def test_allowed_port_http(self):
        with open('/etc/network/iptables.sh') as f:
            content = f.read()
        assert '--dport 80' in content, "HTTP port 80 must be allowed"

    def test_allowed_port_https(self):
        with open('/etc/network/iptables.sh') as f:
            content = f.read()
        assert '--dport 443' in content, "HTTPS port 443 must be allowed"


class TestApacheVhost:
    """Verify Apache virtual host configuration."""

    def test_vhost_file_exists(self):
        assert os.path.isfile('/etc/apache2/sites-available/webserver01.conf'), \
            "Apache vhost config was not deployed"

    def test_vhost_server_name(self):
        with open('/etc/apache2/sites-available/webserver01.conf') as f:
            content = f.read()
        assert 'ServerName webserver01.example.com' in content, \
            "ServerName must be webserver01.example.com"

    def test_vhost_server_alias(self):
        with open('/etc/apache2/sites-available/webserver01.conf') as f:
            content = f.read()
        assert 'ServerAlias www.example.com' in content, \
            "ServerAlias must include www.example.com"

    def test_vhost_security_headers(self):
        with open('/etc/apache2/sites-available/webserver01.conf') as f:
            content = f.read()
        assert 'X-Content-Type-Options' in content, \
            "X-Content-Type-Options header missing"
        assert 'X-Frame-Options' in content, \
            "X-Frame-Options header missing"


class TestFail2ban:
    """Verify fail2ban configuration."""

    def test_jail_config_exists(self):
        assert os.path.isfile('/etc/fail2ban/jail.local'), \
            "fail2ban jail.local was not deployed"

    def test_jail_ssh_port(self):
        with open('/etc/fail2ban/jail.local') as f:
            content = f.read()
        assert re.search(r'^port\s*=\s*2849\s*$', content, re.MULTILINE), \
            "fail2ban SSH jail must monitor port 2849"

    def test_jail_maxretry(self):
        with open('/etc/fail2ban/jail.local') as f:
            content = f.read()
        assert re.search(r'^maxretry\s*=\s*3\s*$', content, re.MULTILINE), \
            "fail2ban maxretry must be 3"

    def test_jail_bantime(self):
        with open('/etc/fail2ban/jail.local') as f:
            content = f.read()
        assert re.search(r'^bantime\s*=\s*3600\s*$', content, re.MULTILINE), \
            "fail2ban bantime must be 3600"


class TestFilterPlugin:
    """Verify the custom filter plugin produces correct results."""

    @pytest.fixture
    def cidr_filter(self):
        spec = importlib.util.spec_from_file_location(
            "net_utils",
            "/app/roles/hardened_lamp/filter_plugins/net_utils.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fm = module.FilterModule()
        return fm.filters()['cidr_to_network']

    def test_class_a_network(self, cidr_filter):
        assert cidr_filter('10.0.0.0/8') == '10.0.0.0/8'

    def test_class_b_rfc1918(self, cidr_filter):
        assert cidr_filter('172.16.0.0/12') == '172.16.0.0/12'

    def test_class_c_rfc1918(self, cidr_filter):
        assert cidr_filter('192.168.0.0/16') == '192.168.0.0/16'

    def test_host_to_network_24(self, cidr_filter):
        """A host address should be masked to its /24 network."""
        assert cidr_filter('192.168.1.100/24') == '192.168.1.0/24'

    def test_host_to_network_16(self, cidr_filter):
        """A host address should be masked to its /16 network."""
        assert cidr_filter('10.10.10.10/16') == '10.10.0.0/16'

    def test_host_to_network_varied(self, cidr_filter):
        """Non-trivial masking across octets."""
        assert cidr_filter('172.31.255.255/12') == '172.16.0.0/12'


class TestPackages:
    """Verify required packages are installed."""

    def test_apache_installed(self):
        result = subprocess.run(
            ['dpkg', '-l', 'apache2'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, "apache2 package must be installed"

    def test_openssh_installed(self):
        result = subprocess.run(
            ['dpkg', '-l', 'openssh-server'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, "openssh-server package must be installed"

    def test_fail2ban_installed(self):
        result = subprocess.run(
            ['dpkg', '-l', 'fail2ban'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, "fail2ban package must be installed"


class TestSecurityBaselineModule:
    """Verify the custom Ansible module exists and is properly structured."""

    MODULE_PATH = '/app/roles/hardened_lamp/library/security_baseline_check.py'

    def test_module_file_exists(self):
        assert os.path.isfile(self.MODULE_PATH), \
            "security_baseline_check module must exist in the role's library/ directory"

    def test_module_is_valid_python(self):
        """Module must be syntactically valid Python."""
        result = subprocess.run(
            ['python3', '-c',
             f'import py_compile; py_compile.compile("{self.MODULE_PATH}", doraise=True)'],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"Module has syntax errors: {result.stderr}"

    def test_module_uses_ansible_api(self):
        """Module must use AnsibleModule from ansible.module_utils.basic."""
        with open(self.MODULE_PATH) as f:
            content = f.read()
        assert 'AnsibleModule' in content, \
            "Module must use AnsibleModule from ansible.module_utils.basic"
        assert 'argument_spec' in content, \
            "Module must define argument_spec for its parameters"

    def test_module_importable_with_main(self):
        """Module must be importable and have a main() function."""
        spec = importlib.util.spec_from_file_location(
            "security_baseline_check", self.MODULE_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, 'main'), \
            "Module must have a callable main() function"

    def test_module_accepts_required_params(self):
        """Module's argument_spec must include the parameters from validate.yml."""
        with open(self.MODULE_PATH) as f:
            content = f.read()
        required_params = [
            'ssh_config', 'firewall_script', 'apache_vhost',
            'fail2ban_jail', 'expected_ssh_port', 'report_path'
        ]
        for param in required_params:
            assert param in content, \
                f"Module argument_spec must include '{param}' parameter"


class TestComplianceReport:
    """Verify the compliance report generated by the custom module."""

    REPORT_PATH = '/var/log/security_compliance.json'

    def test_report_exists(self):
        assert os.path.isfile(self.REPORT_PATH), \
            "Compliance report must exist at /var/log/security_compliance.json"

    def test_report_valid_json(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        assert isinstance(data, dict), "Report must be a JSON object"

    def test_report_overall_compliant(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        assert data.get('overall_compliant') is True, \
            "Report must indicate overall compliance (overall_compliant: true)"

    def test_report_has_all_domains(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        domains = data.get('domains', {})
        for domain in ['ssh', 'firewall', 'apache', 'fail2ban']:
            assert domain in domains, \
                f"Report must include '{domain}' domain"

    def test_report_all_domains_compliant(self):
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        domains = data.get('domains', {})
        for name, domain in domains.items():
            assert domain.get('compliant') is True, \
                f"Domain '{name}' must be compliant"

    def test_report_checks_have_structure(self):
        """Each domain must have structured checks with name and pass fields."""
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        domains = data.get('domains', {})
        for name, domain in domains.items():
            checks = domain.get('checks', [])
            assert len(checks) >= 2, \
                f"Domain '{name}' must have at least 2 checks"
            for check in checks:
                assert 'name' in check, \
                    f"Each check in '{name}' must have a 'name' field"
                assert 'pass' in check, \
                    f"Each check in '{name}' must have a 'pass' field"
                assert check['pass'] is True, \
                    f"Check '{check.get('name')}' in '{name}' must pass"

    def test_report_check_counts(self):
        """Report must track total and passed check counts."""
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        total = data.get('total_checks', 0)
        passed = data.get('passed_checks', 0)
        assert total >= 10, \
            f"Report must have at least 10 total checks, got {total}"
        assert total == passed, \
            f"All checks must pass: total_checks ({total}) != passed_checks ({passed})"

    def test_report_reflects_actual_config(self):
        """Verify report checks are consistent with actual deployed SSH config."""
        with open(self.REPORT_PATH) as f:
            data = json.load(f)
        ssh_checks = data.get('domains', {}).get('ssh', {}).get('checks', [])
        check_names = [c.get('name', '') for c in ssh_checks]
        # The module must inspect actual SSH config — at minimum checking the port
        has_port_check = any('port' in name.lower() for name in check_names)
        assert has_port_check, \
            "SSH domain must include a port validation check"
