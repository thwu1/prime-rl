/*
 *
 * SHA-256 implementation header.
 */
#ifndef SHA256_H
#define SHA256_H

#include <stdint.h>
#include <stddef.h>

typedef struct {
    uint32_t state[8];
    uint64_t bitcount;
    uint8_t  buffer[64];
} sha256_ctx;

void sha256_init(sha256_ctx *ctx);
void sha256_update(sha256_ctx *ctx, const uint8_t *data, size_t len);
void sha256_final(sha256_ctx *ctx, uint8_t digest[32]);

/* Convenience: hash data in one call */
void sha256_hash(const uint8_t *data, size_t len, uint8_t digest[32]);

#endif /* SHA256_H */
