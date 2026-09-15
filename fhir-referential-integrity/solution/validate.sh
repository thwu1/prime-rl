#!/bin/bash
#
# HIPAA compliance scanner using jq for structural validation
# and openssl for independent cryptographic hash verification.

INPUT="/app/output/anonymized.json"
REPORT="/app/output/phi_scan.json"
CRYPTO_KEY="hipaa-safe-harbor-2024"

mkdir -p /app/output

# 1. Verify all resource IDs are 64-char lowercase hex
ids_valid=$(jq '[.entry[].resource.id | select(test("^[0-9a-f]{64}$") | not)] | length == 0' "$INPUT")

# 2. Verify all references point to hashed IDs in ResourceType/hash format
references_valid=$(jq '[
  [.entry[].resource | .. | objects | select(has("reference")) | .reference]
  | .[]
  | select(type == "string")
  | select(test("^[A-Z][a-zA-Z]+/[0-9a-f]{64}$") | not)
] | length == 0' "$INPUT")

# 3. Check that no plaintext patient/practitioner names remain
# Look for name objects that still have family or given fields
names_clean=$(jq '[
  .entry[].resource
  | select(.resourceType == "Patient" or .resourceType == "Practitioner")
  | .name // []
  | .[]
  | select(has("family") or has("given"))
] | length == 0' "$INPUT")

# 4. Check no phone/email contact values remain
contacts_clean=$(jq '[
  .entry[].resource
  | .. | objects
  | select(.system == "phone" or .system == "email" or .system == "fax")
  | select(has("value"))
  | .value
] | length == 0' "$INPUT")

# 5. Check postal codes are properly generalized (XXX00 or 00000)
addresses_clean=$(jq '[
  [.entry[].resource | .. | objects | select(has("postalCode")) | .postalCode]
  | .[]
  | select(. != null)
  | select(test("^[0-9]{3}00$|^00000$") | not)
] | length == 0' "$INPUT")

# 6. Independent hash verification using openssl
# Compute HMAC-SHA256 of "pat-001" with the crypto key and compare
# to the first Patient resource ID in the output
pat001_expected=$(echo -n "pat-001" | openssl dgst -sha256 -hmac "$CRYPTO_KEY" 2>/dev/null | sed 's/^.*= //')

# Find the Patient resource whose ID matches the expected hash
pat001_found=$(jq -r --arg hash "$pat001_expected" '
  [.entry[].resource | select(.resourceType == "Patient" and .id == $hash)] | length > 0
' "$INPUT")

hash_verified="$pat001_found"

# Write the JSON report using jq
jq -n \
  --argjson ids_valid "$ids_valid" \
  --argjson references_valid "$references_valid" \
  --argjson names_clean "$names_clean" \
  --argjson contacts_clean "$contacts_clean" \
  --argjson addresses_clean "$addresses_clean" \
  --argjson hash_verified "$hash_verified" \
  '{
    ids_valid: $ids_valid,
    references_valid: $references_valid,
    names_clean: $names_clean,
    contacts_clean: $contacts_clean,
    addresses_clean: $addresses_clean,
    hash_verified: $hash_verified
  }' > "$REPORT"

echo "PHI scan report written to $REPORT"
cat "$REPORT"
