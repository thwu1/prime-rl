/*
 * test_security.c - Regression tests for identified vulnerabilities.
 *
 * Tests that:
 * 1. KEM encapsulate fails properly when RSA encrypt returns -1.
 * 2. KDF rejects invalid salt types (non-OCTET-STRING).
 * 3. KDF rejects NULL keylength.
 * 4. KDF rejects out-of-range keylength values.
 */

#include <stdio.h>
#include <string.h>
#include "secops.h"

static int test_kem_encrypt_failure(void)
{
    unsigned char fake_n[64];
    unsigned char ct[64], secret[64];
    size_t ctlen = 0, secretlen = 0;
    SECOPS_RSA *rsa;
    SECOPS_KEM_CTX *ctx;
    int ret, i, nlen;

    memset(fake_n, 0x42, sizeof(fake_n));
    rsa = secops_rsa_new();
    secops_rsa_set_key(rsa, fake_n, 64, NULL, 0, NULL, 0);

    ctx = secops_kem_ctx_new(rsa, 0);
    ret = secops_kem_encapsulate(ctx, ct, &ctlen, secret, &secretlen);

    if (ret != 0) {
        printf("  FAIL [kem_encrypt_failure]: got %d, expected 0\n", ret);
        secops_kem_ctx_free(ctx);
        secops_rsa_free(rsa);
        return 1;
    }

    nlen = secops_rsa_size(rsa);
    for (i = 0; i < nlen; i++) {
        if (secret[i] != 0) {
            printf("  FAIL [kem_cleanse]: secret[%d] not zeroed\n", i);
            secops_kem_ctx_free(ctx);
            secops_rsa_free(rsa);
            return 1;
        }
    }

    secops_kem_ctx_free(ctx);
    secops_rsa_free(rsa);
    printf("  KEM encrypt failure handling: PASS\n");
    return 0;
}

static int test_kdf_invalid_salt(void)
{
    SECOPS_ASN1_TYPE salt;
    SECOPS_ASN1_INTEGER keylength, iterations;
    SECOPS_PBKDF2_PARAM param;
    unsigned char key[128];
    int keylen_out = 0;

    memset(&salt, 0, sizeof(salt));
    salt.type = V_SECOPS_ASN1_INTEGER;
    salt.value.integer_value = 42;

    keylength.value = 32;
    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = &keylength;
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("  FAIL [kdf_invalid_salt]: got %d, expected 0\n", ret);
        return 1;
    }
    printf("  KDF invalid salt rejection: PASS\n");
    return 0;
}

static int test_kdf_null_keylength(void)
{
    unsigned char salt_data[] = "valid_salt";
    SECOPS_ASN1_TYPE salt;
    SECOPS_ASN1_INTEGER iterations;
    SECOPS_PBKDF2_PARAM param;
    unsigned char key[128];
    int keylen_out = 0;

    memset(&salt, 0, sizeof(salt));
    salt.type = V_SECOPS_ASN1_OCTET_STRING;
    salt.value.octet_string.data = salt_data;
    salt.value.octet_string.length = 10;

    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = NULL;
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("  FAIL [kdf_null_keylength]: got %d, expected 0\n", ret);
        return 1;
    }
    printf("  KDF null keylength rejection: PASS\n");
    return 0;
}

static int test_kdf_extreme_keylength(void)
{
    unsigned char salt_data[] = "valid_salt";
    SECOPS_ASN1_TYPE salt;
    SECOPS_ASN1_INTEGER keylength, iterations;
    SECOPS_PBKDF2_PARAM param;
    unsigned char key[256];
    int keylen_out = 0;

    memset(&salt, 0, sizeof(salt));
    salt.type = V_SECOPS_ASN1_OCTET_STRING;
    salt.value.octet_string.data = salt_data;
    salt.value.octet_string.length = 10;

    keylength.value = SECOPS_MAX_MD_SIZE + 100;
    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = &keylength;
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("  FAIL [kdf_extreme_keylength]: got %d, expected 0\n", ret);
        return 1;
    }
    printf("  KDF extreme keylength rejection: PASS\n");
    return 0;
}

int main(void)
{
    int failures = 0;

    printf("Security regression tests\n");
    printf("=========================\n");

    failures += test_kem_encrypt_failure();
    failures += test_kdf_invalid_salt();
    failures += test_kdf_null_keylength();
    failures += test_kdf_extreme_keylength();

    printf("=========================\n");
    if (failures == 0) {
        printf("All security regression tests passed.\n");
        return 0;
    }
    printf("%d test(s) FAILED.\n", failures);
    return 1;
}
