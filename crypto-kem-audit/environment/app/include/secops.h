/*
 * secops.h - Security Operations Library (libsecops)
 *
 * Provides RSA key encapsulation (KEM), PBKDF2-based key derivation,
 * and supporting cryptographic utilities.
 *
 * RETURN VALUE CONVENTIONS:
 *   Status functions:     1 = success,  0 = failure
 *   Byte-count functions: N = bytes written on success, -1 = failure
 *
 * Each function documents which convention it uses.
 */

#ifndef SECOPS_H
#define SECOPS_H

#include <stddef.h>

/* ---- Constants ---- */

#define SECOPS_NO_PADDING       0
#define SECOPS_PKCS1_PADDING    1

#define SECOPS_MAX_RSA_SIZE     512
#define SECOPS_MAX_MD_SIZE      64
#define SECOPS_MAX_ITERATIONS   100000000

/* ASN.1 type tags */
#define V_SECOPS_ASN1_OCTET_STRING  4
#define V_SECOPS_ASN1_INTEGER       2
#define V_SECOPS_ASN1_UTF8STRING    12
#define V_SECOPS_ASN1_SEQUENCE      16
#define V_SECOPS_ASN1_SET           17

/* RSA key flags */
#define SECOPS_RSA_FLAG_PUB_SET   0x01
#define SECOPS_RSA_FLAG_PRIV_SET  0x02

/* ---- Data types ---- */

typedef struct secops_rsa_key_st {
    unsigned char *n;       /* modulus */
    int n_len;
    unsigned char *e;       /* public exponent */
    int e_len;
    unsigned char *d;       /* private exponent */
    int d_len;
    int flags;
} SECOPS_RSA;

typedef struct secops_asn1_type_st {
    int type;               /* tag identifying which union member is valid */
    union {
        struct {
            unsigned char *data;
            int length;
        } octet_string;
        long integer_value;
        struct {
            char *data;
            int length;
        } utf8string;
        void *ptr;
    } value;
} SECOPS_ASN1_TYPE;

typedef struct secops_asn1_integer_st {
    long value;
} SECOPS_ASN1_INTEGER;

typedef struct secops_pbkdf2_param_st {
    SECOPS_ASN1_TYPE *salt;             /* CHOICE: expected OCTET STRING */
    SECOPS_ASN1_INTEGER *keylength;     /* key length in bytes (may be absent) */
    SECOPS_ASN1_INTEGER *iterations;    /* iteration count */
    int prf_nid;                        /* PRF algorithm identifier */
} SECOPS_PBKDF2_PARAM;

typedef struct secops_kem_ctx_st {
    SECOPS_RSA *rsa;
    int mode;   /* 0 = encapsulate, 1 = decapsulate */
} SECOPS_KEM_CTX;

/* ---- RSA Operations ---- */

SECOPS_RSA *secops_rsa_new(void);
void secops_rsa_free(SECOPS_RSA *rsa);
int secops_rsa_size(const SECOPS_RSA *rsa);
int secops_rsa_set_key(SECOPS_RSA *rsa,
                       const unsigned char *n, int n_len,
                       const unsigned char *e, int e_len,
                       const unsigned char *d, int d_len);

/*
 * secops_rsa_public_encrypt - Encrypt plaintext with RSA public key.
 *
 * Returns the number of encrypted bytes written to `to` on success.
 * Returns -1 on error.
 *
 * For SECOPS_NO_PADDING, `flen` must equal the RSA modulus size.
 */
int secops_rsa_public_encrypt(int flen, const unsigned char *from,
                              unsigned char *to, SECOPS_RSA *rsa,
                              int padding);

/*
 * secops_rsa_private_decrypt - Decrypt ciphertext with RSA private key.
 *
 * Returns the number of decrypted bytes written to `to` on success.
 * Returns -1 on error.
 */
int secops_rsa_private_decrypt(int flen, const unsigned char *from,
                               unsigned char *to, SECOPS_RSA *rsa,
                               int padding);

/* ---- KEM Operations ---- */

SECOPS_KEM_CTX *secops_kem_ctx_new(SECOPS_RSA *rsa, int mode);
void secops_kem_ctx_free(SECOPS_KEM_CTX *ctx);

/*
 * secops_kem_encapsulate - Generate a random shared secret and its
 * RSA-encrypted ciphertext.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_kem_encapsulate(SECOPS_KEM_CTX *ctx,
                           unsigned char *ct, size_t *ctlen,
                           unsigned char *secret, size_t *secretlen);

/*
 * secops_kem_decapsulate - Recover shared secret from ciphertext.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_kem_decapsulate(SECOPS_KEM_CTX *ctx,
                           unsigned char *secret, size_t *secretlen,
                           const unsigned char *ct, size_t ctlen);

/* ---- KDF Operations ---- */

/*
 * secops_pbmac1_derive - Derive a key from password using PBKDF2
 * parameters in PBMAC1 format.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_pbmac1_derive(SECOPS_PBKDF2_PARAM *param,
                         const char *pass, int passlen,
                         unsigned char *key_out, int *keylen_out);

/*
 * secops_pbkdf2_hmac - Low-level PBKDF2-HMAC key derivation.
 *
 * Returns 1 on success, 0 on failure.
 */
int secops_pbkdf2_hmac(const char *pass, int passlen,
                       const unsigned char *salt, int saltlen,
                       int iterations, int keylen,
                       unsigned char *out);

/* ---- Utilities ---- */

void secops_cleanse(void *ptr, size_t len);
int secops_rand_bytes(unsigned char *buf, int len);

/* ---- ASN.1 Helpers ---- */

long secops_asn1_integer_get(const SECOPS_ASN1_INTEGER *a);
SECOPS_ASN1_INTEGER *secops_asn1_integer_new(long val);
void secops_asn1_integer_free(SECOPS_ASN1_INTEGER *a);
SECOPS_ASN1_TYPE *secops_asn1_type_new(void);
void secops_asn1_type_free(SECOPS_ASN1_TYPE *a);

#endif /* SECOPS_H */
