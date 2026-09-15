/*
 * Utility functions for RSA key management and diagnostics.
 */

#include "util.h"
#include <stdio.h>
#include <string.h>

RSA *generate_rsa_keypair(int bits)
{
    RSA *rsa = NULL;
    BIGNUM *e = NULL;

    rsa = RSA_new();
    if (rsa == NULL)
        goto err;

    e = BN_new();
    if (e == NULL)
        goto err;

    if (!BN_set_word(e, RSA_F4))
        goto err;

    if (!RSA_generate_key_ex(rsa, bits, e, NULL))
        goto err;

    BN_free(e);
    return rsa;

err:
    RSA_free(rsa);
    BN_free(e);
    return NULL;
}

void print_hex(const char *label, const unsigned char *data, size_t len)
{
    size_t i;

    printf("%s (%zu bytes): ", label, len);
    for (i = 0; i < len && i < 32; i++)
        printf("%02x", data[i]);
    if (len > 32)
        printf("...");
    printf("\n");
}

int save_rsa_keypair(RSA *rsa, const char *pubfile, const char *privfile)
{
    FILE *fp;

    fp = fopen(pubfile, "w");
    if (fp == NULL)
        return 0;
    if (!PEM_write_RSAPublicKey(fp, rsa)) {
        fclose(fp);
        return 0;
    }
    fclose(fp);

    fp = fopen(privfile, "w");
    if (fp == NULL)
        return 0;
    if (!PEM_write_RSAPrivateKey(fp, rsa, NULL, NULL, 0, NULL, NULL)) {
        fclose(fp);
        return 0;
    }
    fclose(fp);

    return 1;
}

RSA *load_rsa_pubkey(const char *filename)
{
    FILE *fp;
    RSA *rsa;

    fp = fopen(filename, "r");
    if (fp == NULL)
        return NULL;

    rsa = PEM_read_RSAPublicKey(fp, NULL, NULL, NULL);
    fclose(fp);
    return rsa;
}

RSA *load_rsa_privkey(const char *filename)
{
    FILE *fp;
    RSA *rsa;

    fp = fopen(filename, "r");
    if (fp == NULL)
        return NULL;

    rsa = PEM_read_RSAPrivateKey(fp, NULL, NULL, NULL);
    fclose(fp);
    return rsa;
}

void print_openssl_errors(void)
{
    unsigned long err;

    while ((err = ERR_get_error()) != 0) {
        char buf[256];
        ERR_error_string_n(err, buf, sizeof(buf));
        fprintf(stderr, "OpenSSL error: %s\n", buf);
    }
}
