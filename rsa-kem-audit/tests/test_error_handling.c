/*
 * Mock-based error-handling test for RSA-KEM.
 *
 * Uses the GNU ld --wrap mechanism to replace RSA_public_encrypt with a
 * stub that always returns -1 (failure).  After the fix, rsasve_generate
 * must detect this and return 0.
 *
 * Compile:
 *   gcc -I/app -DOPENSSL_SUPPRESS_DEPRECATED     \
 *       test_error_handling.c /app/rsa_kem.c      \
 *       -Wl,--wrap=RSA_public_encrypt -lcrypto    \
 *       -o test_error_handling
 *
 */

#ifndef OPENSSL_SUPPRESS_DEPRECATED
#define OPENSSL_SUPPRESS_DEPRECATED
#endif

#include <stdio.h>
#include <string.h>
#include <openssl/rsa.h>
#include <openssl/bn.h>
#include <openssl/rand.h>
#include <openssl/crypto.h>
#include "rsa_kem.h"

/* --wrap stub: every call to RSA_public_encrypt is redirected here. */
int __real_RSA_public_encrypt(int flen, const unsigned char *from,
                              unsigned char *to, RSA *rsa, int padding);

int __wrap_RSA_public_encrypt(int flen, const unsigned char *from,
                              unsigned char *to, RSA *rsa, int padding)
{
    (void)flen; (void)from; (void)to; (void)rsa; (void)padding;
    return -1;  /* simulate failure */
}

int main(void)
{
    int exit_code = 0;
    RSA *rsa;
    BIGNUM *e;
    RSA_KEM_CTX *ctx;
    int nlen, ret;
    unsigned char *out, *secret;
    size_t outlen = 0, secretlen = 0;

    rsa = RSA_new();
    e = BN_new();
    BN_set_word(e, RSA_F4);
    if (!RSA_generate_key_ex(rsa, 2048, e, NULL)) {
        fprintf(stderr, "Key generation failed\n");
        BN_free(e);
        RSA_free(rsa);
        return 1;
    }
    BN_free(e);

    ctx = rsa_kem_ctx_new(rsa, RSA_KEM_OP_ENCAPSULATE);
    if (ctx == NULL) {
        fprintf(stderr, "Context creation failed\n");
        RSA_free(rsa);
        return 1;
    }

    nlen = rsa_kem_get_size(ctx);
    out    = OPENSSL_malloc(nlen);
    secret = OPENSSL_malloc(nlen);

    ret = rsasve_generate(ctx, out, &outlen, secret, &secretlen);

    if (ret != 0) {
        printf("FAIL: rsasve_generate returned %d when RSA_public_encrypt "
               "returned -1 (expected 0)\n", ret);
        exit_code = 1;
    } else {
        printf("PASS: rsasve_generate correctly returned 0 on "
               "RSA_public_encrypt failure\n");
    }

    OPENSSL_free(out);
    OPENSSL_free(secret);
    rsa_kem_ctx_free(ctx);
    RSA_free(rsa);

    return exit_code;
}
