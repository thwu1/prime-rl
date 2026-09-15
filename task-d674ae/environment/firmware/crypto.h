/*
 * crypto.h — Cryptographic primitive declarations
 * Target: TM4C123GXL (ARM Cortex-M4F)
 */
#ifndef CRYPTO_H
#define CRYPTO_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint8_t round_keys[176];  /* AES-128 expanded key schedule */
    uint8_t iv[16];
} aes_ctx_t;

void     aes_init(aes_ctx_t *ctx, const uint8_t *key, const uint8_t *iv);
int      aes_decrypt_cbc(aes_ctx_t *ctx, const uint8_t *in, uint8_t *out, size_t len);
void     hmac_sha256(const uint8_t *key, size_t key_len,
                     const uint8_t *data, size_t data_len,
                     uint8_t *mac);
void     kdf_derive(const uint8_t *master, const uint8_t *salt,
                    uint8_t *derived, size_t derived_len);
int      uart_send(const uint8_t *data, size_t len);
int      uart_recv(uint8_t *data, size_t len);
uint32_t get_random_word(void);

#endif /* CRYPTO_H */
