#!/bin/bash

pip3 install requests==2.32.3 urllib3==2.2.3 -q

# Ensure services are running
/app/start_services.sh

# Step 1: Service reconnaissance with nmap
echo "[*] Scanning services with nmap..."
nmap -sV -p 5001,5002,5003 localhost 2>/dev/null

# Step 2: Inspect TLS certificate on port 5003 with openssl
echo "[*] Probing HTTPS service on port 5003..."
openssl s_client -connect localhost:5003 -servername localhost </dev/null 2>/dev/null | openssl x509 -text -noout 2>/dev/null | head -20

# Step 3: Extract cert SHA256 fingerprint and decrypt analyst notes
echo "[*] Extracting certificate fingerprint..."
FINGERPRINT=$(openssl x509 -in /app/certs/server.crt -fingerprint -sha256 -noout | cut -d= -f2 | tr -d :)
echo "    Fingerprint: $FINGERPRINT"

echo "[*] Decrypting analyst notes..."
openssl enc -d -aes-256-cbc -pbkdf2 -in /app/analyst_notes.enc -out /tmp/analyst_notes.txt -pass pass:$FINGERPRINT
echo "--- Decrypted notes ---"
cat /tmp/analyst_notes.txt
echo "--- End notes ---"

# Step 4: Inspect raw binary tokens from port 5001 with xxd
echo "[*] Inspecting raw binary tokens from port 5001..."
curl -s http://localhost:5001/api/session --output /tmp/token1.bin
echo "Token 1:"
xxd /tmp/token1.bin
curl -s http://localhost:5001/api/session --output /tmp/token2.bin
echo "Token 2:"
xxd /tmp/token2.bin

# Step 5: Run the exploit
echo "[*] Running exploit..."
python3 /solution/exploit.py
