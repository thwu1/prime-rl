/*
 * Basic round-trip test for RSA-KEM.
 *
 * Generates a key pair, encapsulates, decapsulates, and verifies
 * the recovered secret matches the original.
 */

#include "rsa_kem.h"
#include "util.h"
#include <stdio.h>
#include <string.h>

#define TEST_KEY_BITS 2048
#define MAX_ATTEMPTS  10

static int test_size_query(void)
{
    int result = 0;
    RSA *rsa = NULL;
    RSA_KEM_CTX *ctx = NULL;
    size_t outlen, secretlen;

    printf("Test: size query ... ");

    rsa = generate_rsa_keypair(TEST_KEY_BITS);
    if (rsa == NULL)
        goto done;

    ctx = rsa_kem_ctx_new(rsa, RSA_KEM_OP_ENCAPSULATE);
    if (ctx == NULL)
        goto done;

    if (rsasve_generate(ctx, NULL, &outlen, NULL, &secretlen) != 1)
        goto done;

    if ((int)outlen != RSA_size(rsa) || (int)secretlen != RSA_size(rsa))
        goto done;

    result = 1;

done:
    rsa_kem_ctx_free(ctx);
    RSA_free(rsa);
    printf("%s\n", result ? "ok" : "FAILED");
    return result;
}

static int test_encap_decap(void)
{
    int result = 0;
    RSA *rsa = NULL;
    RSA_KEM_CTX *enc_ctx = NULL, *dec_ctx = NULL;
    unsigned char *ct = NULL, *secret = NULL, *recovered = NULL;
    size_t ct_len, secret_len, recovered_len;
    int nlen, attempt;

    printf("Test: encapsulate / decapsulate round-trip ... ");

    rsa = generate_rsa_keypair(TEST_KEY_BITS);
    if (rsa == NULL)
        goto done;

    enc_ctx = rsa_kem_ctx_new(rsa, RSA_KEM_OP_ENCAPSULATE);
    dec_ctx = rsa_kem_ctx_new(rsa, RSA_KEM_OP_DECAPSULATE);
    if (enc_ctx == NULL || dec_ctx == NULL)
        goto done;

    nlen = rsa_kem_get_size(enc_ctx);
    ct       = OPENSSL_malloc(nlen);
    secret   = OPENSSL_malloc(nlen);
    recovered = OPENSSL_malloc(nlen);
    if (ct == NULL || secret == NULL || recovered == NULL)
        goto done;

    /*
     * The random z may exceed the modulus, causing RSA_public_encrypt
     * to fail.  Retry up to MAX_ATTEMPTS times.
     */
    for (attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        if (rsasve_generate(enc_ctx, ct, &ct_len,
                            secret, &secret_len) == 1)
            break;
    }
    if (attempt == MAX_ATTEMPTS)
        goto done;

    if (rsasve_recover(dec_ctx, recovered, &recovered_len,
                       ct, ct_len) != 1)
        goto done;

    if (secret_len != recovered_len)
        goto done;
    if (memcmp(secret, recovered, secret_len) != 0)
        goto done;

    result = 1;

done:
    OPENSSL_free(ct);
    OPENSSL_free(secret);
    OPENSSL_free(recovered);
    rsa_kem_ctx_free(enc_ctx);
    rsa_kem_ctx_free(dec_ctx);
    RSA_free(rsa);
    printf("%s\n", result ? "ok" : "FAILED");
    return result;
}

int main(void)
{
    int pass = 1;

    if (!test_size_query())   pass = 0;
    if (!test_encap_decap())  pass = 0;

    printf("\n%s\n", pass ? "PASS: All tests passed" : "FAIL: Some tests failed");
    return pass ? 0 : 1;
}
