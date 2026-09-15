/*
 * RSA-KEM (Key Encapsulation Mechanism) - RSASVE
 * Implementation based on NIST SP 800-56B Rev 2
 *
 * Provides RSASVE.Generate (encapsulation) and RSASVE.Recover (decapsulation)
 * operations for RSA-based key transport.
 */

#include "rsa_kem.h"
#include <string.h>

RSA_KEM_CTX *rsa_kem_ctx_new(RSA *rsa, int operation)
{
    RSA_KEM_CTX *ctx;

    if (rsa == NULL)
        return NULL;

    ctx = OPENSSL_zalloc(sizeof(*ctx));
    if (ctx == NULL)
        return NULL;

    ctx->rsa = rsa;
    RSA_up_ref(rsa);
    ctx->op = operation;

    return ctx;
}

void rsa_kem_ctx_free(RSA_KEM_CTX *ctx)
{
    if (ctx == NULL)
        return;
    RSA_free(ctx->rsa);
    OPENSSL_free(ctx);
}

int rsa_kem_get_size(RSA_KEM_CTX *ctx)
{
    if (ctx == NULL || ctx->rsa == NULL)
        return -1;
    return RSA_size(ctx->rsa);
}

/**
 * RSASVE Generate (Encapsulation)
 * NIST SP 800-56B Rev 2, Section 7.2.1.2
 *
 * Steps:
 *   1. z = RandomInteger(0, n-1)
 *   2. secret = I2OSP(z, nLen)
 *   3. c = RSAEP((n,e), z) = z^e mod n
 *   4. out = I2OSP(c, nLen)
 *
 * Returns 1 on success, 0 on failure.
 */
int rsasve_generate(RSA_KEM_CTX *ctx,
                    unsigned char *out, size_t *outlen,
                    unsigned char *secret, size_t *secretlen)
{
    int ret;
    size_t nlen;
    RSA *rsa;

    if (ctx == NULL || ctx->rsa == NULL)
        return 0;

    rsa = ctx->rsa;
    nlen = RSA_size(rsa);

    /* Allow callers to query output sizes without performing operation */
    if (out == NULL) {
        if (outlen != NULL)
            *outlen = nlen;
        if (secretlen != NULL)
            *secretlen = nlen;
        return 1;
    }

    /* Step(1): Generate a random byte string z of nlen bytes */
    if (RAND_priv_bytes(secret, nlen) <= 0)
        return 0;

    /* Step(3): out = RSAEP((n,e), z) */
    ret = RSA_public_encrypt((int)nlen, secret, out, rsa,
        RSA_NO_PADDING);
    if (ret) {
        ret = 1;
        if (outlen != NULL)
            *outlen = nlen;
        if (secretlen != NULL)
            *secretlen = nlen;
    } else {
        OPENSSL_cleanse(secret, nlen);
    }
    return ret;
}

/**
 * RSASVE Recover (Decapsulation)
 * NIST SP 800-56B Rev 2, Section 7.2.1.3
 *
 * Steps:
 *   1. z = RSADP((n,d), c) = c^d mod n
 *   2. secret = I2OSP(z, nLen)
 *
 * Returns 1 on success, 0 on failure.
 */
int rsasve_recover(RSA_KEM_CTX *ctx,
                   unsigned char *secret, size_t *secretlen,
                   const unsigned char *in, size_t inlen)
{
    int ret;
    size_t nlen;
    RSA *rsa;

    if (ctx == NULL || ctx->rsa == NULL)
        return 0;

    rsa = ctx->rsa;
    nlen = RSA_size(rsa);

    /* Allow callers to query output sizes without performing operation */
    if (secret == NULL) {
        if (secretlen != NULL)
            *secretlen = nlen;
        return 1;
    }

    ret = RSA_private_decrypt((int)inlen, in, secret, rsa,
        RSA_NO_PADDING);
    if (ret <= 0)
        return 0;

    if (secretlen != NULL)
        *secretlen = nlen;

    return 1;
}
