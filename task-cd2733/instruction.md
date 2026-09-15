A corporate certificate authority uses a custom PRNG system (`HardenedPRNG`) across multiple services. Following a suspected key compromise, you have been retained as an external security evaluator. Conduct a comprehensive assessment of the PRNG-based key generation infrastructure: determine which PRNG instances are cryptographically sound and which are exploitable, prove any compromises you find, and review a proposed remediation from the engineering team.

Available at `/app/`:

- `prng.py` — HardenedPRNG source code with configurable output whitening.
- `keygen.py` — RSA key generation script; references an unavailable configuration module.
- `pubkey.der` — the CA's RSA public key (DER format).
- `audit.db` — SQLite database containing operational logs for all deployed PRNG instances, their logged outputs, and key generation events.
- `intercepted.enc` — hex-encoded RSA ciphertext of an intercepted internal communication.
- `remediation_proposal.txt` — the engineering team's proposed configuration fix, awaiting your review.

The audit database contains multiple PRNG instances using different algorithms and configurations. Not all use HardenedPRNG, and those that do may have different security properties depending on their configuration. Evaluate every instance, classify each as secure or compromised, and for any compromised instance prove the vulnerability by recovering the corresponding private key and decrypting the intercepted message. Then review the remediation proposal: determine whether the proposed `whiten_rounds` value is sufficient, and identify the true minimum value that prevents state-recovery attacks.

Write your findings to `/app/assessment.json` in this format:
```json
{
    "compromised_instance": "<instance_id of the vulnerable PRNG>",
    "attack_vector": "<description of the exploited vulnerability>",
    "decrypted_message": "<recovered plaintext proving the compromise>",
    "secure_instances": ["<instance_id>", "..."],
    "remediation_verdict": "ACCEPT or REJECT",
    "minimum_secure_rounds": <integer>
}
```

Also write the decrypted plaintext to `/app/flag.txt`.