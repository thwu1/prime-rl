#!/bin/bash

set -e

# =============================================================================
# 1. Create project directory structure
# =============================================================================
mkdir -p /app/project/plugins/inventory
mkdir -p /app/project/plugins/filter
mkdir -p /app/project/plugins/modules
mkdir -p /app/project/plugins/callback
mkdir -p /app/project/roles/capacity_audit/tasks
mkdir -p /app/project/roles/capacity_audit/templates
mkdir -p /app/project/roles/compliance_check/tasks
mkdir -p /app/project/roles/compliance_check/templates
mkdir -p /app/project/templates

# =============================================================================
# 2. Install all custom plugins
# =============================================================================
cp /solution/fleet.py /app/project/plugins/inventory/fleet.py
cp /solution/compliance_filters.py /app/project/plugins/filter/compliance_filters.py
cp /solution/fleet_validate.py /app/project/plugins/modules/fleet_validate.py
cp /solution/fleet_audit.py /app/project/plugins/callback/fleet_audit.py

# =============================================================================
# 3. Create ansible.cfg with all four plugin paths
# =============================================================================
cat > /app/project/ansible.cfg << 'CFGEOF'
[defaults]
inventory = /app/project/fleet_inventory.yml
roles_path = /app/project/roles
filter_plugins = /app/project/plugins/filter
inventory_plugins = /app/project/plugins/inventory
library = /app/project/plugins/modules
callback_plugins = /app/project/plugins/callback
callbacks_enabled = fleet_audit
host_key_checking = False
retry_files_enabled = False

[inventory]
enable_plugins = fleet, host_list, yaml, ini, auto

[privilege_escalation]
become = True
become_method = sudo
become_user = root
CFGEOF

# =============================================================================
# 4. Create inventory plugin config
# =============================================================================
cat > /app/project/fleet_inventory.yml << 'INVEOF'
plugin: fleet
fleet_file: /app/fleet_inventory.json
INVEOF

# =============================================================================
# 5. Vault operations: decrypt, add variables, re-encrypt
# =============================================================================
echo "Fl33t_N3w!_S3cur3" > /app/project/vault_pass.txt
echo "Fl33t_0ld!" > /tmp/old_vault_pass.txt

cp /app/seed_vault.yml /tmp/vault_work.yml
ansible-vault decrypt /tmp/vault_work.yml --vault-password-file /tmp/old_vault_pass.txt

cat >> /tmp/vault_work.yml << 'VAULTEOF'
backup_key: "bk-alpha-7742-omega"
deploy_token: "dpt-2024-xK9mL3nP"
VAULTEOF

cp /tmp/vault_work.yml /app/project/secrets.yml
ansible-vault encrypt /app/project/secrets.yml --vault-password-file /app/project/vault_pass.txt
rm -f /tmp/old_vault_pass.txt /tmp/vault_work.yml

# =============================================================================
# 6. Create capacity_audit role
# =============================================================================
cat > /app/project/roles/capacity_audit/tasks/main.yml << 'EOF'
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
    password: "{{ db_master_password | password_hash('sha512', 'fltsalt1') }}"
    shell: /bin/bash
    state: present
  loop: "{{ policies.required_users }}"

- name: Write sysctl tuning configuration
  ansible.builtin.template:
    src: sysctl.conf.j2
    dest: /etc/sysctl.d/99-fleet-tuning.conf
    mode: '0644'

- name: Apply sysctl parameters
  ansible.builtin.command: sysctl -p /etc/sysctl.d/99-fleet-tuning.conf
  changed_when: true
  failed_when: false

- name: Generate MOTD from template
  ansible.builtin.template:
    src: motd.j2
    dest: /etc/motd
    mode: '0644'
EOF

cat > /app/project/roles/capacity_audit/templates/sysctl.conf.j2 << 'EOF'
{% for key, value in policies.required_sysctl.items() %}
{{ key }} = {{ value }}
{% endfor %}
EOF

cat > /app/project/roles/capacity_audit/templates/motd.j2 << 'EOF'
========================================
  Host: {{ ansible_hostname }}
  Fleet Compliance System
  API Token: {{ api_token | mask_credential }}
  Managed by Ansible Automation
