#!/bin/bash
# solve.sh — Fix all bugs in the process supervisor and cleanup script
#

set -euo pipefail

# Fix C source bugs
python3 /solution/fix_supervisor.py

# Fix bash cleanup script safety issues
python3 /solution/fix_cleanup.py

# Write root cause analysis
python3 /solution/write_analysis.py

# Verify the fixed code compiles cleanly
gcc -Wall -Wextra -Werror -o /dev/null /app/src/supervisor.c

# Generate strace capture of the fixed supervisor
python3 /solution/capture_strace.py

echo "All fixes applied and verification complete."
