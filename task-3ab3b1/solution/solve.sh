#!/bin/bash

cd /app

# Step 1: Analyze bugs using Wycheproof test vectors
python3 /solution/analyze_bugs.py

# Step 2: Apply the corrected implementation
cp /solution/crypto_ops_fixed.py /app/crypto_ops.py

# Step 3: Verify fixes pass test vectors
python3 -c "
import json, sys
sys.path.insert(0, '/app')
from crypto_ops import aes_gcm_decrypt, ecdsa_verify, hkdf_derive

# Verify zero-IV now raises
data = json.load(open('/app/vectors/aes_gcm_test.json'))
for g in data['testGroups']:
    for tc in g['tests']:
        if 'ZeroLengthIv' in tc.get('flags', []):
            try:
                aes_gcm_decrypt(bytes.fromhex(tc['key']), bytes.fromhex(tc['iv']),
                    bytes.fromhex(tc['ct']), bytes.fromhex(tc['tag']),
                    bytes.fromhex(tc['aad']))
                print('ERROR: zero-IV still accepted')
                sys.exit(1)
            except Exception:
                print('OK: zero-IV correctly raises')
            break
    break

# Verify BER sig now rejected
data = json.load(open('/app/vectors/ecdsa_secp256r1_sha256_test.json'))
g = data['testGroups'][0]
for tc in g['tests']:
    if tc['result'] == 'valid':
        sig = bytes.fromhex(tc['sig'])
        ber = bytes([0x30, 0x81, sig[1]]) + sig[2:]
        if ecdsa_verify(bytes.fromhex(g['publicKeyDer']),
                        bytes.fromhex(tc['msg']), ber, g['sha']):
            print('ERROR: BER sig still accepted')
            sys.exit(1)
        else:
            print('OK: BER sig correctly rejected')
        break
    break

# Verify oversized HKDF now raises
data = json.load(open('/app/vectors/hkdf_sha256_test.json'))
for g in data['testGroups']:
    for tc in g['tests']:
        if 'SizeTooLarge' in tc.get('flags', []):
            try:
                hkdf_derive(bytes.fromhex(tc['ikm']),
                    bytes.fromhex(tc['salt']) if tc['salt'] else None,
                    bytes.fromhex(tc['info']), tc['size'], 'SHA-256')
                print('ERROR: oversized HKDF still accepted')
                sys.exit(1)
            except Exception:
                print('OK: oversized HKDF correctly raises')
            break
    break

print('All fixes verified.')
"
