#!/bin/bash

# No external pip deps needed — pure Python standard library
# Analyze both binaries, generate all keygens, design gamma, produce audit
python3 /solution/extract_and_keygen.py

# Verify alpha keygen
echo "=== Alpha Verification ==="
for user in admin test reverser2024 hello_world x; do
    serial=$(python3 /app/keygen_alpha.py "$user")
    result=$(/app/crackme_alpha "$user" "$serial")
    echo "  $user: serial=$serial result=$result"
done

# Verify beta keygen
echo "=== Beta Verification ==="
for user in admin test reverser2024 hello_world x; do
    serial=$(python3 /app/keygen_beta.py "$user")
    result=$(/app/crackme_beta "$user" "$serial")
    echo "  $user: serial=$serial result=$result"
done

# Verify universal keygen
echo "=== Universal Keygen Verification ==="
for binary in /app/crackme_alpha /app/crackme_beta; do
    for user in admin test; do
        serial=$(python3 /app/keygen_universal.py "$binary" "$user")
        result=$("$binary" "$user" "$serial")
        echo "  $binary $user: serial=$serial result=$result"
    done
done

# Verify gamma keygen against vm_runner
echo "=== Gamma Verification ==="
for user in admin test reverser2024 hello_world x; do
    serial=$(python3 /app/keygen_gamma.py "$user")
    result=$(/app/vm_runner /app/gamma.bc /app/gamma_key.bin "$user" "$serial")
    echo "  $user: serial=$serial result=$result"
done

# Cross-rejection checks
echo "=== Cross-Rejection ==="
alpha_serial=$(python3 /app/keygen_alpha.py admin)
beta_serial=$(python3 /app/keygen_beta.py admin)
gamma_serial=$(python3 /app/keygen_gamma.py admin)
echo "  gamma serial on alpha: $(/app/crackme_alpha admin "$gamma_serial")"
echo "  gamma serial on beta: $(/app/crackme_beta admin "$gamma_serial")"
echo "  alpha serial on gamma: $(/app/vm_runner /app/gamma.bc /app/gamma_key.bin admin "$alpha_serial")"

echo "=== Audit JSON ==="
python3 -c "import json; print(json.dumps(json.load(open('/app/audit.json')), indent=2))"
