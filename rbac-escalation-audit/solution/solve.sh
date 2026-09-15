#!/usr/bin/env bash

pip3 install PyYAML==6.0.2 -q

cp /solution/rbac_audit_fixed.py /app/rbac_audit.py
cd /app
python3 /app/rbac_audit.py
