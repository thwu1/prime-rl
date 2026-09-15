#!/bin/bash

pip3 install pyyaml==6.0.2 -q
cp /solution/audit.py /app/audit.py
python3 /app/audit.py > /dev/null 2>&1
