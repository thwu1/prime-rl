A production cryptographic system at `/app/challenge/` implements an elliptic curve key exchange followed by AES-256-CBC symmetric encryption. Your assignment is to conduct a full security audit: break the system, evaluate proposed fixes, and design a secure replacement.

## Challenge files

- `/app/challenge/public_params.json` — Curve parameters, base point `G`, public key `Q = s·G`
- `/app/challenge/encrypt.py` — Encryption pipeline source code
- `/app/challenge/encrypted_payload.b64` — Base64-encoded AES-256-CBC ciphertext
- `/app/challenge/key_derivation.json` — Key derivation specification
- `/app/challenge/proposed_remediations.json` — Four patches proposed by the engineering team
- `/app/challenge/security_requirements.txt` — Constraints for a secure replacement

## Deliverables

### 1. Cryptanalysis — `/app/solution.txt`
Recover the secret scalar `s`, decrypt the payload, and write the plaintext.

### 2. Vulnerability audit — `/app/audit.json`
Analyze the system's algebraic and number-theoretic properties. Then evaluate each of the four proposed remediations (R1–R4) described in `/app/challenge/proposed_remediations.json` and judge whether each would prevent an attacker from recovering the secret scalar. Justify your verdicts through the mathematical properties you identified.

Required schema:

    {
      "modulus_type": "<prime or composite>",
      "cm_discriminant": <integer or null if not a CM curve>,
      "j_invariant": <integer or null>,
      "factoring_method": "<name of factoring method used>",
      "ecdlp_method": "<name of ECDLP method used>",
      "R1_verdict": "<EFFECTIVE or INEFFECTIVE>",
      "R2_verdict": "<EFFECTIVE or INEFFECTIVE>",
      "R3_verdict": "<EFFECTIVE or INEFFECTIVE>",
      "R4_verdict": "<EFFECTIVE or INEFFECTIVE>"
    }

### 3. Secure replacement — `/app/secure_config.json`
Design a new ECC configuration over a composite modular ring that resists the class of attacks you identified. The configuration must satisfy every constraint in `/app/challenge/security_requirements.txt`. Proving that your design resists Pohlig-Hellman requires computing curve group orders and verifying their largest prime factors.

Required schema:

    {
      "p": "<first prime as decimal string>",
      "q": "<second prime as decimal string>",
      "a": "<curve coefficient a as decimal string>",
      "b": "<curve coefficient b as decimal string>",
      "Gx": "<base point x as decimal string>",
      "Gy": "<base point y as decimal string>"
    }

## Environment

`ecm` (GMP-ECM), `gp` (PARI/GP), and `openssl` are installed.