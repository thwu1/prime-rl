#!/usr/bin/env python3
"""
fix_cleanup.py — Rewrite /app/scripts/cleanup.sh with proper safety.

Fixes:
  - Add set -euo pipefail
  - Check config file exists before reading
  - Validate INSTALL_PATH is non-empty before rm
  - Quote all variable expansions in rm commands

"""

SCRIPT = "/app/scripts/cleanup.sh"

fixed = '''\
#!/bin/bash
# cleanup.sh — Remove supervisor installation
#
# Reads install path from /app/etc/supervisor.conf and removes
# all installed files and directories.

set -euo pipefail

CONF_FILE="/app/etc/supervisor.conf"

if [ ! -f "$CONF_FILE" ]; then
    echo "Error: config file not found: $CONF_FILE" >&2
    exit 1
fi

INSTALL_PATH=$(grep "install_dir" "$CONF_FILE" | cut -d'=' -f2)

if [ -z "$INSTALL_PATH" ]; then
    echo "Error: install_dir not found or empty in config" >&2
    exit 1
fi

if [ ! -d "$INSTALL_PATH" ]; then
    echo "Error: install directory does not exist: $INSTALL_PATH" >&2
    exit 1
fi

echo "Removing installation at: $INSTALL_PATH"

rm -rf "${INSTALL_PATH}/bin/"
rm -rf "${INSTALL_PATH}/etc/"
rm -rf "${INSTALL_PATH}/logs/"
rm -f "${INSTALL_PATH}/run/supervisor.pid"
rmdir "$INSTALL_PATH" 2>/dev/null || true

echo "Cleanup complete."
'''

with open(SCRIPT, "w") as f:
    f.write(fixed)

print(f"Wrote fixed cleanup script to {SCRIPT}")
