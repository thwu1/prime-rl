#include "ed25519.h"
#include <openssl/sha.h>
#include <string.h>


/*
 * Ed25519 implementation skeleton.
 *
 * SHA-512 is available via <openssl/sha.h> (SHA512, SHA512_Init/Update/Final).
 * Arbitrary-precision integers are available via <openssl/bn.h> (BN_* API).
 *
 * You must implement Ed25519 key derivation, signing, and verification
 * per RFC 8032 Section 5.1.
 */

void ed25519_derive_pubkey(const uint8_t secret[32], uint8_t pubkey[32]) {
    (void)secret;
    memset(pubkey, 0, 32);
}

void ed25519_sign(const uint8_t secret[32], const uint8_t *msg, size_t msg_len,
                  uint8_t signature[64]) {
    (void)secret;
    (void)msg;
    (void)msg_len;
    memset(signature, 0, 64);
}

int ed25519_verify(const uint8_t pubkey[32], const uint8_t *msg, size_t msg_len,
                   const uint8_t signature[64]) {
    (void)pubkey;
    (void)msg;
    (void)msg_len;
    (void)signature;
    return 0;
}
