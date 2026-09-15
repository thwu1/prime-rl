# XAES-256-GCM Specification

## Overview

XAES-256-GCM is an authenticated encryption with additional data (AEAD) algorithm
with 256-bit keys and 192-bit nonces. It is an extended-nonce construction on top
of AES-256-GCM: it uses the input key and the large nonce to compute a derived
key and nonce for the underlying AES-256-GCM AEAD.

The large 192-bit nonce enables safe random nonce generation for a virtually
unlimited number of messages (2^80 messages with collision risk 2^-32).

## Notation

- `AES-256_K(X)` denotes the AES-256 block cipher encryption of block X under
  key K. The block size is 128 bits (16 bytes).
- `||` denotes concatenation of byte strings.
- `XOR` denotes bitwise exclusive-or.
- `MSB_1(X)` denotes the most significant bit of X (i.e., bit 7 of the first
  byte in big-endian representation).
- `N[a:b]` denotes the byte slice from index a (inclusive) to index b (exclusive).
- Byte indices are zero-based.

## Algorithm

Given input key K (32 bytes) and input nonce N (24 bytes), the derived
AES-256-GCM key Kx (32 bytes) and nonce Nx (12 bytes) are computed as follows.

### Step 1: CMAC Subkey Generation

The CMAC subkey K1 is derived from K following the subkey generation algorithm
of NIST SP 800-38B (CMAC) for 128-bit block ciphers.

1. Compute L = AES-256_K(0^128), where 0^128 is the all-zero 16-byte block.

2. Derive K1 by "doubling" L in GF(2^128):
   - If MSB_1(L) = 0, then K1 = L << 1
   - If MSB_1(L) = 1, then K1 = (L << 1) XOR R_b

   where `L << 1` is a left shift of the entire 128-bit value by one bit
   position, and R_b is the lexicographically first irreducible polynomial
   of degree 128 over GF(2), represented as a 16-byte constant:

       R_b = 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x00
             0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x87

   That is, R_b is the 128-bit value with only bits 7, 2, 1, and 0 set
   (the polynomial x^7 + x^2 + x + 1). In a byte array of length 16,
   R_b has the value 0x87 at byte index 15 (the final byte) and 0x00
   at all other positions.

### Step 2: KDF Message Construction

Construct two 16-byte input blocks M1 and M2 for the KDF:

    M1 = counter(1) || 0x58 || 0x00 || N[0:12]
    M2 = counter(2) || 0x58 || 0x00 || N[0:12]

where:

- `counter(i)` is the value i encoded as a **16-bit unsigned integer in
  network (big-endian) byte order**. That is:
  - counter(1) = 0x00 0x01 (two bytes)
  - counter(2) = 0x00 0x02 (two bytes)

- 0x58 is the ASCII encoding of the label character 'X' (one byte)

- 0x00 is a separator byte (one byte)

- N[0:12] is the first 12 bytes of the 24-byte input nonce (twelve bytes)

Each block M1, M2 is therefore exactly 2 + 1 + 1 + 12 = 16 bytes.

### Step 3: Derived Key Computation

    Kx = AES-256_K(M1 XOR K1) || AES-256_K(M2 XOR K1)

The derived key Kx is 32 bytes (256 bits), formed by concatenating two
AES-256 block cipher outputs.

### Step 4: Derived Nonce

    Nx = N[12:24]

The derived nonce is the last 12 bytes of the 24-byte input nonce.

### Step 5: Encryption / Decryption

Use the standard AES-256-GCM AEAD (NIST SP 800-38D) with:
- Key = Kx (32 bytes)
- Nonce = Nx (12 bytes)
- Plaintext / Ciphertext and Additional Authenticated Data as provided

The output of encryption is ciphertext || authentication tag (16-byte tag).

## Security Notes

- The input key K MUST be 32 bytes of high-entropy key material.
- The input nonce N MUST be 24 bytes. It is safe to generate randomly.
- A new nonce MUST be used for each message encrypted under the same key.
- K1 can be precomputed once per key for improved performance.


## Appendix A: CMAC-AES256 (NIST SP 800-38B)

CMAC (Cipher-based Message Authentication Code) computes authentication tags
on messages of any length using a block cipher. The XAES-256-GCM KDF uses
CMAC subkeys; the full CMAC algorithm is specified here.

### A.1 Subkey Generation

Two subkeys K1 and K2 are derived from the encryption key K:

1. L = AES-256_K(0^128)
2. K1 = double(L)
3. K2 = double(K1)

where `double(X)` is the GF(2^128) doubling operation defined in Step 1 above:
- If MSB_1(X) = 0: double(X) = X << 1
- If MSB_1(X) = 1: double(X) = (X << 1) XOR R_b

### A.2 Tag Computation

Given key K (32 bytes) and message M of len(M) bytes:

1. Let n = max(1, ceil(len(M) / 16)).
2. Split M into 16-byte blocks: M = M_1 || M_2 || ... || M_n
   where M_n may be shorter than 16 bytes (or empty if len(M) = 0).

3. Prepare the final block M_n*:
   - If len(M) > 0 AND len(M) mod 16 == 0 (complete last block):
     M_n* = M_n XOR K1
   - Otherwise (incomplete or empty last block):
     M_n* = pad(M_n) XOR K2
     where pad(X) = X || 0x80 || 0x00^(15 - len(X))
     That is, append byte 0x80 then pad with zero bytes to reach 16 bytes.

4. CBC-MAC iteration:
   C_0 = 0^128
   For i = 1 to n-1:
     C_i = AES-256_K(C_{i-1} XOR M_i)

5. Tag T = AES-256_K(C_{n-1} XOR M_n*)

The tag T is 16 bytes (128 bits).

### A.3 Properties

- CMAC handles messages of any length, including zero-length messages.
- For zero-length messages, n = 1 and the single block is the padded
  empty block (0x80 || 0x00^15) XOR K2.
- For messages whose length is an exact multiple of 16 bytes, subkey K1
  is used. For all other messages (including empty), subkey K2 is used.
