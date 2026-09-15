Cryptographic artifacts intercepted from an elliptic curve digital signature system are available for analysis.

- `/challenge/curve_params.json` -- Elliptic curve parameters (prime field, short Weierstrass form y^2 = x^3 + ax + b mod p). The standard curve name has been stripped.
- `/challenge/captures.json` -- Eight SHA-256-based digital signatures with their plaintext messages and the signer's public key. Three distinct algorithms from the {ECDSA, ECRDSA-RFC, ECRDSA-ISO} family were used, but algorithm labels are missing. The captured data contains a cryptographic weakness that enables private key extraction — but the weakness spans two different signature algorithms, so standard single-algorithm nonce reuse formulas will not work.
- `/challenge/challenge_message.txt` -- A message requiring a forged signature as proof of key recovery.
- `/challenge/libecc_params.py` -- A reference tool adapted from the ANSSI libecc library's `expand_libecc.py` curve parameter expansion tooling. Computes Montgomery/Barrett internal representation constants for a given prime and word size. Study its interface and conventions.

Produce `/app/output.json`:

```json
{
  "curve_name": "...",
  "classifications": ["...", "...", "...", "...", "...", "...", "...", "..."],
  "vulnerability_type": "...",
  "nonce_reuse_pair": [<index_a>, <index_b>],
  "recovered_private_key": "0x...",
  "forged_signature": {"r": "0x...", "s": "0x..."},
  "internal_params_64bit": {
    "r": "0x...",
    "r_squared": "0x...",
    "mpinv": "0x...",
    "p_reciprocal": "0x..."
  },
  "internal_params_32bit": {
    "r": "0x...",
    "r_squared": "0x...",
    "mpinv": "0x...",
    "p_reciprocal": "0x..."
  }
}
```

- `curve_name`: The well-known standard name of the curve matching the given parameters.
- `classifications[i]`: The algorithm that produced signature i. Valid labels: `"ecdsa"`, `"ecrdsa_rfc"`, `"ecrdsa_iso"`.
- `vulnerability_type`: A string describing the vulnerability class discovered in the captures (be precise about why standard attack formulas are insufficient).
- `nonce_reuse_pair`: The two signature indices that share a nonce.
- `recovered_private_key`: The signer's private scalar, recovered by deriving and applying the correct cross-algorithm nonce recovery formula.
- `forged_signature`: An ECRDSA signature using RFC byte order convention on the challenge message, created with the recovered key. Use deterministic nonce `k = int.from_bytes(SHA256(b"deterministic_forge_nonce"), "big") % order`.
- `internal_params_64bit`: Montgomery/Barrett representation constants for the curve prime under 64-bit word architecture, following the conventions used by `/challenge/libecc_params.py`.
- `internal_params_32bit`: The same constants computed for 32-bit word architecture.

All hex values: lowercase, `0x`-prefixed.