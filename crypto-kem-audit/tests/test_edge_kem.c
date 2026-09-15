/*
 * test_edge_kem.c - Edge-case tests for KEM return-value handling.
 *
 * Verifies that secops_kem_encapsulate correctly reports failure
 * and cleanses secret material when the underlying RSA encrypt fails.
 *
 */

#include <stdio.h>
#include <string.h>
#include "secops.h"

int main(void)
{
    unsigned char fake_n[64];
    unsigned char ct[64], secret[64];
    size_t ctlen = 0, secretlen = 0;
    SECOPS_RSA *rsa;
    SECOPS_KEM_CTX *ctx;
    int ret, i, nlen;

    /*
     * Create an RSA key with a modulus but NO public exponent.
     * secops_rsa_size() will return 64, but secops_rsa_public_encrypt()
     * will return -1 because the public key flag is not set.
     */
    memset(fake_n, 0x42, sizeof(fake_n));
    rsa = secops_rsa_new();
    if (rsa == NULL) {
        printf("FAIL: secops_rsa_new returned NULL\n");
        return 1;
    }
    /* Set modulus only; pass NULL for public and private exponents */
    secops_rsa_set_key(rsa, fake_n, 64, NULL, 0, NULL, 0);

    ctx = secops_kem_ctx_new(rsa, 0);
    if (ctx == NULL) {
        printf("FAIL: secops_kem_ctx_new returned NULL\n");
        secops_rsa_free(rsa);
        return 1;
    }

    /* Attempt encapsulation — must fail */
    ret = secops_kem_encapsulate(ctx, ct, &ctlen, secret, &secretlen);
    if (ret != 0) {
        printf("FAIL: encapsulate should return 0 when encrypt fails (got %d)\n", ret);
        secops_kem_ctx_free(ctx);
        secops_rsa_free(rsa);
        return 1;
    }

    /* Verify secret buffer was cleansed */
    nlen = secops_rsa_size(rsa);
    for (i = 0; i < nlen; i++) {
        if (secret[i] != 0) {
            printf("FAIL: secret[%d] = 0x%02x, expected 0x00 (not cleansed)\n",
                   i, secret[i]);
            secops_kem_ctx_free(ctx);
            secops_rsa_free(rsa);
            return 1;
        }
    }

    secops_kem_ctx_free(ctx);
    secops_rsa_free(rsa);

    printf("PASS: KEM correctly rejects encrypt failure and cleanses secret\n");
    return 0;
}
