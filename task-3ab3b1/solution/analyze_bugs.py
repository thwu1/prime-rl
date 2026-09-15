#!/usr/bin/env python3
"""

Analyze crypto_ops.py for bugs by running Wycheproof test vectors,
then generate findings report.
"""

import json
import sys

sys.path.insert(0, '/app')


def load_vectors(name):
    with open(f'/app/vectors/{name}') as f:
        return json.load(f)


bugs_found = []

# ---- Bug 1: AES-GCM zero-length IV silently returns empty bytes ----
from crypto_ops import aes_gcm_decrypt

gcm_data = load_vectors('aes_gcm_test.json')
for group in gcm_data['testGroups']:
    for tc in group['tests']:
        if 'ZeroLengthIv' not in tc.get('flags', []):
            continue
        key = bytes.fromhex(tc['key'])
        iv = bytes.fromhex(tc['iv'])
        ct = bytes.fromhex(tc['ct'])
        tag = bytes.fromhex(tc['tag'])
        aad = bytes.fromhex(tc['aad'])
        try:
            result = aes_gcm_decrypt(key, iv, ct, tag, aad)
            # If we reach here without exception, the bug exists
            bugs_found.append({
                "function": "aes_gcm_decrypt",
                "bug_type": "AUTH_BYPASS",
                "description": (
                    "Zero-length IV is silently accepted: the function catches "
                    "ValueError and returns empty bytes instead of propagating the "
                    "error. GCM with zero-length IV leaks the authentication key, "
                    "enabling authentication bypass and ciphertext forgery. "
                    "Related: CVE-2017-7822."
                )
            })
            break
        except Exception:
            pass
    if bugs_found:
        break

# ---- Bug 2: ECDSA lenient ASN.1 parsing accepts BER encodings ----
from crypto_ops import ecdsa_verify

ecdsa_data = load_vectors('ecdsa_secp256r1_sha256_test.json')
group = ecdsa_data['testGroups'][0]
key_der = bytes.fromhex(group['publicKeyDer'])
sha = group['sha']
for tc in group['tests']:
    if tc['result'] != 'valid':
        continue
    msg = bytes.fromhex(tc['msg'])
    valid_sig = bytes.fromhex(tc['sig'])
    # Create BER variant with long-form SEQUENCE length
    ber_sig = bytes([0x30, 0x81, valid_sig[1]]) + valid_sig[2:]
    if ecdsa_verify(key_der, msg, ber_sig, sha):
        bugs_found.append({
            "function": "ecdsa_verify",
            "bug_type": "BER_ENCODING",
            "description": (
                "ECDSA verification uses a lenient ASN.1 parser that accepts "
                "non-DER encodings (BER long-form length, non-minimal integer "
                "encodings) and re-encodes to canonical DER before verification. "
                "This bypasses strict DER checking required by X.690 section 11, "
                "enabling signature malleability attacks. "
                "Related: CVE-2020-14966, CVE-2016-1000342."
            )
        })
    break

# ---- Bug 3: HKDF silently clamps oversized output ----
from crypto_ops import hkdf_derive

hkdf_data = load_vectors('hkdf_sha256_test.json')
for group in hkdf_data['testGroups']:
    for tc in group['tests']:
        if 'SizeTooLarge' not in tc.get('flags', []):
            continue
        ikm = bytes.fromhex(tc['ikm'])
        salt = bytes.fromhex(tc['salt']) if tc['salt'] else None
        info = bytes.fromhex(tc['info'])
        size = tc['size']
        try:
            result = hkdf_derive(ikm, salt, info, size, 'SHA-256')
            # If we reach here, the size limit was not enforced
            bugs_found.append({
                "function": "hkdf_derive",
                "bug_type": "MISSING_STEP",
                "description": (
                    "HKDF derive catches ValueError for output sizes exceeding "
                    "the RFC 5869 limit of 255 * hash_length bytes and silently "
                    "clamps to the maximum, returning truncated output. This "
                    "violates the specification and produces output that collides "
                    "with legitimate shorter derivations, breaking key uniqueness."
                )
            })
            break
        except Exception:
            pass
    if len(bugs_found) >= 3:
        break

# ---- Write findings report ----
print(f"Identified {len(bugs_found)} bug(s):")
for b in bugs_found:
    print(f"  [{b['bug_type']}] {b['function']}: {b['description'][:80]}...")

findings = {"bugs": bugs_found}
with open('/app/findings.json', 'w') as f:
    json.dump(findings, f, indent=2)
print(f"\nFindings written to /app/findings.json")
