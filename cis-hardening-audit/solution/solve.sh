#!/bin/bash

set -euo pipefail

# Deploy the fixed hardening script and the audit script
cp /solution/harden_fixed.sh /app/harden.sh
cp /solution/audit_impl.sh /app/audit.sh
chmod +x /app/harden.sh /app/audit.sh

# Run the fixed hardening
/app/harden.sh

# Run the audit to verify all controls pass
/app/audit.sh

echo "Solution applied successfully."
