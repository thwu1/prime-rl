A data exfiltration incident has been captured. The forensic evidence is at `/app/`:

- `session.pcap` — network capture of the exfiltration session (multiple streams, not all relevant)
- `crypto_engine.so` — stripped shared library implementing the block cipher
- `protocol.py` — the protocol wrapper that drives the cipher library
- `PROTOCOL_SPEC.md` — the protocol's official documentation
- `key_params.json` — the RSA public key used during the session

The protocol specification documents one set of cryptographic primitives, but the actual implementation may not match. Produce three deliverables:

**1. Decrypted exfiltration — `/app/flag.txt`**

Recover the plaintext from the encrypted session and write it to `/app/flag.txt`.

**2. Vulnerability assessment — `/app/vuln_assessment.json`**

Produce a structured security evaluation of every discrepancy between the specification and the actual implementation. The JSON must be an object with a `"discrepancies"` array containing at least 6 entries. Each entry requires these fields:

- `"id"` — short string identifier for the discrepancy
- `"spec_claim"` — what the specification documents
- `"actual_behavior"` — what the implementation actually does
- `"exploitable"` — boolean: whether this specific discrepancy was directly leveraged to recover the key or decrypt data in this attack
- `"severity"` — one of `"critical"`, `"high"`, `"medium"`, `"low"`
- `"impact"` — description of the security consequence

Severity must reflect how much each discrepancy contributed to the breach. Flaws that directly enabled key recovery or decryption must be rated `"critical"`. Differences that weaken security posture but were not directly exploited in this attack should be rated lower.

**3. Proof of exploitation — `/app/forged_payload.bin`**

Demonstrate full bidirectional cryptographic control by constructing a new ciphertext from scratch. Create `/app/forged_payload.bin` containing raw ciphertext — produced using the actual cipher algorithm and operating mode discovered during your analysis — that encrypts the ASCII string `FORGED_BY_ANALYST` using the recovered symmetric key with an all-zero IV. Apply PKCS#7 padding to the cipher's native block size.