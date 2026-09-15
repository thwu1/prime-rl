#!/bin/bash

# Copy analysis script to /app/
cp /solution/analyze.py /app/analyze.py

# Create the audit.sh pipeline at /app/
cat > /app/audit.sh << 'AUDIT_SCRIPT'
#!/bin/bash
set -e

# Use C preprocessor to resolve all macro definitions
gcc -dM -E -I/app/include /app/pips_prefetcher.cc 2>/dev/null > /tmp/pips_macros.txt

# Run the storage audit and design-space analysis
python3 /app/analyze.py

echo "Audit complete. Results written to /app/results.json"
AUDIT_SCRIPT

chmod +x /app/audit.sh

# Execute the pipeline
/app/audit.sh
