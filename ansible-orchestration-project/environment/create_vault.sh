#!/bin/bash
mkdir -p /app
cat > /app/seed_vault.yml << 'VEOF'
---
db_master_password: "Pg_m4st3r_2024!"
api_token: "tok-9f8e7d6c5b4a3210"
tls_passphrase: "X7kL9mN2pQ4r"
VEOF
echo "Fl33t_0ld!" > /tmp/vault_pass.txt
ansible-vault encrypt /app/seed_vault.yml --vault-password-file /tmp/vault_pass.txt
rm /tmp/vault_pass.txt
