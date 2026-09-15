#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include "secure_ops.h"
#include "crypto_impl.h"

int main(void) {
    uint8_t key[16] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                       0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10};
    uint8_t plaintext[32] = "Hello, secure world! Test 1234";
    uint8_t ciphertext[32];
    uint8_t decrypted[32];

    /* Test encrypt/decrypt roundtrip */
    secure_encrypt(key, plaintext, ciphertext, 32);
    secure_decrypt(key, ciphertext, decrypted, 32);
    if (memcmp(plaintext, decrypted, 32) != 0) {
        fprintf(stderr, "FAIL: encrypt/decrypt roundtrip\n");
        return 1;
    }

    /* Test auth token verification */
    uint8_t token[] = "my_secret_token";
    uint8_t hash[32];
    hash_compute(token, sizeof(token) - 1, hash, 32);
    if (!verify_auth_token(token, sizeof(token) - 1, hash)) {
        fprintf(stderr, "FAIL: auth token verification (valid token rejected)\n");
        return 1;
    }
    /* Verify rejection of invalid token */
    uint8_t bad_token[] = "wrong_token_xxxx";
    if (verify_auth_token(bad_token, sizeof(bad_token) - 1, hash)) {
        fprintf(stderr, "FAIL: auth token verification (invalid token accepted)\n");
        return 1;
    }

    /* Test keypair generation */
    uint8_t seed[32] = {0};
    uint8_t pub[32], priv[32];
    generate_keypair(seed, pub, priv);
    /* Keys should be different */
    if (memcmp(pub, priv, 32) == 0) {
        fprintf(stderr, "FAIL: keypair generation produced identical keys\n");
        return 1;
    }

    /* Test HMAC sign */
    uint8_t msg[] = "test message";
    uint8_t sig[32];
    hmac_sign(key, 16, msg, sizeof(msg) - 1, sig);
    /* Sign again and verify determinism */
    uint8_t sig2[32];
    hmac_sign(key, 16, msg, sizeof(msg) - 1, sig2);
    if (memcmp(sig, sig2, 32) != 0) {
        fprintf(stderr, "FAIL: HMAC signing is not deterministic\n");
        return 1;
    }

    /* Test subscription processing */
    uint8_t sub_data[] = "subscription_data_here";
    uint8_t sub_hmac[32];
    hmac_compute(key, 16, sub_data, sizeof(sub_data) - 1, sub_hmac, 32);
    if (!process_subscription(key, sub_data, sizeof(sub_data) - 1, sub_hmac)) {
        fprintf(stderr, "FAIL: subscription verification (valid data rejected)\n");
        return 1;
    }
    /* Verify rejection of tampered data */
    uint8_t bad_data[] = "tampered_data_goes_here";
    if (process_subscription(key, bad_data, sizeof(bad_data) - 1, sub_hmac)) {
        fprintf(stderr, "FAIL: subscription verification (tampered data accepted)\n");
        return 1;
    }

    /* Test session key derivation */
    uint8_t nonce[16] = {0xAA, 0xBB, 0xCC, 0xDD};
    uint8_t session_key[32];
    derive_session_key(key, nonce, session_key);

    /* Test safe wipe */
    uint8_t buf[16] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16};
    safe_wipe_example(buf, 16);
    for (int i = 0; i < 16; i++) {
        if (buf[i] != 0) {
            fprintf(stderr, "FAIL: safe_wipe_example did not zero buffer\n");
            return 1;
        }
    }

    /* Test already safe sign */
    already_safe_sign(key, msg, sizeof(msg) - 1, sig);

    printf("All functional tests passed.\n");
    return 0;
}
