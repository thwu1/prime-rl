/*
 * kem.c - RSA Key Encapsulation Mechanism (RSA-KEM)
 *
 * Implements RSASVE (RSA Secret Value Encapsulation) per NIST SP 800-56B
 * Rev. 2.  Generates a random secret and encrypts it with the recipient's
 * RSA public key; the recipient decrypts with their private key to recover
 * the shared secret.
 */

#include "secops.h"
#include <stdlib.h>
#include <string.h>

SECOPS_KEM_CTX *secops_kem_ctx_new(SECOPS_RSA *rsa, int mode)
{
    SECOPS_KEM_CTX *ctx;

    if (rsa == NULL)
        return NULL;

    ctx = calloc(1, sizeof(*ctx));
    if (ctx == NULL)
        return NULL;

    ctx->rsa = rsa;
    ctx->mode = mode;
    return ctx;
}

void secops_kem_ctx_free(SECOPS_KEM_CTX *ctx)
{
    if (ctx == NULL)
        return;
    /* The RSA key is not owned by the context; caller manages its lifetime */
    free(ctx);
}

/*
 * rsasve_generate - Encapsulate a new shared secret (internal).
 *
 * Algorithm (SP 800-56B, Section 7.2.1.2):
 *   Step 1: z = Random(nlen)
 *   Step 2: c = RSAEP((n, e), z)
 *   Step 3: Output (c, z)
 *
 * Returns 1 on success, 0 on failure.
 */
static int rsasve_generate(SECOPS_KEM_CTX *ctx,
                           unsigned char *out, size_t *outlen,
                           unsigned char *secret, size_t *secretlen)
{
    int ret;
    size_t nlen;

    if (ctx == NULL || ctx->rsa == NULL)
        return 0;

    nlen = (size_t)secops_rsa_size(ctx->rsa);
    if (nlen == 0 || nlen > SECOPS_MAX_RSA_SIZE)
        return 0;

    /* Step 1: Generate random secret value z */
    if (secops_rand_bytes(secret, (int)nlen) != 1)
        return 0;

    /* Step 2: Encrypt z with the recipient's public key */
    ret = secops_rsa_public_encrypt((int)nlen, secret, out, ctx->rsa,
                                    SECOPS_NO_PADDING);
    if (ret) {
        ret = 1;
        if (outlen != NULL)
            *outlen = nlen;
        if (secretlen != NULL)
            *secretlen = nlen;
    } else {
        secops_cleanse(secret, nlen);
    }
    return ret;
}

int secops_kem_encapsulate(SECOPS_KEM_CTX *ctx,
                           unsigned char *ct, size_t *ctlen,
                           unsigned char *secret, size_t *secretlen)
{
    if (ctx == NULL || ct == NULL || secret == NULL)
        return 0;
    if (ctx->mode != 0)
        return 0;

    return rsasve_generate(ctx, ct, ctlen, secret, secretlen);
}

/*
 * rsasve_recover - Recover shared secret from ciphertext (internal).
 *
 * Algorithm (SP 800-56B, Section 7.2.1.3):
 *   Step 1: z = RSADP((n, d), c)
 *   Step 2: Output z
 *
 * Returns 1 on success, 0 on failure.
 */
static int rsasve_recover(SECOPS_KEM_CTX *ctx,
                          unsigned char *secret, size_t *secretlen,
                          const unsigned char *ct, size_t ctlen)
{
    int ret;
    size_t nlen;

    if (ctx == NULL || ctx->rsa == NULL)
        return 0;

    nlen = (size_t)secops_rsa_size(ctx->rsa);
    if (nlen == 0 || nlen > SECOPS_MAX_RSA_SIZE)
        return 0;

    if (ctlen != nlen)
        return 0;

    /* Decrypt ciphertext to recover the shared secret */
    ret = secops_rsa_private_decrypt((int)ctlen, ct, secret, ctx->rsa,
                                     SECOPS_NO_PADDING);
    if (ret <= 0 || ret != (int)nlen) {
        secops_cleanse(secret, nlen);
        return 0;
    }

    if (secretlen != NULL)
        *secretlen = nlen;
    return 1;
}

int secops_kem_decapsulate(SECOPS_KEM_CTX *ctx,
                           unsigned char *secret, size_t *secretlen,
                           const unsigned char *ct, size_t ctlen)
{
    if (ctx == NULL || secret == NULL || ct == NULL)
        return 0;
    if (ctx->mode != 1)
        return 0;

    return rsasve_recover(ctx, secret, secretlen, ct, ctlen);
}
