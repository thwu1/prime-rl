#!/bin/bash

# Copy mutation-killing tests into the app
cp /solution/test_mutation_killers.py /app/tests/test_mutation_killers.py

# Annotate equivalent mutations with pragma
python3 /solution/annotate_pragmas.py

# Commit changes so mutmut sees current state
cd /app
git add -A && git commit -m "add mutation-killing tests and pragma annotations"

# Verify all tests pass on original code
python3 -m pytest tests/ -q

# Generate coverage report using the coverage tool
coverage run --source=intervallib -m pytest tests/ -q
coverage json -o /app/coverage.json

# Run mutmut for mutation testing validation
rm -rf mutants/
timeout 300 mutmut run || true

# Generate mutation analysis report by computationally testing each mutation
python3 /solution/generate_report.py
