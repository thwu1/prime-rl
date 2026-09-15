#!/bin/bash

# Install dependencies
pip3 install lit==18.1.8 -q

# 1. Deploy fixed FileCheck implementation
cp /solution/fixed_filecheck.py /app/filecheck.py
chmod +x /app/filecheck.py

# 2. Fix the wrong_pattern.check (pattern issue, not tool bug)
cp /solution/wrong_pattern_fixed.check /app/test_inputs/wrong_pattern.check

# 3. Generate audit report
python3 /solution/gen_audit.py

# 4. Set up lit test suite
python3 /solution/gen_lit_suite.py

# 5. Generate spec evaluation and probe tests
python3 /solution/gen_spec_evaluation.py

# 6. Generate edge case tests
python3 /solution/gen_edge_cases.py

# 7. Verify lit suite passes
echo ""
echo "=== Running lit test suite ==="
lit /app/lit_suite -v --no-progress-bar
LIT_RC=$?

# 8. Verify spec probes pass
echo ""
echo "=== Verifying spec probes ==="
PROBE_RC=0
for check_file in /app/spec_probes/*.check; do
    base=$(basename "$check_file" .check)
    input_file="/app/spec_probes/${base}.input"
    python3 /app/filecheck.py "$check_file" --input-file "$input_file" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "PASS: spec_probe/$base"
    else
        echo "FAIL: spec_probe/$base"
        PROBE_RC=1
    fi
done

# 9. Verify edge cases pass
echo ""
echo "=== Verifying edge cases ==="
for check_file in /app/edge_cases/*.check; do
    base=$(basename "$check_file" .check)
    input_file="/app/edge_cases/${base}.input"
    python3 /app/filecheck.py "$check_file" --input-file "$input_file" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "PASS: edge_case/$base"
    else
        echo "FAIL: edge_case/$base"
        PROBE_RC=1
    fi
done

if [ $LIT_RC -eq 0 ] && [ $PROBE_RC -eq 0 ]; then
    echo ""
    echo "All checks passed."
else
    echo ""
    echo "Some checks failed."
    exit 1
fi
