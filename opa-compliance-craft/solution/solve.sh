#!/bin/bash

cd /app
python3 /solution/solve_helper.py

echo "Verifying solution with OPA..."
opa eval "data.aad.tests" -i /app/tenant_input.json -d /app/rego/ --format json | python3 -c "
import json, sys
data = json.load(sys.stdin)
tests = data['result'][0]['expressions'][0]['value']
results = {t['PolicyId']: t['RequirementMet'] for t in tests}
with open('/app/target_outcomes.json') as f:
    targets = json.load(f)
failures = []
for pid, expected in targets.items():
    actual = results.get(pid)
    if actual != expected:
        failures.append(f'{pid}: expected={expected}, got={actual}')
if failures:
    print('VERIFICATION FAILED:')
    for f in failures:
        print(f'  {f}')
    sys.exit(1)
else:
    print(f'All {len(targets)} target outcomes verified successfully.')
"
