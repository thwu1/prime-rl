#include "secure_ops.h"
#include "crypto_impl.h"
#include <string.h>

/*
 * secure_encrypt: Encrypts plaintext using a derived key schedule.
 * After encryption, the expanded key material should be cleared
 * from the stack to prevent key recovery from memory dumps.
 */
int secure_encrypt(const uint8_t *key, const uint8_t *plaintext,
                   uint8_t *ciphertext, size_t len) {
    uint8_t expanded_key[176];

    key_expand(key, expanded_key, sizeof(expanded_key));
    block_encrypt(expanded_key, sizeof(expanded_key), plaintext, ciphertext, len);

    /* Clear sensitive key material from the stack */
    memset(expanded_key, 0, sizeof(expanded_key));

    return 0;
}

/*
 * secure_decrypt: Decrypts ciphertext using a derived key schedule.
 */
int secure_decrypt(const uint8_t *key, const uint8_t *ciphertext,
                   uint8_t *plaintext, size_t len) {
    uint8_t expanded_key[176];

    key_expand(key, expanded_key, sizeof(expanded_key));
    block_decrypt(expanded_key, sizeof(expanded_key), ciphertext, plaintext, len);

    /* Clear sensitive key material from the stack */
    memset(expanded_key, 0, sizeof(expanded_key));

    return 0;
}

/*
 * verify_auth_token: Computes hash of the provided token and compares
 * it against the stored hash to verify authenticity.
 */
int verify_auth_token(const uint8_t *token, size_t token_len,
                      const uint8_t *stored_hash) {
    uint8_t computed_hash[32];

    hash_compute(token, token_len, computed_hash, sizeof(computed_hash));

    int result = memcmp(computed_hash, stored_hash, 32);

    /* Clear computed hash from stack */
    memset(computed_hash, 0, sizeof(computed_hash));

    return result == 0 ? 1 : 0;
}

/*
 * generate_keypair: Derives a public/private keypair from a seed
 * using an entropy pool as an intermediate derivation step.
 */
int generate_keypair(const uint8_t *seed, uint8_t *pub_key, uint8_t *priv_key) {
    uint8_t entropy_pool[64];

    /* Derive entropy from seed */
    hash_compute(seed, 32, entropy_pool, sizeof(entropy_pool));

    /* Derive public key from first half */
    hash_compute(entropy_pool, 32, pub_key, 32);

    /* Derive private key from second half */
    hash_compute(entropy_pool + 32, 32, priv_key, 32);

    /* Clear the entropy pool */
    memset(entropy_pool, 0, sizeof(entropy_pool));

    return 0;
}

/*
 * hmac_sign: Computes an HMAC signature over a message.
 * Uses standard HMAC construction with inner/outer key padding.
 */
int hmac_sign(const uint8_t *key, size_t key_len,
              const uint8_t *msg, size_t msg_len,
              uint8_t *signature) {
    uint8_t inner_key[64];
    uint8_t outer_key[64];
    uint8_t inner_hash[32];

    /* Prepare inner and outer HMAC keys */
    for (size_t i = 0; i < 64; i++) {
        inner_key[i] = 0x36 ^ (i < key_len ? key[i] : 0);
        outer_key[i] = 0x5c ^ (i < key_len ? key[i] : 0);
    }

    /* Inner hash: H(inner_key || msg) */
    uint8_t inner_data[320];
    memcpy(inner_data, inner_key, 64);
    size_t copy_len = msg_len > 256 ? 256 : msg_len;
    memcpy(inner_data + 64, msg, copy_len);
    hash_compute(inner_data, 64 + copy_len, inner_hash, 32);

    /* Outer hash: H(outer_key || inner_hash) */
    uint8_t outer_data[96];
    memcpy(outer_data, outer_key, 64);
    memcpy(outer_data + 64, inner_hash, 32);
    hash_compute(outer_data, 96, signature, 32);

    /* Clear sensitive HMAC key material */
    memset(inner_key, 0, sizeof(inner_key));
    memset(outer_key, 0, sizeof(outer_key));

    return 0;
}

/*
 * process_subscription: Verifies the HMAC on incoming subscription data.
 * Computes HMAC over the data using the shared key and compares it
 * against the provided HMAC to ensure data integrity and authenticity.
 */
int process_subscription(const uint8_t *key,
                         const uint8_t *data, size_t data_len,
                         const uint8_t *provided_hmac) {
    uint8_t computed_hmac[32];

    hmac_compute(key, 16, data, data_len, computed_hmac, 32);

    int result = memcmp(provided_hmac, computed_hmac, 32);

    /* Clear computed HMAC */
    memset(computed_hmac, 0, sizeof(computed_hmac));

    return result == 0 ? 1 : 0;
}

/*
 * derive_session_key: Derives a session key from a master key and nonce.
 * Works with a local copy of the master key to avoid modifying the original.
 */
int derive_session_key(const uint8_t *master_key,
                       const uint8_t *nonce,
                       uint8_t *session_key) {
    uint8_t local_master[32];

    /* Work with a local copy of the master key */
    memcpy(local_master, master_key, 32);

    kdf_derive(local_master, 32, nonce, 16, session_key, 32);

    /* Clear the local copy of the master key */
    memset(local_master, 0, sizeof(local_master));

    return 0;
}

/*
 * safe_wipe_example: Reference implementation of memory wiping
 * using a volatile pointer to prevent compiler optimization.
 */
void safe_wipe_example(void *buf, size_t len) {
    volatile uint8_t *p = (volatile uint8_t *)buf;
    for (size_t i = 0; i < len; i++) {
        p[i] = 0;
    }
}

/*
 * already_safe_sign: Reference implementation that correctly uses
 * explicit_bzero to wipe key material after use.
 */
int already_safe_sign(const uint8_t *key, const uint8_t *msg,
                      size_t msg_len, uint8_t *signature) {
    uint8_t temp_key[32];

    hash_compute(key, 16, temp_key, sizeof(temp_key));
    hmac_compute(temp_key, sizeof(temp_key), msg, msg_len, signature, 32);

    /* Correctly uses explicit_bzero - will NOT be optimized away */
    explicit_bzero(temp_key, sizeof(temp_key));

    return 0;
}
