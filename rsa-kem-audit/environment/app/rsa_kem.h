/*
 * RSA-KEM (Key Encapsulation Mechanism) - RSASVE
 * Based on NIST SP 800-56B Rev 2, Section 7.2.1
 */
#ifndef RSA_KEM_H
#define RSA_KEM_H

#ifndef OPENSSL_SUPPRESS_DEPRECATED
#define OPENSSL_SUPPRESS_DEPRECATED
#endif

#include <openssl/rsa.h>
#include <openssl/bn.h>
#include <openssl/rand.h>
#include <openssl/err.h>
#include <openssl/crypto.h>
#include <stddef.h>

#define RSA_KEM_OP_ENCAPSULATE 0
#define RSA_KEM_OP_DECAPSULATE 1

typedef struct {
    RSA *rsa;
    int op;
} RSA_KEM_CTX;

/* Create a new RSA-KEM context. Caller retains ownership of rsa. */
RSA_KEM_CTX *rsa_kem_ctx_new(RSA *rsa, int operation);

/* Free the context and release the internal RSA ref. */
void rsa_kem_ctx_free(RSA_KEM_CTX *ctx);

/* Return the modulus byte-length (ciphertext and secret size). */
int rsa_kem_get_size(RSA_KEM_CTX *ctx);

/*
 * RSASVE.Generate (encapsulation).
 *
 * Pass out == NULL to query sizes only.
 * On success writes ciphertext to out[0..outlen) and shared secret to
 * secret[0..secretlen).  Both buffers must be rsa_kem_get_size() bytes.
 *
 * Returns 1 on success, 0 on failure.
 */
int rsasve_generate(RSA_KEM_CTX *ctx,
                    unsigned char *out, size_t *outlen,
                    unsigned char *secret, size_t *secretlen);

/*
 * RSASVE.Recover (decapsulation).
 *
 * Pass secret == NULL to query sizes only.
 * Recovers the shared secret from ciphertext in[0..inlen).
 *
 * Returns 1 on success, 0 on failure.
 */
int rsasve_recover(RSA_KEM_CTX *ctx,
                   unsigned char *secret, size_t *secretlen,
                   const unsigned char *in, size_t inlen);

#endif /* RSA_KEM_H */