========================================
EOF

# =============================================================================
# 7. Create compliance_check role
# =============================================================================
cat > /app/project/roles/compliance_check/tasks/main.yml << 'EOF'
---
- name: Create application config directory
  ansible.builtin.file:
    path: /etc/app
    state: directory
    mode: '0755'

- name: Deploy fleet configuration with vault secrets
  ansible.builtin.template:
    src: fleet_config.yml.j2
    dest: /etc/app/fleet_config.yml
    mode: '0600'

- name: Create web directory
  ansible.builtin.file:
    path: /var/www/fleet
    state: directory
    mode: '0755'

- name: Create index.html
  ansible.builtin.copy:
    dest: /var/www/fleet/index.html
    content: |
      <!DOCTYPE html>
      <html>
      <head><title>Fleet Dashboard</title></head>
      <body><h1>Fleet Compliance Dashboard - {{ ansible_hostname }}</h1></body>
      </html>
    mode: '0644'

- name: Configure nginx with TLS fallback
  block:
    - name: Deploy HTTPS configuration
      ansible.builtin.template:
        src: nginx_ssl.conf.j2
        dest: /etc/nginx/sites-available/fleet
        mode: '0644'

    - name: Enable HTTPS site
      ansible.builtin.file:
        src: /etc/nginx/sites-available/fleet
        dest: /etc/nginx/sites-enabled/fleet
        state: link

    - name: Remove default nginx site
      ansible.builtin.file:
        path: /etc/nginx/sites-enabled/default
        state: absent

    - name: Validate nginx HTTPS configuration
      ansible.builtin.command: nginx -t
      changed_when: false

  rescue:
    - name: Deploy HTTP-only fallback configuration
      ansible.builtin.template:
        src: nginx_http.conf.j2
        dest: /etc/nginx/sites-available/fleet
        mode: '0644'

    - name: Ensure HTTP site symlink
      ansible.builtin.file:
        src: /etc/nginx/sites-available/fleet
        dest: /etc/nginx/sites-enabled/fleet
        state: link
        force: true

    - name: Remove default nginx site (rescue)
      ansible.builtin.file:
        path: /etc/nginx/sites-enabled/default
        state: absent

    - name: Validate HTTP fallback configuration
      ansible.builtin.command: nginx -t
      changed_when: false

  always:
    - name: Ensure nginx is running
      ansible.builtin.shell: nginx -s reload 2>/dev/null || nginx
      failed_when: false
EOF

cat > /app/project/roles/compliance_check/templates/fleet_config.yml.j2 << 'EOF'
---
database:
  master_password: "{{ db_master_password }}"

api:
  token: "{{ api_token }}"

tls:
  passphrase: "{{ tls_passphrase }}"

backup:
  key: "{{ backup_key }}"

deployment:
  token: "{{ deploy_token }}"
EOF

