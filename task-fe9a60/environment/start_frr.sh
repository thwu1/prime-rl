#!/bin/bash
# Start FRR daemons for configuration validation

mkdir -p /var/run/frr /var/log/frr
chown -R frr:frr /var/run/frr /var/log/frr /etc/frr 2>/dev/null

# Check if already running
if pgrep -x zebra > /dev/null 2>&1; then
    echo "FRR daemons already running"
    exit 0
fi

# Start zebra (must be first)
/usr/lib/frr/zebra -d -A 127.0.0.1
sleep 2

# Start bgpd
/usr/lib/frr/bgpd -d -A 127.0.0.1
sleep 2

echo "FRR daemons started. Use 'vtysh' to interact."
