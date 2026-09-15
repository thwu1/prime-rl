#!/bin/bash

# Deploy and run the reference audit tool
cp /solution/audit_tool.py /app/audit.py
cd /app
python3 audit.py
