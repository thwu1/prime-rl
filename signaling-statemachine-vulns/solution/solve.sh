#!/bin/bash

set -e

pip3 install hypothesis==6.108.5 -q

cd /app
mkdir -p /app/analysis

# Run the analysis script that dynamically discovers vulnerabilities,
# tests patches, and generates all required outputs
python3 /solution/analyze_and_solve.py

# Render state graph to PNG
dot -Tpng /app/analysis/state_graph.dot -o /app/analysis/state_graph.png

# Verify fuzzer detects violations in original code
echo "Verifying fuzzer detects violations..."
python3 -c "
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/analysis')
from hypothesis import settings, HealthCheck
from hypothesis.stateful import RuleBasedStateMachine
import importlib.util

spec = importlib.util.spec_from_file_location('fuzzer', '/app/analysis/invariant_fuzzer.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

cls = None
for name in dir(mod):
    obj = getattr(mod, name)
    if isinstance(obj, type) and issubclass(obj, RuleBasedStateMachine) and obj is not RuleBasedStateMachine:
        cls = obj
        break

tc = cls.TestCase
tc.settings = settings(max_examples=100, stateful_step_count=10, suppress_health_check=list(HealthCheck), database=None)
try:
    tc('runTest').runTest()
    print('ERROR: Fuzzer did not detect violation')
    sys.exit(1)
except Exception as e:
    print(f'Fuzzer correctly detected violation: {type(e).__name__}')
"

echo "All analysis outputs generated and verified."
