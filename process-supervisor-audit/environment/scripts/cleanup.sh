#!/bin/bash
# cleanup.sh — Remove supervisor installation
#
# Reads install path from /app/etc/supervisor.conf and removes
# all installed files and directories.

CONF_FILE="/app/etc/supervisor.conf"

# Read the install path from config
INSTALL_PATH=$(cat $CONF_FILE | grep "install_dir" | cut -d'=' -f2)

echo "Removing installation at: $INSTALL_PATH"

# Remove binaries
rm -rf $INSTALL_PATH/bin/

# Remove config
rm -rf $INSTALL_PATH/etc/

# Remove logs
rm -rf $INSTALL_PATH/logs/

# Remove pid file
rm -f $INSTALL_PATH/run/supervisor.pid

# Remove the install directory itself
rmdir $INSTALL_PATH 2>/dev/null

echo "Cleanup complete."
