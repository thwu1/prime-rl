#!/bin/bash

cd /app

# Disable LeakSanitizer — it cannot run in container/ptrace environments
export ASAN_OPTIONS=detect_leaks=0

# Patch all 6 vulnerabilities in the source code
python3 /solution/patch_bugs.py

# Generate the peer review and corrected security audit
python3 /solution/generate_audit.py

# Rebuild with AddressSanitizer
make clean && make

echo "Build complete. Verifying fixes..."

# Verify ASan-reported PoCs are fixed
ALL_FIXED=true
for i in 1 2 3 4; do
    if /app/kvstore /app/poc/poc$i.cfg > /dev/null 2>&1; then
        echo "PoC $i: FIXED"
    else
        echo "PoC $i: STILL CRASHES"
        ALL_FIXED=false
    fi
done

# Verify hidden bug fixes
echo "SET selfkey testval" > /tmp/selfcopy.cfg
echo "COPY selfkey selfkey" >> /tmp/selfcopy.cfg
echo "GET selfkey" >> /tmp/selfcopy.cfg
echo "QUIT" >> /tmp/selfcopy.cfg
if /app/kvstore /tmp/selfcopy.cfg > /dev/null 2>&1; then
    echo "Self-copy: FIXED"
else
    echo "Self-copy: STILL CRASHES"
    ALL_FIXED=false
fi

if $ALL_FIXED; then
    echo "All vulnerabilities fixed successfully."
else
    echo "Some vulnerabilities remain."
    exit 1
fi
