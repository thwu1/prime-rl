#!/bin/bash
set -e

# Create broken project directory structure
mkdir -p /app/project/plugins/inventory
mkdir -p /app/project/plugins/filter
mkdir -p /app/project/plugins/modules
mkdir -p /app/project/plugins/callback
mkdir -p /app/project/roles/capacity_audit/tasks
mkdir -p /app/project/roles/compliance_check/tasks
mkdir -p /app/project/templates

# =============================================================================
# Broken ansible.cfg — wrong plugin paths, fleet plugin not enabled,
# missing module library and callback plugin paths
# =============================================================================
cat > /app/project/ansible.cfg << 'CFGEOF'
[defaults]
roles_path = roles
filter_plugins = plugins/filters
inventory_plugins = plugins/inventories

[inventory]
enable_plugins = host_list, yaml, ini, auto

[privilege_escalation]
become = True
become_method = sudo
become_user = root
CFGEOF

# =============================================================================
# Inventory plugin config (correct — points to plugin and data file)
# =============================================================================
cat > /app/project/fleet_inventory.yml << 'INVEOF'
plugin: fleet
fleet_file: /app/fleet_inventory.json
INVEOF

# =============================================================================
# Broken inventory plugin — wrong capacity weights, no decommission filter,
# no usable_hosts, no compound groups
# =============================================================================
cat > /app/project/plugins/inventory/fleet.py << 'PYEOF'
from ansible.plugins.inventory import BaseInventoryPlugin
import json

DOCUMENTATION = r"""
    name: fleet
    plugin_type: inventory
    short_description: Fleet JSON inventory source
    options:
        plugin:
            description: Name of the plugin
            required: true
            choices: ['fleet']
        fleet_file:
            description: Path to the fleet inventory JSON file
            required: true
            type: string
"""


class InventoryModule(BaseInventoryPlugin):
    NAME = 'fleet'

    def verify_file(self, path):
        valid = False
        if super().verify_file(path):
            if path.endswith(('.yml', '.yaml', '.json')):
                valid = True
        return valid

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path, cache)
        self._read_config_data(path)

        fleet_file = self.get_option('fleet_file')

        with open(fleet_file, 'r') as f:
            fleet_data = json.load(f)

        for host in fleet_data.get('hosts', []):
            hostname = host['hostname']
            self.inventory.add_host(hostname)

            self.inventory.set_variable(hostname, 'ansible_host', host.get('ip', '127.0.0.1'))
            self.inventory.set_variable(hostname, 'ansible_connection', 'local')

            res = host.get('resources', {})
            cpu_pct = res.get('allocated_cpu', 0) / res.get('cpu_cores', 1)
            mem_pct = res.get('allocated_memory_bytes', 0) / res.get('memory_bytes', 1)
            disk_pct = res.get('allocated_disk_bytes', 0) / res.get('disk_bytes', 1)
            capacity = cpu_pct * 25 + mem_pct * 35 + disk_pct * 40
            self.inventory.set_variable(hostname, 'capacity_utilization', round(capacity, 2))

            dc = host.get('datacenter', 'unknown')
            self.inventory.add_group(dc)
            self.inventory.add_host(hostname, group=dc)

            role = host.get('role', 'unknown')
            self.inventory.add_group(role)
            self.inventory.add_host(hostname, group=role)
PYEOF

# =============================================================================
# Broken filter plugins — wrong boundaries, wrong thresholds, wrong masking,
# missing cidr_host_count, missing sha256_digest
# =============================================================================
cat > /app/project/plugins/filter/compliance_filters.py << 'PYEOF'
class FilterModule(object):
    def filters(self):
        return {
            'risk_grade': self.risk_grade,
            'capacity_status': self.capacity_status,
            'mask_credential': self.mask_credential,
        }

    def risk_grade(self, score):
        score = float(score)
        if score < 20:
            return 'A'
        elif score < 40:
            return 'B'
        elif score < 60:
            return 'C'
        elif score < 80:
            return 'D'
        else:
            return 'F'

    def capacity_status(self, utilization):
        utilization = float(utilization)
        if utilization < 50:
            return 'green'
        elif utilization < 75:
            return 'yellow'
        else:
            return 'red'

    def mask_credential(self, value):
        value = str(value)
        if len(value) <= 5:
            return '*' * len(value)
        return value[:2] + '*' * (len(value) - 5) + value[-3:]
