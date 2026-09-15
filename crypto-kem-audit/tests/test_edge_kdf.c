/*
 * test_edge_kdf.c - Edge-case tests for KDF parameter validation.
 *
 * Verifies that secops_pbmac1_derive correctly rejects:
 *   1. Salt with wrong ASN.1 type tag (not OCTET STRING)
 *   2. NULL keylength pointer
 *   3. Excessive keylength (> SECOPS_MAX_MD_SIZE)
 *   4. Negative keylength
 *
 */

#include <stdio.h>
#include <string.h>
#include "secops.h"

static int test_invalid_salt_type(void)
{
    SECOPS_ASN1_TYPE salt;
    SECOPS_ASN1_INTEGER keylength, iterations;
    SECOPS_PBKDF2_PARAM param;
    unsigned char key[128];
    int keylen_out = 0;

    memset(&salt, 0, sizeof(salt));
    salt.type = V_SECOPS_ASN1_INTEGER;       /* wrong type! */
    salt.value.integer_value = 42;

    keylength.value = 32;
    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = &keylength;
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("FAIL [invalid_salt_type]: expected 0, got %d\n", ret);
        return 1;
    }
    return 0;
}

static int test_null_keylength(void)
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
    param.keylength = NULL;                 /* missing keylength */
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("FAIL [null_keylength]: expected 0, got %d\n", ret);
        return 1;
    }
    return 0;
}

static int test_excessive_keylength(void)
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

    keylength.value = SECOPS_MAX_MD_SIZE + 1;  /* too large */
    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = &keylength;
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("FAIL [excessive_keylength]: expected 0, got %d\n", ret);
        return 1;
    }
    return 0;
}

static int test_negative_keylength(void)
{
    unsigned char salt_data[] = "valid_salt";
    SECOPS_ASN1_TYPE salt;
    SECOPS_ASN1_INTEGER keylength, iterations;
    SECOPS_PBKDF2_PARAM param;
    unsigned char key[128];
    int keylen_out = 0;

    memset(&salt, 0, sizeof(salt));
    salt.type = V_SECOPS_ASN1_OCTET_STRING;
    salt.value.octet_string.data = salt_data;
    salt.value.octet_string.length = 10;

    keylength.value = -1;                   /* negative */
    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = &keylength;
    param.iterations = &iterations;

    int ret = secops_pbmac1_derive(&param, "password", 8, key, &keylen_out);
    if (ret != 0) {
        printf("FAIL [negative_keylength]: expected 0, got %d\n", ret);
        return 1;
    }
    return 0;
}

int main(void)
{
    int failures = 0;

    failures += test_invalid_salt_type();
    failures += test_null_keylength();
    failures += test_excessive_keylength();
    failures += test_negative_keylength();

    if (failures == 0) {
        printf("PASS: all KDF parameter validation checks passed\n");
        return 0;
    }

    printf("%d KDF edge-case test(s) FAILED\n", failures);
    return 1;
}
