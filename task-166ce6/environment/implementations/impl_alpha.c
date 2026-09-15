/*
 * impl_alpha.c — Poly1305 MAC implementation (variant alpha).
 * Uses GMP for arbitrary-precision arithmetic over GF(2^130-5).
 */
#include <stdint.h>
#include <string.h>
#include <gmp.h>

void poly1305_mac(const uint8_t *msg, size_t msg_len,
                  const uint8_t *key_r, const uint8_t *key_s,
                  uint8_t *tag_out) {
    mpz_t p, acc, r, s, c, mask;

    /* p = 2^130 - 5 */
    mpz_init(p);
    mpz_set_ui(p, 1);
    mpz_mul_2exp(p, p, 130);
    mpz_sub_ui(p, p, 5);

    mpz_init_set_ui(acc, 0);

    /* Import r from key bytes (little-endian) */
    mpz_init(r);
    mpz_import(r, 16, -1, 1, 0, 0, key_r);

    mpz_init(c);

    for (size_t i = 0; i < msg_len; i += 16) {
        size_t chunk_len = msg_len - i;
        if (chunk_len > 16) chunk_len = 16;

        /* Encode chunk as little-endian integer */
        mpz_set_ui(c, 0);
        mpz_import(c, chunk_len, -1, 1, 0, 0, msg + i);

        /* Add sentinel bit at position 8 * chunk_len */
        mpz_setbit(c, 8 * chunk_len);

        /* acc = (acc + c) * r mod p */
        mpz_add(acc, acc, c);
        mpz_mul(acc, acc, r);
        mpz_mod(acc, acc, p);
    }

    /* Add s (little-endian import) */
    mpz_init(s);
    mpz_import(s, 16, -1, 1, 0, 0, key_s);
    mpz_add(acc, acc, s);

    /* Reduce mod 2^128 */
    mpz_init(mask);
    mpz_set_ui(mask, 1);
    mpz_mul_2exp(mask, mask, 128);
    mpz_mod(acc, acc, mask);

    /* Export tag as 16 bytes little-endian */
    memset(tag_out, 0, 16);
    mpz_export(tag_out, NULL, -1, 1, 0, 0, acc);

    mpz_clear(p); mpz_clear(acc); mpz_clear(r);
    mpz_clear(s); mpz_clear(c); mpz_clear(mask);
}
