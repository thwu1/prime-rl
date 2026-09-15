#!/bin/bash

set -e

# Step 1: Generate RSA key pair (2048-bit, no passphrase)
mkdir -p /app/auth
openssl genrsa -out /app/auth/private.pem 2048 2>/dev/null
openssl rsa -in /app/auth/private.pem -pubout -out /app/auth/public.pem 2>/dev/null

# Step 2: Create credentials file and CVE report
python3 /solution/setup_auth.py

# Step 3: Install analysis tool and run it
cp /solution/analyzer.py /app/analyze.py
python3 /app/analyze.py

# Step 4: Create auth test script and run it
cp /solution/auth_test.sh /app/run_auth_test.sh
chmod +x /app/run_auth_test.sh
bash /app/run_auth_test.sh
