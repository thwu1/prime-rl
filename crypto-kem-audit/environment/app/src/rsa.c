/*
 * rsa.c - RSA key operations
 *
 * Provides RSA encryption and decryption using a simplified model.
 *
 * Return convention for encrypt/decrypt:
 *   - Success: number of bytes written (always equal to modulus size)
 *   - Failure: -1
 */

#include "secops.h"
#include <stdlib.h>
#include <string.h>

SECOPS_RSA *secops_rsa_new(void)
{
    SECOPS_RSA *rsa = calloc(1, sizeof(*rsa));
    return rsa;
}

void secops_rsa_free(SECOPS_RSA *rsa)
{
    if (rsa == NULL)
        return;
    if (rsa->n != NULL) {
        secops_cleanse(rsa->n, (size_t)rsa->n_len);
        free(rsa->n);
    }
    if (rsa->e != NULL)
        free(rsa->e);
    if (rsa->d != NULL) {
        secops_cleanse(rsa->d, (size_t)rsa->d_len);
        free(rsa->d);
    }
    free(rsa);
}

int secops_rsa_size(const SECOPS_RSA *rsa)
{
    if (rsa == NULL)
        return 0;
    return rsa->n_len;
}

int secops_rsa_set_key(SECOPS_RSA *rsa,
                       const unsigned char *n, int n_len,
                       const unsigned char *e, int e_len,
                       const unsigned char *d, int d_len)
{
    if (rsa == NULL)
        return 0;

    if (n != NULL && n_len > 0) {
        rsa->n = malloc((size_t)n_len);
        if (rsa->n == NULL)
            return 0;
        memcpy(rsa->n, n, (size_t)n_len);
        rsa->n_len = n_len;
    }

    if (e != NULL && e_len > 0) {
        rsa->e = malloc((size_t)e_len);
        if (rsa->e == NULL)
            return 0;
        memcpy(rsa->e, e, (size_t)e_len);
        rsa->e_len = e_len;
        rsa->flags |= SECOPS_RSA_FLAG_PUB_SET;
    }

    if (d != NULL && d_len > 0) {
        rsa->d = malloc((size_t)d_len);
        if (rsa->d == NULL)
            return 0;
        memcpy(rsa->d, d, (size_t)d_len);
        rsa->d_len = d_len;
        rsa->flags |= SECOPS_RSA_FLAG_PRIV_SET;
    }

    return 1;
}

/*
 * Perform RSA public-key encryption.
 *
 * This is a simplified model using XOR with the modulus for demonstration.
 * In a production implementation, this would use modular exponentiation.
 *
 * Returns: number of bytes written to `to` on success, -1 on failure.
 */
int secops_rsa_public_encrypt(int flen, const unsigned char *from,
                              unsigned char *to, SECOPS_RSA *rsa,
                              int padding)
{
    int n_len;
    int i;

    if (rsa == NULL || from == NULL || to == NULL)
        return -1;

    if (!(rsa->flags & SECOPS_RSA_FLAG_PUB_SET))
        return -1;

    n_len = rsa->n_len;
    if (n_len <= 0 || n_len > SECOPS_MAX_RSA_SIZE)
        return -1;

    if (padding == SECOPS_NO_PADDING) {
        if (flen != n_len)
            return -1;
    } else if (padding == SECOPS_PKCS1_PADDING) {
        if (flen > n_len - 11)
            return -1;
    } else {
        return -1;  /* unsupported padding mode */
    }

    /* Simplified encryption: XOR input with modulus bytes */
    for (i = 0; i < n_len; i++) {
        unsigned char input_byte = (i < flen) ? from[i] : 0;
        to[i] = input_byte ^ rsa->n[i % rsa->n_len];
    }

    return n_len;
}

/*
 * Perform RSA private-key decryption.
 *
 * Returns: number of bytes written to `to` on success, -1 on failure.
 */
int secops_rsa_private_decrypt(int flen, const unsigned char *from,
                               unsigned char *to, SECOPS_RSA *rsa,
                               int padding)
{
    int n_len;
    int i;

    if (rsa == NULL || from == NULL || to == NULL)
        return -1;

    if (!(rsa->flags & SECOPS_RSA_FLAG_PRIV_SET))
        return -1;

    n_len = rsa->n_len;
    if (n_len <= 0 || n_len > SECOPS_MAX_RSA_SIZE)
        return -1;

    if (padding == SECOPS_NO_PADDING) {
        if (flen != n_len)
            return -1;
    }

    /* Simplified decryption: XOR with modulus (inverse of XOR encrypt) */
    for (i = 0; i < n_len; i++)
        to[i] = from[i] ^ rsa->n[i % rsa->n_len];

    return n_len;
}
