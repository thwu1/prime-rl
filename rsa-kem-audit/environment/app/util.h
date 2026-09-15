/*
 * Utility functions for RSA key management and diagnostics.
 */
#ifndef UTIL_H
#define UTIL_H

#ifndef OPENSSL_SUPPRESS_DEPRECATED
#define OPENSSL_SUPPRESS_DEPRECATED
#endif

#include <openssl/rsa.h>
#include <openssl/bn.h>
#include <openssl/pem.h>
#include <openssl/err.h>
#include <stddef.h>

/* Generate an RSA key pair of the given bit size. Caller owns the result. */
RSA *generate_rsa_keypair(int bits);

/* Print a hex dump (truncated at 32 bytes) to stdout. */
void print_hex(const char *label, const unsigned char *data, size_t len);

/* Write RSA key pair to PEM files. Returns 1 on success. */
int save_rsa_keypair(RSA *rsa, const char *pubfile, const char *privfile);

/* Load RSA public key from PEM file. */
RSA *load_rsa_pubkey(const char *filename);

/* Load RSA private key from PEM file. */
RSA *load_rsa_privkey(const char *filename);

/* Drain and print the OpenSSL error queue to stderr. */
void print_openssl_errors(void);

#endif /* UTIL_H */
