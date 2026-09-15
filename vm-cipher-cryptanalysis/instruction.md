An incident response team has seized three encrypted session captures in `/app/encrypted/` alongside the stripped encryption tool `/app/cipher_engine` that produced them. Session metadata is in `/app/encrypted/manifest.json`. A preliminary binary survey (intentionally incomplete) is in `/app/audit_notes.txt`.

The manifest does **not** label encryption modes directly. You must reverse engineer the binary to discover all key derivation paths and determine which path was used for each session based on the available evidence.

Produce three deliverables:

1. **Security assessment** at `/app/assessment.json`: a JSON object keyed by session name (`alpha`, `beta`, `gamma`). Each value must contain:
   - `verdict`: `"recoverable"` or `"not_recoverable"`
   - `justification`: explanation grounded in your analysis of the binary's cryptographic internals and each session's encryption context
   - `attack_complexity`: estimated computational cost to recover the session key (e.g., `"~100 encrypt-and-compare operations"` or `"2^32 exhaustive search with no efficient distinguisher"`)
   - `risk_level`: integer 1–5 rating (1 = negligible risk, 5 = critical/trivially exploitable)

   Risk levels must reflect the relative exploitability of each session — sessions with smaller brute-force windows or dependent key relationships are higher risk than sessions seeded from high-entropy sources.

2. **Recovered flag** at `/app/flag.txt`: Decrypt every session you classified as recoverable, extract the flag fragments from the plaintext, and combine them into the complete flag.

3. **Proof-of-exploitation forgery** at `/app/forgery.enc`: Demonstrate full mastery of the cipher by creating a ciphertext that the binary decrypts to the exact byte string `SECURITY_AUDIT_COMPLETE:VERIFIED` using seed `1337` in standard mode:
   ```
   /app/cipher_engine d 1337 /app/forgery.enc /tmp/check.dec
   ```
   The resulting file must contain exactly that string with no trailing newline or extra bytes.