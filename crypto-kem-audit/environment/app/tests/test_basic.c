/*
 * test_basic.c - Basic functionality tests for libsecops
 *
 * Validates correct operation of RSA, KEM, and KDF under normal conditions.
 */

#include <stdio.h>
#include <string.h>
#include "secops.h"

static int test_rsa_roundtrip(void)
{
    unsigned char modulus[32];
    unsigned char pub_exp[3] = {0x01, 0x00, 0x01};
    unsigned char priv_exp[32];
    unsigned char plain[32], cipher[32], recovered[32];
    SECOPS_RSA *rsa;
    int ret, i;

    for (i = 0; i < 32; i++) {
        modulus[i] = (unsigned char)(0x42 + i);
        priv_exp[i] = (unsigned char)(0x23 + i);
        plain[i] = (unsigned char)(0x10 + i);
    }

    rsa = secops_rsa_new();
    if (rsa == NULL) return 1;

    if (secops_rsa_set_key(rsa, modulus, 32, pub_exp, 3, priv_exp, 32) != 1) {
        printf("  RSA set_key failed\n");
        return 1;
    }

    if (secops_rsa_size(rsa) != 32) {
        printf("  RSA size mismatch\n");
        return 1;
    }

    ret = secops_rsa_public_encrypt(32, plain, cipher, rsa, SECOPS_NO_PADDING);
    if (ret != 32) {
        printf("  RSA encrypt failed: %d\n", ret);
        return 1;
    }

    ret = secops_rsa_private_decrypt(32, cipher, recovered, rsa, SECOPS_NO_PADDING);
    if (ret != 32) {
        printf("  RSA decrypt failed: %d\n", ret);
        return 1;
    }

    if (memcmp(plain, recovered, 32) != 0) {
        printf("  RSA roundtrip data mismatch\n");
        return 1;
    }

    secops_rsa_free(rsa);
    printf("  RSA roundtrip: PASS\n");
    return 0;
}

static int test_kem_roundtrip(void)
{
    unsigned char modulus[32], pub_exp[3], priv_exp[32];
    unsigned char ct[32], secret_enc[32], secret_dec[32];
    size_t ctlen = 0, enc_slen = 0, dec_slen = 0;
    SECOPS_RSA *rsa;
    SECOPS_KEM_CTX *enc_ctx, *dec_ctx;
    int ret, i;

    for (i = 0; i < 32; i++) {
        modulus[i] = (unsigned char)(0x42 + i);
        priv_exp[i] = (unsigned char)(0x23 + i);
    }
    pub_exp[0] = 0x01; pub_exp[1] = 0x00; pub_exp[2] = 0x01;

    rsa = secops_rsa_new();
    if (rsa == NULL) return 1;

    if (secops_rsa_set_key(rsa, modulus, 32, pub_exp, 3, priv_exp, 32) != 1)
        return 1;

    /* Encapsulate */
    enc_ctx = secops_kem_ctx_new(rsa, 0);
    if (enc_ctx == NULL) return 1;

    ret = secops_kem_encapsulate(enc_ctx, ct, &ctlen, secret_enc, &enc_slen);
    if (ret != 1) {
        printf("  KEM encapsulate failed\n");
        return 1;
    }
    if (ctlen != 32 || enc_slen != 32) {
        printf("  KEM encapsulate size mismatch\n");
        return 1;
    }

    /* Decapsulate */
    dec_ctx = secops_kem_ctx_new(rsa, 1);
    if (dec_ctx == NULL) return 1;

    ret = secops_kem_decapsulate(dec_ctx, secret_dec, &dec_slen, ct, ctlen);
    if (ret != 1) {
        printf("  KEM decapsulate failed\n");
        return 1;
    }
    if (dec_slen != 32) {
        printf("  KEM decapsulate size mismatch\n");
        return 1;
    }

    if (memcmp(secret_enc, secret_dec, 32) != 0) {
        printf("  KEM secrets do not match\n");
        return 1;
    }

    secops_kem_ctx_free(enc_ctx);
    secops_kem_ctx_free(dec_ctx);
    secops_rsa_free(rsa);
    printf("  KEM roundtrip: PASS\n");
    return 0;
}

static int test_kdf_derive(void)
{
    unsigned char salt_bytes[] = "test_salt_value";
    SECOPS_ASN1_TYPE salt;
    SECOPS_ASN1_INTEGER keylength, iterations;
    SECOPS_PBKDF2_PARAM param;
    unsigned char key1[64], key2[64];
    int kl1 = 0, kl2 = 0;
    int ret;

    memset(&salt, 0, sizeof(salt));
    salt.type = V_SECOPS_ASN1_OCTET_STRING;
    salt.value.octet_string.data = salt_bytes;
    salt.value.octet_string.length = 15;

    keylength.value = 32;
    iterations.value = 1000;

    memset(&param, 0, sizeof(param));
    param.salt = &salt;
    param.keylength = &keylength;
    param.iterations = &iterations;
    param.prf_nid = 0;

    ret = secops_pbmac1_derive(&param, "password", 8, key1, &kl1);
    if (ret != 1) {
        printf("  KDF derive failed\n");
        return 1;
    }
    if (kl1 != 32) {
        printf("  KDF keylength mismatch: %d\n", kl1);
        return 1;
    }

    /* Derive again with same params - should produce identical output */
    ret = secops_pbmac1_derive(&param, "password", 8, key2, &kl2);
    if (ret != 1 || kl2 != 32) {
        printf("  KDF second derive failed\n");
        return 1;
    }

    if (memcmp(key1, key2, 32) != 0) {
        printf("  KDF determinism check failed\n");
        return 1;
    }

    printf("  KDF derive: PASS\n");
    return 0;
}

static int test_util_cleanse(void)
{
    unsigned char buf[16];
    int i;

    memset(buf, 0xAA, 16);
    secops_cleanse(buf, 16);

    for (i = 0; i < 16; i++) {
        if (buf[i] != 0) {
            printf("  cleanse failed at byte %d\n", i);
            return 1;
        }
    }

    printf("  Utility cleanse: PASS\n");
    return 0;
}

int main(void)
{
    int failures = 0;

    printf("libsecops basic test suite\n");
    printf("==========================\n");

    failures += test_rsa_roundtrip();
    failures += test_kem_roundtrip();
    failures += test_kdf_derive();
    failures += test_util_cleanse();

    printf("==========================\n");
    if (failures == 0) {
        printf("All tests passed.\n");
        return 0;
    }
    printf("%d test(s) FAILED.\n", failures);
    return 1;
}
