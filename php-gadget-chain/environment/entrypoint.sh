#!/bin/bash
# Generate random flag at runtime (not build time)
FLAG="FLAG{$(head -c 32 /dev/urandom | md5sum | head -c 32)}"
echo -n "$FLAG" > /app/flag.txt

# Generate HMAC secret key for import.php signature verification
head -c 64 /dev/urandom | base64 | head -c 64 > /app/hmac_secret.key
chmod 600 /app/hmac_secret.key

# Start Apache in foreground
exec apachectl -D FOREGROUND
