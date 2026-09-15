#!/usr/bin/env python3
"""

Custom DSA-like Signature Scheme — Challenge Description
=========================================================

This file documents the signing algorithm used to generate the challenge data
in data.json. The actual secret parameters are NOT included.

Signature Scheme
----------------
  Group order:  q  (secp256k1 curve order, 256 bits)
  Private key:  x  in [1, q-1]

  To sign message m_i:
    1. Sample random nonce  k_i  in [1, q-1]
    2. Compute  r_i  (public per-signature value derived from k_i)
    3. Compute  h_i = SHA-256(message_i)  interpreted as integer mod q
    4. Compute  s_i = k_i^{-1} * (h_i + x * r_i)  mod q
    5. Output signature  (r_i, s_i, h_i)

  The fundamental signing relation is:

        s_i * k_i  ≡  h_i + x * r_i   (mod q)

Side-Channel Leakage
---------------------
  Each 256-bit nonce k_i is decomposed as:

      k_i = hi_i * 2^176  +  mid_i * 2^80  +  lo_i

  where:
      hi_i  :  top 80 bits   (bits 176–255)  — UNKNOWN
      mid_i :  middle 96 bits (bits 80–175)   — LEAKED via side channel
      lo_i  :  bottom 80 bits (bits 0–79)     — UNKNOWN

  The leaked mid_i values are included in data.json alongside each signature.

Data Format (data.json)
-----------------------
  {
    "q": "<hex group order>",
    "nonce_layout": { ... },
    "num_signatures": 30,
    "signatures": [
      {
        "index": <int>,
        "r": "<hex>",
        "s": "<hex>",
        "h": "<hex>",
        "leaked_mid": "<hex>"
      },
      ...
    ]
  }

Objective
---------
  Recover the private key  x  from the partial nonce information and signatures.
  Write x as a lowercase hex string with 0x prefix to /app/secret_key.txt.
"""

# The secp256k1 curve order used in this scheme:
q = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
