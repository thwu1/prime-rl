#!/bin/bash
set -e

# Create the encrypted vault file
# Passphrase is first 32 chars of SECRET_KEY_BASE from .env
PASSPHRASE="7f2b48e91a4c53d8e06f7a9b2c3d4e5f"

# Write plaintext to pipe, encrypt directly — no temp file on disk
printf '{"vault_format":"v2","rotated_credentials":[{"service":"github-deploy","token":"ghr_k2VnR6rKpL9sYhTf8WcJdQ0dHiB5fA291kwV","rotated_at":"2024-03-14T22:00:00Z"},{"service":"github-app-v2","token":"ghs_p1WyS7tLqM0xZiUg4CfMqU0eIjC6gB4ENsHt","rotated_at":"2024-03-14T23:30:00Z"}]}' \
  | openssl enc -aes-256-cbc -pbkdf2 -pass "pass:${PASSPHRASE}" -out /app/corpus/vault.enc
