#!/bin/bash
#
# Solution pipeline:
# 1. Compile the C brute-force seed finder
# 2. Run it to recover the MT19937 seed
# 3. Replay the PRNG to extract the admin token
# 4. Write the result to /app/admin_token.txt

set -e

echo "[*] Step 1: Compiling brute-force seed finder..."
gcc -O3 -o /tmp/bruteforce_seed /solution/bruteforce_seed.c
echo "[+] Compiled successfully."

echo "[*] Step 2: Brute-forcing the MT19937 seed (this may take a few minutes)..."
SEED=$(/tmp/bruteforce_seed)
echo "[+] Recovered seed: ${SEED}"

echo "[*] Step 3: Replaying PRNG to extract admin token..."
ADMIN_TOKEN=$(python3 /solution/replay_mt.py "${SEED}")
echo "[+] Admin token: ${ADMIN_TOKEN}"

echo "[*] Step 4: Writing result..."
echo -n "${ADMIN_TOKEN}" > /app/admin_token.txt
echo "[+] Done. Admin token written to /app/admin_token.txt"
