#!/usr/bin/env python3
"""Write the structured audit report to /app/audit_report.json."""

import json

report = {
    "vulnerabilities": [
        {
            "function": "aes_gcm_decrypt",
            "bug_type": "ZeroLengthIv",
            "severity": "AUTH_BYPASS",
            "description": (
                "When an empty IV is provided, the function falls back to "
                "a deterministic nonce derived from the key (MD5(key)[:12]) "
                "instead of rejecting the request. A zero-length IV in GCM "
                "leaks the authentication key, enabling forgery of "
                "ciphertexts. See CVE-2017-7822."
            ),
            "fix": (
                "Return None immediately when len(iv) == 0 instead of "
                "substituting a derived nonce."
            ),
        },
        {
            "function": "ecdsa_verify",
            "bug_type": "InvalidSignature",
            "severity": "AUTH_BYPASS",
            "description": (
                "Signatures where r == 0 or s == 0 are accepted without "
                "performing actual verification. An attacker can forge a "
                "valid-looking signature for any message using the trivial "
                "encoding of (0, 0). This is the 'psychic signatures' "
                "class of bugs (CVE-2022-21449)."
            ),
            "fix": (
                "Changed the early-return from True to False so that "
                "degenerate zero-component signatures are rejected."
            ),
        },
        {
            "function": "ecdsa_verify",
            "bug_type": "BerEncodedSignature",
            "severity": "BER_ENCODING / SIGNATURE_MALLEABILITY",
            "description": (
                "The ASN.1 length parser accepts long-form length encoding "
                "for values below 128, which is valid BER but violates "
                "DER. Because the code re-encodes signatures as canonical "
                "DER before passing them to the library, BER-encoded "
                "variants of valid signatures are silently accepted. "
                "This enables signature malleability."
            ),
            "fix": (
                "Added a DER canonicality check: after parsing (r, s) and "
                "re-encoding as DER, reject the signature if the canonical "
                "form differs from the original encoding. Also hardened "
                "the ASN.1 length parser to reject non-minimal encodings."
            ),
        },
        {
            "function": "ecdsa_verify",
            "bug_type": "RangeCheck",
            "severity": "CAN_OF_WORMS",
            "description": (
                "After parsing r and s the code reduces them modulo the "
                "curve order n (r = r % n). This means out-of-range "
                "values such as r + n are silently mapped back to r, "
                "causing the underlying library to accept them as valid. "
                "This defeats the range verification mandated by the "
                "ECDSA standard."
            ),
            "fix": (
                "Removed the modular reduction step and replaced it with "
                "an explicit range check: reject if r >= n or s >= n."
            ),
        },
        {
            "function": "x25519_exchange",
            "bug_type": "ZeroSharedSecret",
            "severity": "DEFINED / CONFIDENTIALITY",
            "description": (
                "The function returns an all-zero shared secret when a "
                "low-order public key is provided (e.g., the identity "
                "point). RFC 7748 Section 6.1 recommends rejecting such "
                "outputs because they indicate the peer's public key "
                "has a small subgroup component, which can leak "
                "information about the private key."
            ),
            "fix": (
                "Added a check after the exchange: if the shared secret "
                "is all-zero bytes, return None instead of the result."
            ),
        },
    ]
}

with open("/app/audit_report.json", "w") as f:
    json.dump(report, f, indent=2)

print("[REPORT] Written /app/audit_report.json with 5 vulnerabilities.")
