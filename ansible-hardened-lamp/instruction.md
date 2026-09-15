An Ansible project at `/app/` implements a `hardened_lamp` role to configure a security-hardened Apache web server on Ubuntu. The project uses a custom Python filter plugin (`filter_plugins/net_utils.py`), Jinja2 templates for SSH/firewall/Apache/fail2ban configuration, and variables organized across `defaults/`, `vars/`, `group_vars/`, and `host_vars/` directories. All required system packages (apache2, openssh-server, fail2ban, iptables) are pre-installed.

The project has multiple defects spanning Python code, Jinja2 templates, YAML task definitions, Ansible variable precedence, module selection, fact-gathering dependencies, and security configuration. Some defects cause playbook failures; others silently produce non-compliant system state. Defects are interconnected — fixing one may reveal or depend on another.

Additionally, the role's task sequence includes a final validation step (`tasks/validate.yml`) that invokes a custom Ansible module `security_baseline_check` to programmatically validate the deployed configuration and generate a machine-readable compliance report. This module was never implemented — design and create it within the role's directory structure following Ansible module conventions.

Audit the entire project, remediate all defects, and implement the missing module so that `ansible-playbook -i /app/inventory/hosts /app/playbook.yml` succeeds and produces the following compliant state:

## SSH (`/etc/ssh/sshd_config`)
- Port 2849
- PermitRootLogin no
- PasswordAuthentication no
- MaxAuthTries 3
- ClientAliveInterval 300

## Firewall (`/etc/network/iptables.sh`)
- Script exists and is executable
- Allowed inbound TCP ports: 2849 (SSH), 80 (HTTP), 443 (HTTPS)
- Trusted RFC1918 networks with full access: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (network addresses must be mathematically correct, not byte-reversed)
- All per-port ACCEPT rules and per-network ACCEPT rules must appear before any REJECT rule in the iptables chain ordering

## Apache (`/etc/apache2/sites-available/webserver01.conf`)
- ServerName webserver01.example.com
- ServerAlias includes www.example.com
- Security headers present: X-Content-Type-Options, X-Frame-Options

## fail2ban (`/etc/fail2ban/jail.local`)
- SSH jail enabled, monitoring port 2849
- maxretry = 3
- bantime = 3600

## Custom Filter Plugin
The `cidr_to_network` filter in `filter_plugins/net_utils.py` must correctly compute network addresses from CIDR notation by applying the subnet mask to the IP address (e.g., `192.168.1.100/24` → `192.168.1.0/24`, `172.31.255.255/12` → `172.16.0.0/12`).

## Compliance Report
The custom module must generate a JSON compliance report at `/var/log/security_compliance.json` containing:
- `overall_compliant` (boolean): true when all security domains pass validation
- `domains` (object): keyed by domain name (`ssh`, `firewall`, `apache`, `fail2ban`), each containing:
  - `compliant` (boolean)
  - `checks` (list): each item has `name` (string) and `pass` (boolean)
- `total_checks` (integer): total number of individual checks performed (minimum 10)
- `passed_checks` (integer): number of checks that passed

The module must accept the parameters defined in `tasks/validate.yml`, read the actual deployed configuration files to validate them against expected values, and return success only when all checks pass. The report must reflect actual file inspection, not hardcoded values.

## Packages
The packages apache2, openssh-server, and fail2ban must be installed on the system.