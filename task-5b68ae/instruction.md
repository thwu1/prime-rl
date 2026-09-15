A Vinaigrette signature scheme deployment is configured at `/app/`. Vinaigrette is a simplified variant of the MAYO post-quantum signature scheme, based on the Unbalanced Oil and Vinegar (UOV) construction with a "whipping up" expansion.

The deployment stores its configuration — scheme parameters, the target message, and key management metadata — in a SQLite database at `/app/vinaigrette.db`. The public key (upper-triangular matrices over a finite field) is stored encrypted at `/app/pubkey.enc`; the database describes the encryption cipher, KDF, and how the passphrase is derived from the deployment's TLS certificate at `/app/certs/service.crt`.

A reference implementation of the scheme (key generation, signing, verification) is at `/app/vinaigrette.py`. PARI/GP (`gp`) is available for finite field polynomial arithmetic.

You do not have the secret key.

## Required outputs

1. **Decrypt the public key** and write the plaintext to `/app/public_key.txt`. The file must contain exactly `m` matrix blocks (one per public polynomial), separated by blank lines, in upper-triangular format matching the reference implementation's `parse_public_key` function.

2. **Forge a valid signature** for the target message and write it to `/app/signature.txt`. The file must contain exactly `k * n` space-separated integers, each in the range `[0, q)`, representing the concatenation of `k` vectors `(s_1, ..., s_k)`. A valid signature satisfies `P*(s_1, ..., s_k) = H(message)` where `P*` is the whipped-up public mapping and `H` uses SHAKE256 as specified in the reference implementation. The signature must be non-trivial (not all zeros).