#!/usr/bin/env python3
"""Fix and complete the broken Ansible project at /app/ansible-project/."""


import configparser
import os
import re
import shutil
import subprocess

PROJECT_DIR = "/app/ansible-project"


def create_vault():
    """Create vault password file and encrypted vault with secrets.

    MUST run BEFORE fix_ansible_cfg() to avoid duplicate vault-id error.
    When ansible.cfg already has vault_password_file AND we pass
    --vault-password-file on the CLI, ansible-vault sees two sources
    with vault-id 'default' and refuses to encrypt.
    """
    vpf_path = f"{PROJECT_DIR}/vault_pass.txt"
    with open(vpf_path, "w") as f:
        f.write("RedHat294!\n")
    os.chmod(vpf_path, 0o600)

    vault_path = f"{PROJECT_DIR}/vars/vault.yml"
    os.makedirs(os.path.dirname(vault_path), exist_ok=True)
    with open(vault_path, "w") as f:
        f.write('---\nvault_db_password: "S3cur3P@ss2024!"\n')
        f.write('vault_api_key: "ak-7f3d9e2b1a4c8d5e"\n')
        f.write('vault_backup_passphrase: "bkp-X9mK2pL7"\n')

    subprocess.run(
        ["ansible-vault", "encrypt", vault_path, "--vault-password-file", vpf_path],
        check=True,
    )
    print("Created and encrypted vault")


def fix_ansible_cfg():
    """Fix broken ansible.cfg settings."""
    cfg_path = f"{PROJECT_DIR}/ansible.cfg"
    config = configparser.ConfigParser()
    config.read(cfg_path)

    config.set("defaults", "inventory", f"{PROJECT_DIR}/inventory/hosts")
    config.set("defaults", "host_key_checking", "False")
    config.set("defaults", "vault_password_file", f"{PROJECT_DIR}/vault_pass.txt")
    config.set("defaults", "retry_files_enabled", "False")
    # gathering was set to 'explicit' which prevents automatic fact collection.
    # Templates use ansible_hostname, ansible_fqdn, ansible_date_time etc. which
    # require facts. Setting to 'smart' enables fact caching with auto-collection.
    config.set("defaults", "gathering", "smart")
    # All hosts use ansible_connection=local — they share one filesystem.
    # Parallel task execution (default forks=5) causes race conditions
    # when multiple "hosts" concurrently create the same users/groups.
    config.set("defaults", "forks", "1")
    config.set("privilege_escalation", "become_method", "sudo")
    config.set("privilege_escalation", "become_ask_pass", "False")

    with open(cfg_path, "w") as f:
        config.write(f)
    print("Fixed ansible.cfg")


def fix_host_vars():
    """Remove conflicting host_vars that override group_vars.

    host_vars/app1.yml overrides env_name to 'staging', which takes precedence
    over group_vars/webservers.yml (env_name: 'production') due to Ansible's
    variable precedence hierarchy. This causes app1's config to render with
    'STAGING' instead of 'PRODUCTION'.
    """
    host_vars_path = f"{PROJECT_DIR}/host_vars/app1.yml"
    if os.path.exists(host_vars_path):
        os.remove(host_vars_path)
        print("Removed conflicting host_vars/app1.yml")
    # Clean up empty directory
    host_vars_dir = f"{PROJECT_DIR}/host_vars"
    if os.path.isdir(host_vars_dir) and not os.listdir(host_vars_dir):
        os.rmdir(host_vars_dir)
        print("Removed empty host_vars directory")


def fix_inventory():
    """Add missing production parent group to inventory."""
    inv_path = f"{PROJECT_DIR}/inventory/hosts"
    with open(inv_path, "a") as f:
        f.write("\n[production:children]\nwebservers\ndatabases\n")
    print("Fixed inventory: added [production:children]")


def fix_template():
    """Fix Jinja2 template syntax errors (missing closing braces)."""
    template_path = f"{PROJECT_DIR}/templates/app_config.conf.j2"
    with open(template_path, "r") as f:
        content = f.read()

    # Fix: {{ ansible_date_time.date } -> {{ ansible_date_time.date }}
    content = re.sub(
        r"(\{\{\s*ansible_date_time\.date\s*)\}(?!\})", r"\1}}", content
    )

    # Fix: {{ env_name | upper } -> {{ env_name | upper }}
    content = re.sub(
        r"(\{\{\s*env_name\s*\|\s*upper\s*)\}(?!\})", r"\1}}", content
    )

    with open(template_path, "w") as f:
        f.write(content)
    print("Fixed Jinja2 template syntax errors")


