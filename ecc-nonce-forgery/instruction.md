Six ECDSA signatures on the ANSSI FRP256V1 elliptic curve are provided in `/app/challenge/data.json`. The signer's implementation has a nonce reuse vulnerability — two of the six signatures were generated with the same ephemeral key `k`.

Exploit the nonce reuse to recover the signer's private key, then forge a valid ECRDSA signature (RFC/GOST R 34.10-2012 variant, **not** ISO 14888-3) on the challenge message specified in the data file using SHA-256.

Write the following outputs:

- `/app/recovered_key.txt` — the recovered private key as a lowercase hex string (no `0x` prefix, no whitespace)
- `/app/forged_signature.json` — a JSON object `{"r": "<hex>", "s": "<hex>"}` with the forged ECRDSA signature (lowercase hex, no `0x` prefix, zero-padded to 64 characters)