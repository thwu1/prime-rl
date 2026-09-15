#!/usr/bin/env bash

set -e

# Copy solution files to /app
cp /solution/ecl_evaluator.py /app/
cp /solution/verhoeff_validate.py /app/
cp /solution/load_rf2.sh /app/load-rf2
cp /solution/ecl_to_valueset.sh /app/ecl-to-valueset
chmod +x /app/load-rf2 /app/ecl-to-valueset

# Create ecl-eval wrapper
cat > /app/ecl-eval << 'WRAPPER'
#!/usr/bin/env python3
import sys, os
sys.path.insert(0, "/app")
os.chdir("/app")
from ecl_evaluator import main
main()
WRAPPER
chmod +x /app/ecl-eval

# Build the database from RF2 files
/app/load-rf2
