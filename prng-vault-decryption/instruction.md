A "Secure Vault" system at `/app/vault/` protects an encrypted flag using hybrid RSA+AES encryption. The vault's RSA private key was destroyed after creation, but a PRNG calibration diagnostic log was accidentally left behind in `/app/vault/data/`.

Three security patches have been proposed to fix the underlying vulnerability. The patch implementations are at `/app/vault/patches/`.

**Part 1 — Exploit:** Analyze the vault's cryptographic implementation in `/app/vault/crypto_utils.py`, study the architecture documented in `/app/vault/README.txt`, and exploit weaknesses in the key generation process to recover the plaintext flag. Write the recovered flag to `/app/flag.txt`.

**Part 2 — Evaluate:** Assess each proposed security patch (`patch_a.py`, `patch_b.py`, `patch_c.py`) for effectiveness against the vulnerability you exploited. Determine whether each patch genuinely mitigates the attack or merely provides a false sense of security. Write your assessment to `/app/patch_assessment.json` with the structure:

```json
{
  "patch_a": {"effective": <bool>, "justification": "<explanation>"},
  "patch_b": {"effective": <bool>, "justification": "<explanation>"},
  "patch_c": {"effective": <bool>, "justification": "<explanation>"}
}
```

All vault data (public key, encrypted flag, encrypted AES key, nonce, and diagnostic log) is in `/app/vault/data/`.