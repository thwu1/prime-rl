#!/bin/bash

# Deploy the correct DNS server implementation, replacing the buggy one
cp /solution/dns_server.py /app/dns_server.py

# Create start.sh with named-checkzone validation and server startup
cat > /app/start.sh << 'STARTEOF'
#!/bin/bash
# Validate all zone files with named-checkzone before starting
for zonefile in /app/zones/*.zone; do
    zone_name=$(basename "$zonefile" .zone)
    if ! named-checkzone "$zone_name" "$zonefile" > /dev/null 2>&1; then
        echo "FATAL: named-checkzone failed for zone '$zone_name' ($zonefile)" >&2
        exit 1
    fi
    echo "Zone '$zone_name' validated OK" >&2
done

# Start the DNS server (handles both UDP and TCP on port 5300)
exec python3 /app/dns_server.py
STARTEOF
chmod +x /app/start.sh

echo "Solution deployed successfully."
