#!/bin/bash
pkill -x nsd 2>/dev/null || true
pkill -x unbound 2>/dev/null || true
sleep 1

nsd -c /app/dns/nsd.conf
echo "NSD started on 127.0.0.1:5353"
sleep 1

unbound -c /app/dns/unbound.conf
echo "Unbound started on 127.0.0.1:5300"
sleep 2

echo "DNS services started."
