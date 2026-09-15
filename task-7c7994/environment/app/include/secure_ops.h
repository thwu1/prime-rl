#ifndef SECURE_OPS_H
#define SECURE_OPS_H

#include <stdint.h>
#include <stddef.h>

/* Encrypt data using the provided 16-byte key */
int secure_encrypt(const uint8_t *key, const uint8_t *plaintext,
                   uint8_t *ciphertext, size_t len);

/* Decrypt data using the provided 16-byte key */
int secure_decrypt(const uint8_t *key, const uint8_t *ciphertext,
                   uint8_t *plaintext, size_t len);

/* Verify an authentication token against a stored hash.
 * Returns 1 if valid, 0 if invalid. */
int verify_auth_token(const uint8_t *token, size_t token_len,
                      const uint8_t *stored_hash);

/* Generate a public/private keypair from a 32-byte seed */
int generate_keypair(const uint8_t *seed, uint8_t *pub_key, uint8_t *priv_key);

/* Compute HMAC signature over a message using the provided key */
int hmac_sign(const uint8_t *key, size_t key_len,
              const uint8_t *msg, size_t msg_len,
              uint8_t *signature);

/* Verify HMAC on subscription data.
 * Returns 1 if valid, 0 if invalid. */
int process_subscription(const uint8_t *key,
                         const uint8_t *data, size_t data_len,
                         const uint8_t *provided_hmac);

/* Derive a session key from a master key and nonce */
int derive_session_key(const uint8_t *master_key,
                       const uint8_t *nonce,
                       uint8_t *session_key);

/* Secure memory wiping using volatile pointer (reference implementation) */
void safe_wipe_example(void *buf, size_t len);

/* Sign a message using explicit_bzero for key wiping (reference implementation) */
int already_safe_sign(const uint8_t *key, const uint8_t *msg,
                      size_t msg_len, uint8_t *signature);

#endif
