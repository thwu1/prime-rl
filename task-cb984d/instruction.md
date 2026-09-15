An ACVP (Automated Cryptographic Validation Protocol) prompt file is located at `/app/prompt.json`. It contains NIST SP 800-90A CTR-DRBG test vectors across four test groups covering:

- **AES-128** with derivation function, prediction resistance enabled
- **AES-256** without derivation function, prediction resistance enabled
- **AES-128** with derivation function, explicit reseed (no prediction resistance)
- **AES-256** without derivation function, explicit reseed (no prediction resistance)

Build a processor that reads `/app/prompt.json`, implements the CTR-DRBG algorithm per NIST SP 800-90A, and writes the correct ACVP response to `/app/response.json`.

The response JSON must follow the ACVP response format:

```json
{
  "vsId": 42,
  "algorithm": "ctrDRBG",
  "revision": "1.0",
  "testGroups": [
    {
      "tgId": <group_id>,
      "tests": [
        {"tcId": <test_id>, "returnedBits": "<hex_output>"},
        ...
      ]
    },
    ...
  ]
}
```

Each test case requires processing the DRBG lifecycle (instantiate, optionally reseed, generate twice, return second output) following the correct procedure for the given prediction resistance / reseed configuration. The `returnedBits` field is the uppercase hex-encoded output of the final generate call.