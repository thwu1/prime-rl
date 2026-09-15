#!/bin/bash

# Run the Python script that fixes all configurations
python3 /solution/fix_all.py

echo "All infrastructure configurations repaired."

# Validate
echo ""
echo "=== Validating ==="
echo "--- named-checkconf ---"
named-checkconf /app/dns/named.conf && echo "PASS" || echo "FAIL"

echo "--- named-checkzone (internal forward) ---"
named-checkzone infra.example.com /app/dns/zones/db.infra.example.com.internal && echo "PASS" || echo "FAIL"

echo "--- named-checkzone (external forward) ---"
named-checkzone infra.example.com /app/dns/zones/db.infra.example.com.external && echo "PASS" || echo "FAIL"

echo "--- named-checkzone (reverse) ---"
named-checkzone 30.20.10.in-addr.arpa /app/dns/zones/db.10.20.30 && echo "PASS" || echo "FAIL"

echo "--- haproxy -c ---"
haproxy -c -f /app/haproxy/haproxy.cfg && echo "PASS" || echo "FAIL"

echo "--- ansible --syntax-check ---"
ansible-playbook --syntax-check -i /app/ansible/inventory.ini /app/ansible/playbook.yml && echo "PASS" || echo "FAIL"
