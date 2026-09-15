#!/usr/bin/env bash

set -e

pip3 install cryptography==44.0.0 -q

# Deploy fixed Python implementation
cp /solution/ctr_drbg_fixed.py /app/impl_alpha/ctr_drbg.py

# Deploy ctypes harness for C library
cp /solution/harness_beta.py /app/harness_beta.py

# Deploy and run cross-validation script
cp /solution/cross_validate.sh /app/cross_validate.sh
chmod +x /app/cross_validate.sh
bash /app/cross_validate.sh

# Run ctypes harness against C library
cd /app
python3 /app/harness_beta.py

# Build audit report
cp /solution/build_report.py /app/build_report.py
python3 /app/build_report.py

echo "Solution complete."
python3 -c "
import json
r = json.load(open('/app/audit_report.json'))
for impl in r['implementations']:
    print(f\"{impl['name']}: {impl['passed']}/{impl['total_vectors']} passed, verdict={impl['compliance_verdict']}\")
cv = r['cross_validation']
print(f\"Cross-validation: {cv['checks_passed']}/{cv['intermediate_checks']} checks passed\")
"
