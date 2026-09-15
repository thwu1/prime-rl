#!/usr/bin/env bash

python3 -m pip install pytest==8.3.4 -q

# Verify data and tool are accessible
python3 -c "
import json, os, sys
for f in ['arith_proof.json', 'list_proof.json', 'bool_proof.json']:
    p = os.path.join('/app/data', f)
    if not os.path.exists(p):
        print(f'ERROR: {p} not found', file=sys.stderr)
        sys.exit(1)
    json.load(open(p))
if not os.path.exists('/app/proofquery.py'):
    print('ERROR: /app/proofquery.py not found', file=sys.stderr)
    sys.exit(1)
print('Pre-flight checks passed')
"
PREFLIGHT=$?
if [ $PREFLIGHT -ne 0 ]; then
    echo "Pre-flight checks failed"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

cd /app
python3 -m pytest /tests/test_state.py -v --tb=short
EXIT_CODE=$?

mkdir -p /logs/verifier
if [ $EXIT_CODE -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi
exit $EXIT_CODE
