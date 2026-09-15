#!/bin/bash

set -e
cd /app/ansible-project

# Run the Python helper to fix and build everything
python3 /solution/fix_project.py

# Verify ansible setup
echo "=== Verifying inventory structure ==="
ansible-inventory --graph

echo "=== Verifying vault contents ==="
ansible-vault view vars/vault.yml

# Run playbooks
echo "=== Running site.yml ==="
ansible-playbook site.yml -v

echo "=== Running report.yml ==="
ansible-playbook report.yml -v

echo "=== Solution complete ==="