PYEOF

# =============================================================================
# Broken custom validation module — missing capacity_weights parameter,
# no supports_check_mode, wrong hardcoded weights, wrong threshold operators,
# missing capacity_utilization return, no decommission filter
# =============================================================================
cat > /app/project/plugins/modules/fleet_validate.py << 'PYEOF'
from ansible.module_utils.basic import AnsibleModule
import json

DOCUMENTATION = r"""
module: fleet_validate
short_description: Validate fleet host compliance
options:
    fleet_file:
        description: Path to fleet JSON file
        type: str
        required: true
    hostname:
        description: Host to validate
        type: str
        required: true
    risk_threshold:
        description: Max risk score
        type: str
        required: true
    capacity_threshold:
        description: Max capacity percentage
        type: str
        required: true
"""


def main():
    module = AnsibleModule(
        argument_spec=dict(
            fleet_file=dict(type='str', required=True),
            hostname=dict(type='str', required=True),
            risk_threshold=dict(type='str', required=True),
            capacity_threshold=dict(type='str', required=True),
        ),
    )

    fleet_file = module.params['fleet_file']
    hostname = module.params['hostname']
    risk_threshold = module.params['risk_threshold']
    capacity_threshold = module.params['capacity_threshold']

    with open(fleet_file) as f:
        fleet_data = json.load(f)

    host = None
    for h in fleet_data['hosts']:
        if h['hostname'] == hostname:
            host = h
            break

    if host is None:
        module.fail_json(msg="Host '{}' not found".format(hostname))

    violations = []
    res = host['resources']
    cpu_pct = res['allocated_cpu'] / res['cpu_cores']
    mem_pct = res['allocated_memory_bytes'] / res['memory_bytes']
    disk_pct = res['allocated_disk_bytes'] / res['disk_bytes']
    capacity = cpu_pct * 33 + mem_pct * 33 + disk_pct * 34

    if capacity > float(capacity_threshold):
        violations.append("capacity {:.2f} exceeds threshold".format(capacity))

    if int(host['risk_score']) >= int(risk_threshold):
        violations.append("risk_score {} exceeds threshold".format(host['risk_score']))

    compliant = len(violations) == 0

    module.exit_json(
        changed=False,
        compliant=compliant,
        violations=violations,
        msg="Host {}: {}".format(hostname, 'COMPLIANT' if compliant else 'NON-COMPLIANT')
    )


if __name__ == '__main__':
    main()
PYEOF

# =============================================================================
# Broken callback plugin — wrong base class, wrong class attributes,
# wrong method names, wrong result data access, wrong output path
# =============================================================================
cat > /app/project/plugins/callback/fleet_audit.py << 'PYEOF'
import json
import os

DOCUMENTATION = """
    name: fleet_audit
    type: aggregate
    short_description: Fleet audit logging callback
    description:
        - Logs playbook execution data to a JSON audit file
"""


class CallbackModule(object):
    CALLBACK_NAME = 'audit_plugin'

    def __init__(self):
        self._play = None
        self._tasks_ok = 0
        self._tasks_failed = 0
        self._tasks_changed = 0
        self._task_log = []

    def v2_playbook_on_play_start(self, play):
        self._play = play.get_name()

    def v2_on_runner_ok(self, result):
        self._tasks_ok += 1
        task_data = {
            'task': result.task_name,
            'host': result._host.get_name(),
            'status': 'ok',
            'changed': result.result.get('changed', False)
        }
        self._task_log.append(task_data)
        if result.result.get('changed', False):
            self._tasks_changed += 1

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._tasks_failed += 1

    def v2_playbook_on_stats(self, stats):
        audit_data = {
            'play': self._play,
            'tasks_ok': self._tasks_ok,
            'tasks_failed': self._tasks_failed,
            'tasks_changed': self._tasks_changed,
            'task_log': self._task_log,
        }
        with open('/tmp/audit.json', 'w') as f:
            json.dump(audit_data, f, indent=2)
