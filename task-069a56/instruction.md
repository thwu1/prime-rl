You are given a set of cryptographic challenge configurations in `/app/challenges.json`. Each challenge specifies a Noise Protocol name (e.g. `Noise_XX_25519_ChaChaPoly_SHA256`) along with all necessary key material (static and ephemeral private keys as hex), prologues, optional pre-shared keys, and a sequence of message payloads.

Your task is to produce the complete message transcript for each challenge — both the handshake phase and any subsequent transport-phase messages — as well as the final handshake hash.

A condensed reference for the Noise Protocol Framework is provided at `/app/noise_spec_reference.txt`. The six challenges span multiple handshake patterns, cipher choices, hash functions, and one PSK-modified variant.

Write results to `/app/results.json`:
```json
[
  {
    "protocol_name": "Noise_XX_25519_ChaChaPoly_SHA256",
    "handshake_hash": "<lowercase hex>",
    "messages": [
      {"ciphertext": "<lowercase hex>"},
      ...
    ]
  },
  ...
]
```

The `messages` array must contain one entry per payload in the corresponding challenge, in order. All hex strings must be lowercase.