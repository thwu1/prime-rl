You have obtained complete key material (static keys, ephemeral keys, PSKs) for several intercepted Noise Protocol Framework sessions. Implement a Noise Protocol handshake engine that can process these sessions end-to-end: execute the handshake state machine to derive transport keys, then decrypt all transport-phase messages.

`/app/sessions.json` contains an array of sessions. Each session specifies a `protocol_name` (e.g. `Noise_XX_25519_ChaChaPoly_BLAKE2s`), all private keys for both parties, the prologue, `num_handshake_messages`, and hex-encoded ciphertexts for every message (handshake + transport). Static/ephemeral fields contain raw 32-byte Curve25519 private keys; `remote_static` fields contain public keys. PSK sessions include `init_psks`/`resp_psks` arrays.

The sessions exercise five different handshake patterns (XX, IK, NNpsk0, KK, NK), two AEAD ciphers (ChaChaPoly, AESGCM), and three hash functions (SHA256, BLAKE2s, BLAKE2b — note BLAKE2b has HASHLEN=64, requiring key truncation in MixKey and Split). The Noise Protocol Framework specification is at `/app/noise_spec_reference.md`.

Write `/app/results.json` as a JSON array (one object per session, same order) where each object has:
- `handshake_hash`: hex string of the handshake hash after the final handshake message
- `transport_payloads`: array of hex strings — the decrypted plaintext of each transport message (messages beyond `num_handshake_messages`), in order

After `Split()`, `c1` encrypts initiator-to-responder and `c2` encrypts responder-to-initiator. Even-indexed messages are from the initiator; odd-indexed are from the responder. Transport encryption/decryption uses `EncryptWithAd`/`DecryptWithAd` with empty associated data.