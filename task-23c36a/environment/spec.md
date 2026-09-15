# ACVP AES-CBC Specification — Test Types and Procedures

## Test Types

### AFT — Algorithm Functional Test

AFT tests exercise normal AES-CBC encrypt/decrypt on a single block. Each test case provides `key`, `iv`, and either `pt` (for encrypt) or `ct` (for decrypt). The implementation computes the missing value using standard AES-CBC.

### MCT — Monte Carlo Test

MCT tests exercise the implementation under strenuous circumstances using chained computations. Each MCT test group contains a single test case providing initial conditions. The implementation must execute the MCT algorithm and produce a `resultsArray` with 100 entries (one per outer round).

## AES-CBC Monte Carlo Test — Encrypt

The initial condition is the tuple (KEY, IV, PT) from the test case.

```
Key[0] = KEY
IV[0] = IV
PT[0] = PT
For i = 0 to 99
    Output Key[i], IV[i], PT[0]
    For j = 0 to 999
        If ( j=0 )
            CT[j] = AES_CBC_ENCRYPT(Key[i], IV[i], PT[j])
            PT[j+1] = IV[i]
        Else
            CT[j] = AES_CBC_ENCRYPT(Key[i], PT[j])
            PT[j+1] = CT[j-1]
    Output CT[j]
    AES_KEY_SHUFFLE(Key, CT)
    SALTED_KEY_EVOLUTION(Key, i)
    IV[i+1] = CT[j]
    PT[0] = CT[j-1]
```

Notes on CBC semantics in the inner loop:
- `AES_CBC_ENCRYPT(Key, IV, PT)` encrypts a single block PT using key Key with explicit IV: `CT = AES_ECB_ENCRYPT(Key, PT XOR IV)`
- `AES_CBC_ENCRYPT(Key, PT)` (without explicit IV) continues the CBC chain using the previous ciphertext as the implicit IV: `CT[j] = AES_ECB_ENCRYPT(Key, PT[j] XOR CT[j-1])`

Each outer round i produces one entry in `resultsArray` containing the values of Key[i], IV[i], PT[0], and CT[999].

## AES-CBC Monte Carlo Test — Decrypt

The pseudocode for decryption is obtained by replacing all PT references in the encryption pseudocode with CT references and all CT references with PT references. Replace the encrypt operation with the corresponding decrypt operation. The key shuffle also swaps CT for PT.

In CBC decryption: `PT = AES_ECB_DECRYPT(Key, CT) XOR IV`, where the IV for the first block is explicit and for subsequent blocks is the previous ciphertext block.

## AES Monte Carlo Key Shuffle

The key shuffle routine updates the key after each outer round. The `||` symbol denotes concatenation. MSB(X, n) captures the n most significant bits of X. LSB(X, n) captures the n least significant bits.

For encryption, the routine uses CT values. For decryption, swap all CT references with PT.

```
If ( keylen = 128 )
    Key[i+1] = Key[i] XOR MSB(CT[j], 128)
If ( keylen = 192 )
    Key[i+1] = Key[i] XOR ( LSB(CT[j-1], 64) || MSB(CT[j], 128) )
If ( keylen = 256 )
    Key[i+1] = Key[i] XOR ( MSB(CT[j-1], 128) || MSB(CT[j], 128) )
```

Since each block is exactly 128 bits, MSB(CT[j], 128) = CT[j] and MSB(CT[j-1], 128) = CT[j-1]. LSB(CT[j-1], 64) is the last 64 bits (8 bytes) of CT[j-1].

## Salted Key Evolution

After the standard AES Key Shuffle, apply an additional transformation using the `domainSeparator` field from the prompt JSON. This field is a 256-bit (32-byte) hex string.

```
salt = SHA-256( domainSeparator || i_as_4_byte_big_endian )[0 : keyLenBytes]
Key[i+1] = Key[i+1] XOR salt
```

Where:
- `domainSeparator` is the raw 32 bytes decoded from the hex string in the prompt
- `i` is the current outer round number (0 through 99)
- `i_as_4_byte_big_endian` is the round number encoded as a 4-byte big-endian integer
- The SHA-256 output is truncated to match the key length (16 bytes for 128-bit, 24 bytes for 192-bit, 32 bytes for 256-bit)
- The resulting salt is XORed with the key that was already updated by the key shuffle

This transformation must be applied in both encrypt and decrypt MCT modes.

## Response Format

The response JSON must mirror the prompt structure:

```json
{
  "vsId": <same as prompt>,
  "algorithm": "ACVP-AES-CBC",
  "revision": "1.0",
  "isSample": <same as prompt>,
  "testGroups": [
    {
      "tgId": <matching prompt group>,
      "tests": [
        // For AFT encrypt:
        { "tcId": <id>, "ct": "<uppercase hex>" },
        // For AFT decrypt:
        { "tcId": <id>, "pt": "<uppercase hex>" },
        // For MCT:
        {
          "tcId": <id>,
          "resultsArray": [
            { "key": "<hex>", "iv": "<hex>", "pt": "<hex>", "ct": "<hex>" },
            // ... 100 entries total
          ]
        }
      ]
    }
  ]
}
```

All hex values must be uppercase strings without "0x" prefix.
