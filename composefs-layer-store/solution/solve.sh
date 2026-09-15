#!/bin/bash

# Replace the buggy tool with the fixed version
cp /solution/cfs_tool_fixed.py /app/cfs_tool.py

# Install the store audit script
cp /solution/store_audit.sh /app/store-audit.sh
chmod +x /app/store-audit.sh
