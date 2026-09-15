#!/bin/bash
# Helper script to access router vtysh CLI
# Usage: /app/scripts/router.sh <r1|r2|r3|r4|r5> [command]
# Interactive: /app/scripts/router.sh r1
# Single cmd:  /app/scripts/router.sh r1 "show bgp summary"

if [ $# -lt 1 ]; then
    echo "Usage: $0 <r1|r2|r3|r4|r5> [vtysh command]"
    exit 1
fi

ROUTER="$1"
shift

if [ $# -eq 0 ]; then
    exec ip netns exec "$ROUTER" vtysh --vty_socket "/var/run/frr/$ROUTER"
else
    exec ip netns exec "$ROUTER" vtysh --vty_socket "/var/run/frr/$ROUTER" -c "$*"
fi
