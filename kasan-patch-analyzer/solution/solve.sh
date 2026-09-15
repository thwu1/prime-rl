#!/bin/bash

set -e

# Create the kasan_analyzer package
mkdir -p /app/kasan_analyzer

# Create __init__.py
python3 -c "
with open('/app/kasan_analyzer/__init__.py', 'w') as f:
    f.write('\"\"\"KASAN Crash Report Analyzer - inspired by RGym kernel APR methodology.\"\"\"\\n')
"

# Create the implementation modules
cp /solution/parser.py /app/kasan_analyzer/parser.py
cp /solution/localizer.py /app/kasan_analyzer/localizer.py
cp /solution/verifier.py /app/kasan_analyzer/verifier.py
cp /solution/patch_analyzer.py /app/kasan_analyzer/patch_analyzer.py

echo "kasan_analyzer package installed at /app/kasan_analyzer/"
