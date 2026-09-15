#!/bin/bash

cd /app

# Step 1: Identify the key exchange TCP stream using tshark
echo "[*] Identifying key exchange stream on port 31337..."
STREAM=$(tshark -r /app/capture.pcap \
    -Y "tcp.dstport == 31337 && tcp.flags.syn == 1 && tcp.flags.ack == 0" \
    -T fields -e tcp.stream 2>/dev/null | head -1)
echo "[*] Found stream: ${STREAM}"

# Step 2: Extract raw TCP stream data using tshark follow
echo "[*] Extracting stream payload..."
tshark -r /app/capture.pcap -q \
    -z "follow,tcp,raw,${STREAM}" 2>/dev/null > /tmp/stream_raw.txt

# Step 3: Parse protocol messages and solve DLP (outputs key material)
echo "[*] Running algebraic attack..."
python3 /solution/solver.py

# Step 4: Derive AES key from shared secret using openssl
echo "[*] Deriving AES key with openssl..."
cat /tmp/shared_secret.bin | openssl dgst -sha256 -binary | \
    head -c 16 | xxd -p -c 32 > /tmp/aes_key.hex

# Step 5: Decrypt ciphertext using openssl
echo "[*] Decrypting with openssl enc..."
openssl enc -aes-128-cbc -d \
    -K "$(cat /tmp/aes_key.hex)" \
    -iv "$(cat /tmp/iv.hex)" \
    -in /tmp/ciphertext.bin \
    -out /app/flag.txt

echo "[*] Recovered flag:"
cat /app/flag.txt
echo ""
