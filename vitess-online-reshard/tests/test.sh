#!/bin/bash


# Ensure /tmp is writable (container runtime may restrict)
chmod 1777 /tmp 2>/dev/null || true
mkdir -p /var/lib/mysql/tmp
chown mysql:mysql /var/lib/mysql/tmp 2>/dev/null || true

# Install test dependencies
pip3 install pytest==8.3.4 pymysql==1.1.1 pyyaml==6.0.2 -q

# Start MySQL reliably
/usr/local/bin/ensure-mysql.sh
if [ $? -ne 0 ]; then
    echo "FATAL: Could not start MySQL"
    mkdir -p /logs/verifier
    echo "0.0" > /logs/verifier/reward.txt
    exit 1
fi

# Run tests
cd /tests
python3 -m pytest test_state.py -v
RESULT=$?

# Write reward
mkdir -p /logs/verifier
if [ $RESULT -eq 0 ]; then
    echo "1.0" > /logs/verifier/reward.txt
else
    echo "0.0" > /logs/verifier/reward.txt
fi

exit $RESULT
