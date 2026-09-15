#!/bin/bash

cd /app

# Phase 1: Forensic analysis
python3 /solution/analyze.py

# Phase 2: YARA rule generation and validation
python3 /solution/generate_rules.py

# Phase 3: Threat intelligence assessment
python3 /solution/generate_assessment.py

# Phase 4: Validate YARA rules
echo "=== Validating YARA rules ==="
echo "--- Scanning suspects ---"
yara -r /app/detection_rules.yar /app/suspects/
echo "--- Scanning baselines (expect no output) ---"
yara -r /app/detection_rules.yar /app/baselines/
echo "=== Validation complete ==="
