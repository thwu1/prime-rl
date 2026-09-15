Input data at `/data/vectors.json` contains QUIC connection parameters (Destination Connection ID, unprotected packet headers, plaintext payloads, and related protocol inputs) for both QUIC v1 and QUIC v2. The output schema is at `/data/output_schema.json`.

Produce `/app/output/results.json` conforming to that schema. Every output value must be a lowercase hex string matching the corresponding reference test vector from the QUIC-TLS specifications (RFC 9001 for v1, RFC 9369 for v2).

The output must include, for each protocol version: all intermediate key material (initial secret, client/server initial secrets, encryption keys, IVs, and header protection keys), fully protected Client Initial and Server Initial packets, a complete Retry packet with its integrity tag, and a protected short header packet using the ChaCha20-Poly1305 cipher suite.

This requires implementing: HKDF-Extract and HKDF-Expand-Label (TLS 1.3 style), AEAD_AES_128_GCM encryption, AES-ECB-based header protection masking, Retry integrity tag computation, and ChaCha20-Poly1305 AEAD with ChaCha20-based header protection. Each version uses different salts, labels, and fixed constants.

The relevant specifications are freely available from the IETF at https://www.rfc-editor.org/.