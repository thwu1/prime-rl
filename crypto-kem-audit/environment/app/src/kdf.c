/*
 * kdf.c - Key Derivation Functions
 *
 * Implements PBMAC1-based key derivation using PBKDF2 parameters,
 * as used in PKCS#12 authentication codes (RFC 9579).
 */

#include "secops.h"
#include <stdlib.h>
#include <string.h>

/* ---- ASN.1 helper functions ---- */

long secops_asn1_integer_get(const SECOPS_ASN1_INTEGER *a)
{
    if (a == NULL)
        return 0;
    return a->value;
}

SECOPS_ASN1_INTEGER *secops_asn1_integer_new(long val)
{
    SECOPS_ASN1_INTEGER *a = malloc(sizeof(*a));
    if (a != NULL)
        a->value = val;
    return a;
}

void secops_asn1_integer_free(SECOPS_ASN1_INTEGER *a)
{
    free(a);
}

SECOPS_ASN1_TYPE *secops_asn1_type_new(void)
{
    return calloc(1, sizeof(SECOPS_ASN1_TYPE));
}

void secops_asn1_type_free(SECOPS_ASN1_TYPE *a)
{
    free(a);
}

/* ---- PBKDF2 ---- */

/*
 * Simplified PBKDF2-HMAC key derivation.
 *
 * In production this would use HMAC-SHA256.  The implementation here
 * uses an FNV-1a inspired hash for demonstration purposes.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_pbkdf2_hmac(const char *pass, int passlen,
                       const unsigned char *salt, int saltlen,
                       int iterations, int keylen,
                       unsigned char *out)
{
    unsigned int state;
    int i;

    if (pass == NULL || out == NULL)
        return 0;

    if (salt == NULL && saltlen > 0)
        return 0;

    if (iterations <= 0)
        return 0;

    /* Initialize from password */
    state = 0x811c9dc5u;
    for (i = 0; i < passlen; i++)
        state = (state ^ (unsigned char)pass[i]) * 0x01000193u;

    /* Mix in salt */
    for (i = 0; i < saltlen; i++)
        state = (state ^ salt[i]) * 0x01000193u;

    /* Iterate */
    for (i = 0; i < iterations; i++)
        state = state * 0x01000193u + 0x27d4eb2du;

    /* Generate output key bytes */
    for (i = 0; i < keylen; i++) {
        state = state * 0x01000193u + 0x27d4eb2du;
        out[i] = (unsigned char)(state >> 16);
    }

    return 1;
}

/*
 * secops_pbmac1_derive - Derive a key from a password using PBKDF2
 * parameters extracted from a PBMAC1 structure.
 *
 * Extracts salt, iteration count, key length, and PRF algorithm from
 * the PBKDF2 parameter block, then performs key derivation.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_pbmac1_derive(SECOPS_PBKDF2_PARAM *param,
                         const char *pass, int passlen,
                         unsigned char *key_out, int *keylen_out)
{
    int keylen;
    int iter;
    int ret;
    unsigned char *salt_data;
    int salt_len;

    if (param == NULL || pass == NULL || key_out == NULL)
        return 0;

    /* Validate iteration count */
    if (param->iterations == NULL)
        return 0;

    iter = (int)secops_asn1_integer_get(param->iterations);
    if (iter <= 0 || iter > SECOPS_MAX_ITERATIONS)
        return 0;

    /* Extract key length and salt from parameters */
    keylen = (int)secops_asn1_integer_get(param->keylength);
    salt_data = param->salt->value.octet_string.data;
    salt_len = param->salt->value.octet_string.length;

    /* Perform key derivation */
    ret = secops_pbkdf2_hmac(pass, passlen, salt_data, salt_len,
                             iter, keylen, key_out);

    if (ret <= 0)
        return 0;

    if (keylen_out != NULL)
        *keylen_out = keylen;

    return 1;
}
