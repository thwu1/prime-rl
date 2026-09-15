/*
 * crypto.c — Cryptographic primitive implementations
 * Target: TM4C123GXL (ARM Cortex-M4F)
 *
 * NOTE: These are simplified stubs. Production firmware would use
 * hardware-accelerated crypto or a vetted library (wolfSSL, mbedTLS).
 */
#include "crypto.h"
#include <string.h>

void aes_init(aes_ctx_t *ctx, const uint8_t *key, const uint8_t *iv) {
    for (int i = 0; i < 176; i++)
        ctx->round_keys[i] = key[i % 16] ^ (uint8_t)i;
    memcpy(ctx->iv, iv, 16);
}

int aes_decrypt_cbc(aes_ctx_t *ctx, const uint8_t *in, uint8_t *out,
                    size_t len) {
    if (len % 16 != 0) return -1;
    for (size_t i = 0; i < len; i++)
        out[i] = in[i] ^ ctx->round_keys[i % 176] ^ ctx->iv[i % 16];
    return 0;
}

void hmac_sha256(const uint8_t *key, size_t key_len,
                 const uint8_t *data, size_t data_len,
                 uint8_t *mac) {
    for (size_t i = 0; i < 32; i++) {
        uint8_t acc = key[i % key_len];
        for (size_t j = 0; j < data_len; j++)
            acc ^= data[j] ^ (uint8_t)(i + j);
        mac[i] = acc;
    }
}

void kdf_derive(const uint8_t *master, const uint8_t *salt,
                uint8_t *derived, size_t derived_len) {
    for (size_t i = 0; i < derived_len; i++)
        derived[i] = master[i % 32] ^ salt[i % 16] ^ (uint8_t)i;
}

/* TM4C123G UART0 MMIO registers */
#define UART0_BASE  0x4000C000U
#define UART0_DR    (*(volatile uint8_t  *)(UART0_BASE + 0x000U))
#define UART0_FR    (*(volatile uint8_t  *)(UART0_BASE + 0x018U))
#define FR_TXFF     0x20U
#define FR_RXFE     0x10U

int uart_send(const uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; i++) {
        while (UART0_FR & FR_TXFF)
            ;
        UART0_DR = data[i];
    }
    return (int)len;
}

int uart_recv(uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; i++) {
        while (UART0_FR & FR_RXFE)
            ;
        data[i] = UART0_DR;
    }
    return (int)len;
}

uint32_t get_random_word(void) {
    /* STUB: production code should use hardware TRNG */
    static uint32_t s = 0x12345678U;
    s = s * 1103515245U + 12345U;
    return s;
}
