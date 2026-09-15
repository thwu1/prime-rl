#!/bin/bash

set -e

cd /app

echo "=== Step 1: Fix config.toml ==="
cp /solution/fixed_config.toml /app/config.toml

echo "=== Step 2: Fix runner.py ==="
cp /solution/fixed_runner.py /app/runner.py

echo "=== Step 3: Fix report.py ==="
cp /solution/fixed_report.py /app/report.py

echo "=== Step 4: Fix buggy C test files ==="
cp /solution/fixed_irr_flow_test_02.c /app/tests/irr_flow/test_02.c
cp /solution/fixed_alias_test_02.c /app/tests/alias/test_02.c

echo "=== Step 5: Generate additional test programs ==="
python3 /solution/solve_helper.py

echo "=== Step 6: Run the pipeline ==="
python3 /app/runner.py
python3 /app/report.py

echo "=== Step 7: Verify results ==="
python3 -c "
import json
with open('/app/results.json') as f:
    data = json.load(f)
print('Compilers tested:', data['compilers_tested'])
print('Total tests:', data['total_tests'])
for cat, info in data['categories'].items():
    print(f'  {cat}: {info[\"count\"]} tests')
print(f'Discrepancies: {len(data[\"discrepancies\"])}')
"

echo "=== Done ==="
