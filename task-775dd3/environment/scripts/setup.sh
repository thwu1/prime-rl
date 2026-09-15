#!/bin/bash
# Initialize environment and start services

mkdir -p /var/secret /run/php /usr/local/apache2/logs

# Generate flag deterministically at runtime
if [ ! -f /var/secret/flag.txt ]; then
    /usr/local/bin/flaggen > /var/secret/flag.txt
    chown www-data:www-data /var/secret/flag.txt
    chmod 0440 /var/secret/flag.txt
fi

# Start PHP-FPM if not already running
if ! pgrep -x "php-fpm8.3" > /dev/null 2>&1; then
    /usr/sbin/php-fpm8.3 --daemonize 2>&1 || true
    sleep 1
fi

# Verify PHP-FPM is listening
for i in $(seq 1 5); do
    if ss -tlnp 2>/dev/null | grep -q ':9000' || \
       netstat -tlnp 2>/dev/null | grep -q ':9000'; then
        break
    fi
    sleep 1
done

# Start Apache if not already running
if ! pgrep -x "httpd" > /dev/null 2>&1; then
    /usr/local/apache2/bin/apachectl start 2>&1 || true
    sleep 1
fi

# Wait for server to be ready
for i in $(seq 1 30); do
    if curl -s -o /dev/null -w '%{http_code}' http://localhost/ 2>/dev/null | grep -q '200'; then
        echo "[*] Services ready - http://localhost"
        exit 0
    fi
    sleep 1
done

echo "[-] Warning: server may not be fully ready"
