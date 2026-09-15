#ifndef CRYPTO_IMPL_H
#define CRYPTO_IMPL_H

#include <stdint.h>
#include <stddef.h>

/* Key expansion: expands a 16-byte key into expanded_len bytes of round keys */
void key_expand(const uint8_t *key, uint8_t *expanded, size_t expanded_len);

/* Block cipher encryption */
void block_encrypt(const uint8_t *key_schedule, size_t ks_len,
                   const uint8_t *input, uint8_t *output, size_t len);

/* Block cipher decryption */
void block_decrypt(const uint8_t *key_schedule, size_t ks_len,
                   const uint8_t *input, uint8_t *output, size_t len);

/* Hash function: produces hash_len bytes of hash from input data */
void hash_compute(const uint8_t *data, size_t data_len,
                  uint8_t *hash, size_t hash_len);

/* HMAC computation */
void hmac_compute(const uint8_t *key, size_t key_len,
                  const uint8_t *msg, size_t msg_len,
                  uint8_t *mac, size_t mac_len);

/* Key derivation function */
void kdf_derive(const uint8_t *master, size_t master_len,
                const uint8_t *salt, size_t salt_len,
                uint8_t *derived, size_t derived_len);

#endif
