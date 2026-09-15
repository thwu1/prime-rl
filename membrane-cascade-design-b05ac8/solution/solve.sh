#!/usr/bin/env bash

set -e

pip3 install numpy==2.1.3 -q

mkdir -p /app/membrane_analysis

cp /solution/eos.py /app/membrane_analysis/eos.py
cp /solution/robeson.py /app/membrane_analysis/robeson.py
cp /solution/cascade.py /app/membrane_analysis/cascade.py
cp /solution/validate.py /app/membrane_analysis/validate.py
cp /solution/cli.py /app/membrane_analysis/__main__.py
cp /solution/Makefile /app/Makefile

cat > /app/membrane_analysis/__init__.py << 'PYEOF'
"""Membrane gas separation analysis package."""
PYEOF
