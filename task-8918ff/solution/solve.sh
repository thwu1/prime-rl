#!/usr/bin/env bash

set -euo pipefail

pip3 install cryptography==44.0.0 -q

# Step 1 — Diagnose bugs by running Wycheproof vectors against buggy service
python3 /solution/diagnose.py

# Step 2 — Apply fixes to crypto_service.py
python3 /solution/apply_fixes.py

# Step 3 — Write the audit report
python3 /solution/write_report.py

echo "[solve] All fixes applied and audit report written."
