#!/bin/bash

set -e

pip3 install numpy==2.1.3 scipy==1.14.1 -q 2>/dev/null

mkdir -p /app/typesim

# Write __init__.py
python3 /solution/write_init.py

# Write parser.py
python3 /solution/write_parser.py

# Write similarity.py
python3 /solution/write_similarity.py

# Write cli.py
python3 /solution/write_cli.py

echo "TypeSim scoring engine installed at /app/typesim/"
