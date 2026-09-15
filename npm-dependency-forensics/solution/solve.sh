#!/bin/bash

set -e

cd /app
mkdir -p /app/exploits /app/mitigations

# Generate vulnerability report
python3 /solution/create_report.py

# Deploy exploit scripts
cp /solution/exploit_pp.js   /app/exploits/prototype_pollution.js
cp /solution/exploit_pt.js   /app/exploits/path_traversal.js
cp /solution/create_tar.py   /app/exploits/create_tar.py
cp /solution/exploit_redos.js /app/exploits/redos.js
cp /solution/exploit_ci.js   /app/exploits/code_injection.js

# Deploy mitigation scripts
cp /solution/mit_pp.js    /app/mitigations/prototype_pollution_safe.js
cp /solution/mit_pt.js    /app/mitigations/path_traversal_safe.js
cp /solution/mit_redos.js /app/mitigations/redos_safe.js
cp /solution/mit_ci.js    /app/mitigations/code_injection_safe.js

echo "Solution deployed."