cat > /app/project/roles/compliance_check/templates/nginx_ssl.conf.j2 << 'EOF'
server {
    listen 443 ssl;
    server_name {{ ansible_hostname }};

    ssl_certificate /etc/ssl/fleet/cert.pem;
    ssl_certificate_key /etc/ssl/fleet/key.pem;

    root /var/www/fleet;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

cat > /app/project/roles/compliance_check/templates/nginx_http.conf.j2 << 'EOF'
server {
    listen 8080;
    server_name {{ ansible_hostname }};

    root /var/www/fleet;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF

# =============================================================================
# 8. Create site.yml with validation play
# =============================================================================
cat > /app/project/site.yml << 'EOF'
---
- name: Fleet capacity audit
  hosts: localhost
  connection: local
  become: yes
  gather_facts: yes
  vars_files:
    - secrets.yml
  roles:
    - capacity_audit

- name: Fleet compliance check
  hosts: localhost
  connection: local
  become: yes
  gather_facts: yes
  vars_files:
    - secrets.yml
  roles:
    - compliance_check

- name: Fleet compliance validation
  hosts: localhost
  connection: local
  become: no
  gather_facts: no
  vars_files:
    - secrets.yml
  tasks:
    - name: Load compliance policies
      ansible.builtin.include_vars:
        file: /app/compliance_policies.yml
        name: policies

    - name: Validate fleet hosts
      fleet_validate:
        fleet_file: /app/fleet_inventory.json
        hostname: "{{ item }}"
        risk_threshold: "{{ policies.thresholds.max_risk_score }}"
        capacity_threshold: "{{ policies.thresholds.capacity_critical }}"
        capacity_weights:
          cpu: 40
          memory: 35
          disk: 25
      register: validation_results
      ignore_errors: true
      loop:
        - localhost
        - db-primary
        - cache-node
        - app-worker-01
        - monitor-srv

    - name: Aggregate validation results
      ansible.builtin.set_fact:
        validation_map: "{{ validation_map | default({}) | combine({ item.item: { 'compliant': item.compliant | default(false), 'capacity_utilization': item.capacity_utilization | default(0), 'violations': item.violations | default([]) } }) }}"
      loop: "{{ validation_results.results }}"
      loop_control:
        label: "{{ item.item }}"

    - name: Write validation results
      ansible.builtin.copy:
        dest: /app/project/validation_results.json
        content: "{{ validation_map | to_nice_json }}"
        mode: '0644'
EOF

# =============================================================================
# 9. Create report template and audit_report.yml playbook
# =============================================================================
cat > /app/project/templates/compliance_report.j2 << 'EOF'
Fleet Compliance Report
=======================

{% for host in fleet_data.hosts %}
{% if host.status != 'decommissioned' %}
{% set cpu_pct = host.resources.allocated_cpu / host.resources.cpu_cores %}
{% set mem_pct = host.resources.allocated_memory_bytes / host.resources.memory_bytes %}
{% set disk_pct = host.resources.allocated_disk_bytes / host.resources.disk_bytes %}
{% set capacity = cpu_pct * 40 + mem_pct * 35 + disk_pct * 25 %}
Host: {{ host.hostname }}
  Datacenter: {{ host.datacenter }}
  Role: {{ host.role }}
  Capacity Utilization: {{ "%.2f" | format(capacity) }}%
  Capacity Status: {{ capacity | capacity_status }}
  Risk Score: {{ host.risk_score }}
  Risk Grade: {{ host.risk_score | risk_grade }}
  Network: {{ host.network.cidr }}
  Usable Hosts: {{ host.network.cidr | cidr_host_count }}

{% endif %}
{% endfor %}
Vault Secrets (masked):
  db_master_password: {{ db_master_password | mask_credential }}
  api_token: {{ api_token | mask_credential }}
  tls_passphrase: {{ tls_passphrase | mask_credential }}
  backup_key: {{ backup_key | mask_credential }}
  deploy_token: {{ deploy_token | mask_credential }}
EOF

cat > /app/project/audit_report.yml << 'EOF'
---
- name: Generate fleet compliance report
  hosts: localhost
  connection: local
  become: yes
  gather_facts: no
  vars_files:
    - secrets.yml
  tasks:
    - name: Read fleet inventory data
      ansible.builtin.slurp:
        src: /app/fleet_inventory.json
      register: fleet_raw

    - name: Parse fleet data
      ansible.builtin.set_fact:
        fleet_data: "{{ fleet_raw.content | b64decode | from_json }}"

    - name: Generate compliance report
      ansible.builtin.template:
        src: templates/compliance_report.j2
        dest: /app/project/compliance_report.txt
        mode: '0644'
EOF

# =============================================================================
# 10. Run playbooks
# =============================================================================
cd /app/project
export ANSIBLE_CONFIG=/app/project/ansible.cfg

# Disable set -e for playbook execution to avoid exit on rescued/ignored errors
set +e
ansible-playbook site.yml --vault-password-file vault_pass.txt -v
SITE_RC=$?
ansible-playbook audit_report.yml --vault-password-file vault_pass.txt -v
REPORT_RC=$?

if [ $SITE_RC -ne 0 ]; then
    echo "Warning: site.yml exited with code $SITE_RC"
fi
if [ $REPORT_RC -ne 0 ]; then
    echo "Warning: audit_report.yml exited with code $REPORT_RC"
fi

# Exit 0 — tests verify the actual state
exit 0
