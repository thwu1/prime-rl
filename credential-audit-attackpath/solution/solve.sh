#!/bin/bash

cd /app

# Step 1: Prepare hash files for cracking
echo "[*] Preparing NTLM hashes for cracking..."

# Create pwdump-format file for john (strip domain prefix)
sed 's/^[^\\]*\\//' /app/loot/ntds_dump.txt > /tmp/pwdump_hashes.txt

# Also create user:hash mapping for the Python fallback cracker
awk -F: '{
    user=$1;
    sub(/^.*\\/, "", user);
    nt=$4;
    print user":"nt
}' /app/loot/ntds_dump.txt > /tmp/user_hash_map.txt

# Step 2: Combine wordlists
echo "[*] Building combined wordlist..."
cat /app/wordlists/base.txt /app/wordlists/company_terms.txt | sort -u > /tmp/combined_wordlist.txt

# Step 3: Generate custom hashcat rules
echo "[*] Generating custom cracking rules..."
cat > /tmp/enterprise_rules.rule << 'RULEEOF'
:
l
c
c $!
c $#
c $$
c $@
$!
$#
$$
$@
c $! $2 $0 $2 $4
c $# $2 $0 $2 $4
c $$ $2 $0 $2 $4
c $@ $2 $0 $2 $4
c $2 $0 $2 $4 $!
c $2 $0 $2 $4 $#
c $2 $0 $2 $4 $$
c $2 $0 $2 $4 $@
c $2 $4 $!
c $2 $4 $#
c $2 $4 $$
c $2 $4 $@
$2 $0 $2 $4
$$ $2 $0 $2 $4
$! $2 $0 $2 $4
$# $2 $0 $2 $4
$@ $2 $0 $2 $4
l $$ $2 $0 $2 $4
l $! $2 $0 $2 $4
c $2 $0 $2 $3 $!
c $2 $0 $2 $3 $#
RULEEOF

# Step 4: Crack with john the ripper (pwdump format, --rules=All)
echo "[*] Cracking NTLM hashes with john..."
john --wordlist=/tmp/combined_wordlist.txt --rules=All --format=nt /tmp/pwdump_hashes.txt 2>/dev/null || true

# Extract john results
john --show --format=nt /tmp/pwdump_hashes.txt 2>/dev/null > /tmp/john_cracked.txt || true

# Step 5: Try hashcat as secondary cracker
if command -v hashcat &> /dev/null; then
    echo "[*] Running hashcat with custom rules..."
    awk -F: '{print $4}' /tmp/pwdump_hashes.txt > /tmp/nt_only.txt
    hashcat -m 1000 /tmp/nt_only.txt /tmp/combined_wordlist.txt \
        -r /tmp/enterprise_rules.rule \
        --force --potfile-disable -o /tmp/hashcat_output.txt \
        --outfile-format=2 2>/dev/null || true
fi

# Step 6: Run Python fallback cracker for any remaining hashes, then analyze
echo "[*] Running analysis and fallback cracker..."
python3 /solution/analyze.py

echo "[*] Analysis complete. Report written to /app/report/findings.json"
