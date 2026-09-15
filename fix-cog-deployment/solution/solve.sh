#!/bin/bash

set -e

pip3 install pyyaml==6.0.2 -q

cd /app
python3 /solution/fix_project.py
