#!/bin/bash

# Extract services.lab zone from pcap capture
python3 /solution/extract_zone.py /app/captures/dns_traffic.pcap /app/zones/services.lab.zone services.lab

# Deploy the DNS server implementation
cp /solution/dns_server_impl.py /app/dns_server.py

# Verify the server starts and responds
python3 /app/dns_server.py &
SERVER_PID=$!
sleep 2

dig @127.0.0.1 -p 5353 example.com A +short
dig @127.0.0.1 -p 5353 api.services.lab A +short
dig @127.0.0.1 -p 5353 +tcp example.com A +short

kill $SERVER_PID 2>/dev/null
wait $SERVER_PID 2>/dev/null
