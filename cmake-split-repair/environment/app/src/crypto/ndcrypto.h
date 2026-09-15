#ifndef NDCRYPTO_H
#define NDCRYPTO_H

#include <stddef.h>

/* Hash a password using SHA-256, output as hex string */
int nd_hash_password(const char *password, char *out, size_t out_len);

/* Verify a password against a hex hash (returns 0 on match) */
int nd_verify_password(const char *password, const char *hash);

/* Generate a random hex token of given length */
int nd_generate_token(char *out, size_t len);

#endif /* NDCRYPTO_H */
