#!/bin/bash

set -e

pip3 install PyYAML==6.0.2 -q 2>/dev/null || true

cp /solution/scorer.py /app/audit.py
cd /app && python3 audit.py
