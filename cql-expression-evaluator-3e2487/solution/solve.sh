#!/bin/bash

set -e

# Install Python ANTLR4 runtime
pip3 install antlr4-python3-runtime==4.13.2 -q

# Download ANTLR4 tool JAR
ANTLR_JAR=/tmp/antlr-4.13.2-complete.jar
if [ ! -f "$ANTLR_JAR" ]; then
    curl -sL -o "$ANTLR_JAR" https://www.antlr.org/download/antlr-4.13.2-complete.jar
fi

# Copy the adapted grammar to /app
cp /solution/CqlExpr.g4 /app/CqlExpr.g4

# Generate Python3 parser/lexer from the grammar
mkdir -p /app/generated
java -jar "$ANTLR_JAR" -Dlanguage=Python3 -visitor -o /app/generated /app/CqlExpr.g4

# Install the runner
cp /solution/cql_runner.py /app/cql_runner.py

# Verify
echo "=== Generated parser files ==="
ls /app/generated/*Parser.py /app/generated/*Lexer.py 2>/dev/null

echo "=== Quick smoke test ==="
python3 /app/cql_runner.py /app/fixtures/CqlLogicalOperatorsTest.xml | python3 -c "
import sys, json
d = json.load(sys.stdin)
s = d['summary']
print(f\"Logical: {s['passed']}/{s['total']} passed\")
"

echo "=== Batch summary ==="
python3 /app/cql_runner.py --batch | python3 -c "
import sys, json
data = json.load(sys.stdin)
total = sum(d['summary']['total'] for d in data)
passed = sum(d['summary']['passed'] for d in data)
print(f'Overall: {passed}/{total} ({100*passed/total:.1f}%)')
for d in data:
    s = d['summary']
    print(f\"  {d['file']}: {s['passed']}/{s['total']}\")
"
