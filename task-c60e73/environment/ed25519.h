#ifndef ED25519_H
#define ED25519_H


#include <stdint.h>
#include <stddef.h>

/*
 * Derive the 32-byte Ed25519 public key from a 32-byte secret key.
 */
void ed25519_derive_pubkey(const uint8_t secret[32], uint8_t pubkey[32]);

/*
 * Sign a message using a 32-byte secret key.
 * Produces a 64-byte deterministic signature.
 * msg may be NULL if msg_len is 0.
 */
void ed25519_sign(const uint8_t secret[32], const uint8_t *msg, size_t msg_len,
                  uint8_t signature[64]);

/*
 * Verify a 64-byte signature on a message using a 32-byte public key.
 * Returns 1 if valid, 0 if invalid.
 * Must reject signatures with S >= L (group order).
 * msg may be NULL if msg_len is 0.
 */
int ed25519_verify(const uint8_t pubkey[32], const uint8_t *msg, size_t msg_len,
                   const uint8_t signature[64]);

#endif /* ED25519_H */
