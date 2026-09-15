# ACVP Test Vector Processing Procedures

## Overview

The Automated Cryptographic Validation Protocol (ACVP) defines how cryptographic
implementations are validated against NIST standards. Test vectors are provided as
JSON prompt files. A processor must compute the correct cryptographic results and
produce a response JSON file with matching structure.

## Response JSON Structure

The response JSON must mirror the prompt structure:
```json
{
  "vsId": <same as prompt>,
  "algorithm": "<same as prompt>",
  "revision": "<same as prompt>",
  "isSample": <same as prompt>,
  "testGroups": [
    {
      "tgId": <same as prompt>,
      "tests": [
        {
          "tcId": <same as prompt>,
          // ... result fields (algorithm-specific)
        }
      ]
    }
  ]
}
```

## AES-CBC Test Types

### AFT (Algorithm Functional Test)

Standard encrypt/decrypt of AES-CBC data. Payloads are always a multiple of
the 16-byte AES block size but may span one or more blocks.

**Encrypt input:** key, iv, pt (plaintext — 16 to N bytes, block-aligned)
**Encrypt output:** ct (ciphertext — same length as pt)

**Decrypt input:** key, iv, ct (ciphertext — 16 to N bytes, block-aligned)
**Decrypt output:** pt (plaintext — same length as ct)

All hex values are uppercase.

### MCT (Monte Carlo Test)

The MCT exercises the implementation through 100 outer iterations, each containing
1000 inner iterations with chained state.

#### AES-CBC MCT — Encrypt

```
Key[0] = KEY
IV[0] = IV
PT[0] = PT
For i = 0 to 99
    Output Key[i], IV[i], PT[0]
    For j = 0 to 999
        If ( j == 0 )
            CT[j] = AES_CBC_ENCRYPT(Key[i], IV[i], PT[j])
            PT[j+1] = IV[i]
        Else
            CT[j] = AES_CBC_ENCRYPT(Key[i], CT[j-1], PT[j])
            PT[j+1] = CT[j-1]
    Output CT[j]
    AES_KEY_SHUFFLE(Key, i, CT)
    IV[i+1] = CT[999]
    PT[0] = CT[998]
```

Note: `AES_CBC_ENCRYPT(Key, IV, PT)` encrypts a single 128-bit block:
`CT = AES_ECB_ENCRYPT(Key, PT XOR IV)`

#### AES-CBC MCT — Decrypt

Obtained by swapping PT↔CT and replacing encrypt with decrypt in the
pseudocode above. The 2-argument form uses the implicit CBC chain IV:
```
Key[0] = KEY
IV[0] = IV
CT[0] = CT
For i = 0 to 99
    Output Key[i], IV[i], CT[0]
    For j = 0 to 999
        If ( j == 0 )
            PT[j] = AES_CBC_DECRYPT(Key[i], IV[i], CT[j])
            CT[j+1] = IV[i]
        Else
            PT[j] = AES_CBC_DECRYPT(Key[i], CT[j])
            CT[j+1] = PT[j-1]
    Output PT[j]
    AES_KEY_SHUFFLE_DEC(Key, i, PT)
    IV[i+1] = PT[999]
    CT[0] = PT[998]
```

Note: `AES_CBC_DECRYPT(Key, IV, CT)` decrypts a single 128-bit block:
`PT = AES_ECB_DECRYPT(Key, CT) XOR IV`

In CBC mode, the chain IV is always the previous **ciphertext** (input to
decrypt), not the previous plaintext output. The 2-argument form
`AES_CBC_DECRYPT(Key, CT[j])` for j>0 uses CT[j-1] as the implicit IV —
where CT[j-1] is the ciphertext block that was decrypted in iteration j-1.

#### AES Key Shuffle Routine

After each outer iteration, the key is updated using recent ciphertext values.
For encryption, CT is used; for decryption, PT is used (the "output" values).
Let `OUT` refer to CT (encrypt) or PT (decrypt).

```
If ( keyLen == 128 )
    Key[i+1] = Key[i] XOR OUT[999]
If ( keyLen == 192 )
    Key[i+1] = Key[i] XOR ( LSB(OUT[998], 64) || OUT[999] )
If ( keyLen == 256 )
    Key[i+1] = Key[i] XOR ( OUT[998] || OUT[999] )
```

Where:
- `LSB(X, n)` = least significant n bits of X
- `||` = concatenation
- OUT[999] is the last output of the inner loop
- OUT[998] is the second-to-last output

#### MCT Response Format

Each MCT test case produces a `resultsArray` with 100 entries:
```json
{
  "tcId": <id>,
  "resultsArray": [
    {
      "key": "<hex>",
      "iv": "<hex>",
      "pt": "<hex>",
      "ct": "<hex>"
    },
    ...
  ]
}
```

Each entry records the state at the START of the outer iteration (key, iv, pt/ct[0])
plus the FINAL output of that iteration (ct/pt[999]).

## SHA2-256 Test Types

### AFT (Algorithm Functional Test)

Compute SHA-256 hash of the given message.

**Input:** msg (hex string), len (message length in bits)
**Output:** md (message digest, hex string)

When `len` is 0, hash the empty byte string. Otherwise, use the first `len` bits
of the `msg` hex string (which is always byte-aligned in practice).

### MCT (Monte Carlo Test)

There are two versions selected by the `mctVersion` field in the test group:

#### Standard MCT
```
For j = 0 to 99
    A = B = C = SEED
    For i = 0 to 999
        MSG = A || B || C
        MD = SHA-256(MSG)
        A = B
        B = C
        C = MD
    Output MD
    SEED = MD
```

#### Alternate MCT
```
INITIAL_SEED_LENGTH = LEN(SEED) (in bits)
For j = 0 to 99
    A = B = C = SEED
    For i = 0 to 999
        MSG = A || B || C
        If LEN(MSG) >= INITIAL_SEED_LENGTH
            MSG = leftmost INITIAL_SEED_LENGTH bits of MSG
        Else
            MSG = MSG padded with zero bits to INITIAL_SEED_LENGTH
        MD = SHA-256(MSG)
        A = B
        B = C
        C = MD
    Output MD
    SEED = MD
```

#### MCT Response Format
```json
{
  "tcId": <id>,
  "resultsArray": [
    {"md": "<hex>"},
    ...
  ]
}
```
100 entries, one per outer iteration.

### LDT (Large Data Test)

Hash a very large message constructed by repeating a small content pattern.

**Input:** `largeMsg` object:
- `content`: hex string of the repeating unit
- `contentLength`: length of content in bits
- `fullLength`: total message length in bits
- `expansionTechnique`: "repeating"

For "repeating": concatenate the content bytes to itself until the message reaches
`fullLength` bits. Then compute SHA-256 of the full message.

The message may be multiple gigabytes. Use incremental/streaming hashing.

**Output:** md (message digest, hex string)
