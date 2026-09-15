#!/usr/bin/env python3
"""
Fix all architectural flaws and bugs in the Ansible project at /app/.

Issues:
1. ansible.cfg: roles_path typo (/app/role -> /app/roles), missing vault_password_file
2. inventory: children group name typo (locals -> local)
3. Vault: encrypted with "batterystaple" but vault_pass.txt has "correcthorse" - must rekey
4. Custom filter plugin: templates reference upstream_servers and health_endpoints
   filters that don't exist - must create filter_plugins/service_filters.py
5. Variable precedence: roles/webapp/vars/main.yml has app_port=8080 that accidentally
   overrides group_vars app_port=3000 (role vars precedence > group_vars), but
   max_connections=500 and ssl_redirect=true are INTENTIONAL security overrides
   that must be preserved
6. nginx template: references undefined {{ server_name }} instead of {{ app_server_name }}
7. JSON template: trailing comma in services for-loop (missing loop.last check)
8. Handler: task notifies "restart nginx" but handler is "Restart Nginx" (case-sensitive)
9. report.yml: missing vars_files for vault secrets (admin_email undefined)
"""

import os
import subprocess
import sys


def fix_ansible_cfg():
    """Fix roles_path typo and add vault_password_file."""
    path = "/app/ansible.cfg"
    with open(path) as f:
        content = f.read()

    content = content.replace("roles_path = /app/role", "roles_path = /app/roles")
    content = content.replace(
        "[defaults]\n",
        "[defaults]\nvault_password_file = /app/vault_pass.txt\n",
        1,
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed ansible.cfg: roles_path and vault_password_file")


def fix_inventory():
    """Fix webservers:children group name typo."""
    path = "/app/inventory"
    with open(path) as f:
        content = f.read()

    content = content.replace("\nlocals\n", "\nlocal\n")

    with open(path, "w") as f:
        f.write(content)
    print("Fixed inventory: locals -> local")


def fix_vault():
    """Rekey vault from 'batterystaple' to 'correcthorse'."""
    old_pass_file = "/tmp/_old_vault_pass.txt"
    with open(old_pass_file, "w") as f:
        f.write("batterystaple")

    result = subprocess.run(
        [
            "ansible-vault", "rekey",
            "--vault-password-file", old_pass_file,
            "--new-vault-password-file", "/app/vault_pass.txt",
            "/app/secrets.yml",
        ],
        capture_output=True,
        text=True,
    )
    os.remove(old_pass_file)

    if result.returncode != 0:
        print(f"ERROR rekeying vault: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Fixed vault: rekeyed to match vault_pass.txt")


def create_filter_plugin():
    """Create custom filter plugin with upstream_servers and health_endpoints filters.

    upstream_servers: takes services list, returns list of 'IP:PORT weight=N' strings
    for enabled services only.

    health_endpoints: takes services list, returns dict mapping enabled service names
    to their health check URLs.
    """
    os.makedirs("/app/filter_plugins", exist_ok=True)
    path = "/app/filter_plugins/service_filters.py"
    content = '''\
def upstream_servers(services):
    """Return list of weighted upstream entries for enabled services."""
    return [
        "127.0.0.1:{} weight={}".format(svc["port"], svc.get("weight", 1))
        for svc in services
        if svc.get("enabled", False)
    ]


def health_endpoints(services):
    """Return dict mapping enabled service names to health check URLs."""
    return {
        svc["name"]: "http://127.0.0.1:{}/health".format(svc["port"])
        for svc in services
        if svc.get("enabled", False)
    }


class FilterModule(object):
    def filters(self):
        return {
            "upstream_servers": upstream_servers,
            "health_endpoints": health_endpoints,
        }
'''
    with open(path, "w") as f:
        f.write(content)
    print("Created filter plugin: upstream_servers and health_endpoints")


def fix_variable_precedence():
    """Evaluate and selectively fix role vars.

    In Ansible's variable precedence hierarchy, role vars (level 16) override
    group_vars (level 4). The vars/main.yml has:
    - app_port: 8080 -> ACCIDENTAL override, must remove (group_vars has 3000)
    - max_connections: 500 -> INTENTIONAL security hardening, must keep
    - ssl_redirect: true -> INTENTIONAL security hardening, must keep
    """
    path = "/app/roles/webapp/vars/main.yml"
    content = """\
---
# Security hardening overrides for webapp role.
# DO NOT MOVE these to defaults — they are intentional production values
# that must take precedence over baseline defaults.
max_connections: 500
ssl_redirect: true
"""
    with open(path, "w") as f:
        f.write(content)
    print("Fixed variable precedence: removed accidental app_port override, "
          "preserved intentional max_connections and ssl_redirect")


def fix_nginx_template():
    """Fix undefined server_name variable reference."""
    path = "/app/roles/webapp/templates/nginx.conf.j2"
    with open(path) as f:
        content = f.read()

    content = content.replace("{{ server_name }}", "{{ app_server_name }}")

    with open(path, "w") as f:
        f.write(content)
    print("Fixed nginx template: server_name -> app_server_name")


def fix_json_template():
    """Fix trailing comma in JSON services for-loop."""
    path = "/app/roles/webapp/templates/app_config.json.j2"
    with open(path) as f:
        content = f.read()

    content = content.replace(
        '    },\n{% endfor %}',
        '    }{% if not loop.last %},{% endif %}\n{% endfor %}',
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed JSON template: added loop.last check for trailing comma")


def fix_handler_name():
    """Fix handler notify case to match handler definition."""
    path = "/app/roles/webapp/tasks/main.yml"
    with open(path) as f:
        content = f.read()

    content = content.replace("notify: restart nginx", "notify: Restart Nginx")

    with open(path, "w") as f:
        f.write(content)
    print("Fixed handler notify: 'restart nginx' -> 'Restart Nginx'")


def fix_report_playbook():
    """Add vars_files to report.yml for vault secret access."""
    path = "/app/playbooks/report.yml"
    with open(path) as f:
        content = f.read()

    content = content.replace(
        "  hosts: local\n  tasks:",
        "  hosts: local\n  vars_files:\n    - /app/secrets.yml\n  tasks:",
    )

    with open(path, "w") as f:
        f.write(content)
    print("Fixed report.yml: added vars_files for vault secrets")


if __name__ == "__main__":
    fix_ansible_cfg()
    fix_inventory()
    fix_vault()
    create_filter_plugin()
    fix_variable_precedence()
    fix_nginx_template()
    fix_json_template()
    fix_handler_name()
    fix_report_playbook()
    print("\nAll issues fixed successfully.")