def create_role():
    """Create the site_deploy role with all required components."""
    role_base = f"{PROJECT_DIR}/roles/site_deploy"

    for d in ["tasks", "handlers", "templates", "defaults"]:
        os.makedirs(f"{role_base}/{d}", exist_ok=True)

    # Copy fixed template into role templates directory
    src_template = f"{PROJECT_DIR}/templates/app_config.conf.j2"
    dst_template = f"{role_base}/templates/app_config.conf.j2"
    shutil.copy2(src_template, dst_template)

    with open(f"{role_base}/tasks/main.yml", "w") as f:
        f.write("""---
- name: Create appadmin group
  ansible.builtin.group:
    name: appadmin
    gid: 5000
    state: present

- name: Create system users with error handling
  block:
    - name: Create deployer user
      ansible.builtin.user:
        name: deployer
        uid: 5001
        group: appadmin
        shell: /bin/bash
        create_home: yes
        state: present

    - name: Create svcaccount user
      ansible.builtin.user:
        name: svcaccount
        uid: 5002
        group: appadmin
        shell: /sbin/nologin
        create_home: no
        state: present
  rescue:
    - name: Report user creation failure
      ansible.builtin.debug:
        msg: "WARNING: User creation encountered an error, attempting recovery"

    - name: Recover deployer user
      ansible.builtin.user:
        name: deployer
        group: appadmin
        shell: /bin/bash
        create_home: yes
        state: present

    - name: Recover svcaccount user
      ansible.builtin.user:
        name: svcaccount
        group: appadmin
        shell: /sbin/nologin
        create_home: no
        state: present

- name: Ensure base webapp directory exists
  ansible.builtin.file:
    path: "{{ deploy_base }}"
    state: directory
    owner: deployer
    group: appadmin
    mode: '2775'

- name: Create subdirectories
  ansible.builtin.file:
    path: "{{ deploy_base }}/{{ item }}"
    state: directory
    owner: deployer
    group: appadmin
    mode: '0755'
  loop:
    - config
    - data
    - logs

- name: Deploy application configuration
  ansible.builtin.template:
    src: app_config.conf.j2
    dest: "{{ deploy_base }}/config/{{ inventory_hostname }}.conf"
    owner: deployer
    group: appadmin
    mode: '0640'
  notify: reload application config
""")

    # Write handlers/main.yml
    with open(f"{role_base}/handlers/main.yml", "w") as f:
        f.write("""---
- name: reload application config
  ansible.builtin.copy:
    content: "Config reloaded at {{ ansible_date_time.iso8601 }}\\n"
    dest: "{{ config_reload_marker }}"
    mode: '0644'
""")

    print("Created site_deploy role")


def create_playbooks():
    """Create site.yml and report.yml playbooks."""
    # serial: 1 ensures hosts run one at a time, complementing forks=1
    # to prevent any race conditions with local connections
    with open(f"{PROJECT_DIR}/site.yml", "w") as f:
        f.write("""---
- name: Deploy site configuration
  hosts: all
  serial: 1
  vars_files:
    - vars/vault.yml
  roles:
    - site_deploy
""")

    # Create report template
    with open(f"{PROJECT_DIR}/templates/system_report.j2", "w") as f:
        f.write("""=== System Report for {{ inventory_hostname }} ===
Generated: {{ ansible_date_time.iso8601 }}

[System Information]
Hostname: {{ ansible_hostname }}
FQDN: {{ ansible_fqdn }}
OS: {{ ansible_distribution }} {{ ansible_distribution_version }}
Kernel: {{ ansible_kernel }}
Architecture: {{ ansible_architecture }}

[Hardware]
CPU Count: {{ ansible_processor_vcpus | default('N/A') }}
Memory Total (MB): {{ ansible_memtotal_mb }}
Swap Total (MB): {{ ansible_swaptotal_mb }}

[Network]
Default IPv4: {{ ansible_default_ipv4.address | default('N/A') }}
Default Interface: {{ ansible_default_ipv4.interface | default('N/A') }}

=== End Report ===
""")

    with open(f"{PROJECT_DIR}/report.yml", "w") as f:
        f.write("""---
- name: Generate system reports
  hosts: all
  serial: 1
  tasks:
    - name: Generate system report
      ansible.builtin.template:
        src: templates/system_report.j2
        dest: "{{ deploy_base }}/system_report.txt"
        mode: '0644'
""")

    print("Created playbooks and report template")


def main():
    print("=" * 60)
    print("Fixing and completing Ansible project")
    print("=" * 60)

    # IMPORTANT: Vault must be created BEFORE ansible.cfg is modified.
    # If ansible.cfg already has vault_password_file set, passing
    # --vault-password-file on the CLI creates duplicate vault-ids
    # (both 'default'), causing ansible-vault encrypt to fail.
    print("\nStep 1: Creating vault (before ansible.cfg changes)...")
    create_vault()

    print("\nStep 2: Fixing ansible.cfg...")
    fix_ansible_cfg()

    print("\nStep 3: Removing conflicting host_vars...")
    fix_host_vars()

    print("\nStep 4: Fixing inventory...")
    fix_inventory()

    print("\nStep 5: Fixing Jinja2 template...")
    fix_template()

    print("\nStep 6: Creating site_deploy role...")
    create_role()

    print("\nStep 7: Creating playbooks...")
    create_playbooks()

    print("\n" + "=" * 60)
    print("All fixes and creations complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
