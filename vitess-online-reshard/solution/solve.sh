#!/bin/bash


# Ensure /tmp is writable (container runtime may restrict)
chmod 1777 /tmp 2>/dev/null || true
mkdir -p /var/lib/mysql/tmp
chown mysql:mysql /var/lib/mysql/tmp 2>/dev/null || true

# Install solution dependencies
pip3 install pymysql==1.1.1 pyyaml==6.0.2 -q

# Start MySQL reliably
/usr/local/bin/ensure-mysql.sh
if [ $? -ne 0 ]; then
    echo "FATAL: Could not start MySQL"
    exit 1
fi

# Run the resharding solution
python3 /solution/reshard.py
