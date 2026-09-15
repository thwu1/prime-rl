#!/bin/bash

cd /app/ansible-project

# Run playbooks to create system state (capture output for diagnostics)
echo "=== Running site.yml ==="
ansible-playbook site.yml -v 2>&1
SITE_RC=$?
echo "site.yml exit code: $SITE_RC"

echo "=== Running report.yml ==="
ansible-playbook report.yml -v 2>&1
REPORT_RC=$?
echo "report.yml exit code: $REPORT_RC"

# Install test dependencies and run verification
pip3 install pytest==8.3.4 -q

echo "=== Running verification tests ==="
pytest /tests/test_state.py -v
PYTEST_RC=$?

# Write reward
mkdir -p /logs/verifier
if [ $PYTEST_RC -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