PYEOF

# =============================================================================
# Broken capacity_audit role — no password hash, no sysctl, no MOTD
# =============================================================================
cat > /app/project/roles/capacity_audit/tasks/main.yml << 'YAMLEOF'
---
- name: Load compliance policies
  ansible.builtin.include_vars:
    file: /app/compliance_policies.yml
    name: policies

- name: Create required system groups
  ansible.builtin.group:
    name: "{{ item }}"
    state: present
  loop: "{{ policies.required_groups }}"

- name: Create required system users
  ansible.builtin.user:
    name: "{{ item.name }}"
    uid: "{{ item.uid }}"
    groups: "{{ item.group }}"
    shell: /bin/bash
    state: present
  loop: "{{ policies.required_users }}"
YAMLEOF

# =============================================================================
# Broken compliance_check role — no fleet_config deployment, no web directory,
# no block/rescue for nginx TLS fallback
# =============================================================================
cat > /app/project/roles/compliance_check/tasks/main.yml << 'YAMLEOF'
---
- name: Deploy HTTPS configuration
  ansible.builtin.copy:
    dest: /etc/nginx/sites-available/fleet
    content: |
      server {
          listen 443 ssl;
          ssl_certificate /etc/ssl/fleet/cert.pem;
          ssl_certificate_key /etc/ssl/fleet/key.pem;
          root /var/www/fleet;
          index index.html;
      }
    mode: '0644'

- name: Enable fleet site
  ansible.builtin.file:
    src: /etc/nginx/sites-available/fleet
    dest: /etc/nginx/sites-enabled/fleet
    state: link

- name: Remove default site
  ansible.builtin.file:
    path: /etc/nginx/sites-enabled/default
    state: absent

- name: Validate nginx configuration
  ansible.builtin.command: nginx -t
  changed_when: false
YAMLEOF

# =============================================================================
# Broken site.yml — wrong vault file, broken validation play with wrong
# parameter name, missing capacity_weights, missing result aggregation
# =============================================================================
cat > /app/project/site.yml << 'YAMLEOF'
---
- name: Fleet automation
  hosts: localhost
  connection: local
  become: yes
  gather_facts: yes
  vars_files:
    - vault_secrets.yml
  roles:
    - capacity_audit
    - compliance_check

- name: Validate fleet
  hosts: localhost
  connection: local
  vars_files:
    - vault_secrets.yml
  tasks:
    - name: Run validation
      fleet_validate:
        fleet_data: /app/fleet_inventory.json
        hostname: "{{ item }}"
        risk_threshold: 50
        capacity_threshold: 80.0
      register: validation_results
      loop:
        - localhost
        - db-primary
        - cache-node
        - app-worker-01
        - monitor-srv
YAMLEOF

# =============================================================================
# Broken audit_report.yml — wrong vault file reference
# =============================================================================
cat > /app/project/audit_report.yml << 'YAMLEOF'
---
- name: Generate compliance report
  hosts: localhost
  connection: local
  become: yes
  gather_facts: no
  vars_files:
    - vault_secrets.yml
  tasks:
    - name: Read fleet data
      ansible.builtin.slurp:
        src: /app/fleet_inventory.json
      register: fleet_raw

    - name: Parse fleet data
      ansible.builtin.set_fact:
        fleet_data: "{{ fleet_raw.content | b64decode | from_json }}"

    - name: Generate report
      ansible.builtin.template:
        src: templates/compliance_report.j2
        dest: /app/project/compliance_report.txt
        mode: '0644'
YAMLEOF

# =============================================================================
# Broken report template — missing computations, no decommission filter,
# no vault secrets section
# =============================================================================
cat > /app/project/templates/compliance_report.j2 << 'J2EOF'
Fleet Compliance Report
=======================

{% for host in fleet_data.hosts %}
Host: {{ host.hostname }}
  Datacenter: {{ host.datacenter }}
  Role: {{ host.role }}
  Risk Score: {{ host.risk_score }}

{% endfor %}
J2EOF
