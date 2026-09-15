#!/bin/bash

set -e

# Verify config file exists and is valid
python3 -c "import json; d=json.load(open('/app/config/problems.json')); assert 'blast' in d['problems'], f'Bad config: {list(d.keys())}'"

cd /app
python3 /solution/solver.py
