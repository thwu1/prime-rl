#include "crypto_impl.h"
#include <string.h>

void key_expand(const uint8_t *key, uint8_t *expanded, size_t expanded_len) {
    if (expanded_len < 16) return;
    memcpy(expanded, key, 16);
    for (size_t i = 16; i < expanded_len; i++) {
        expanded[i] = expanded[i - 1] ^ expanded[i - 16] ^ (uint8_t)(i * 0x9E + 0x37);
    }
}

void block_encrypt(const uint8_t *key_schedule, size_t ks_len,
                   const uint8_t *input, uint8_t *output, size_t len) {
    for (size_t i = 0; i < len; i++) {
        uint8_t k = key_schedule[i % ks_len];
        output[i] = (input[i] ^ k) + (uint8_t)(k >> 3);
    }
}

void block_decrypt(const uint8_t *key_schedule, size_t ks_len,
                   const uint8_t *input, uint8_t *output, size_t len) {
    for (size_t i = 0; i < len; i++) {
        uint8_t k = key_schedule[i % ks_len];
        output[i] = (input[i] - (uint8_t)(k >> 3)) ^ k;
    }
}

void hash_compute(const uint8_t *data, size_t data_len,
                  uint8_t *hash, size_t hash_len) {
    uint64_t state[4] = {
        0xcbf29ce484222325ULL, 0xbb67ae8584caa73bULL,
        0x3c6ef372fe94f82bULL, 0xa54ff53a5f1d36f1ULL
    };
    for (size_t i = 0; i < data_len; i++) {
        state[i % 4] ^= ((uint64_t)data[i]) << ((i % 8) * 8);
        state[i % 4] *= 0x100000001b3ULL;
        state[(i + 1) % 4] ^= state[i % 4] >> 17;
    }
    for (size_t i = 0; i < hash_len; i++) {
        hash[i] = (uint8_t)(state[i % 4] >> ((i % 8) * 8));
        if ((i % 8) == 7) {
            state[i % 4] ^= 0xa5a5a5a5a5a5a5a5ULL;
            state[i % 4] *= 0x100000001b3ULL;
        }
    }
}

void hmac_compute(const uint8_t *key, size_t key_len,
                  const uint8_t *msg, size_t msg_len,
                  uint8_t *mac, size_t mac_len) {
    uint8_t inner_input[256];
    size_t inner_len = 0;

    if (key_len + msg_len <= sizeof(inner_input)) {
        memcpy(inner_input, key, key_len);
        memcpy(inner_input + key_len, msg, msg_len);
        inner_len = key_len + msg_len;
    } else {
        inner_len = sizeof(inner_input);
        for (size_t i = 0; i < inner_len; i++) {
            if (i < key_len) inner_input[i] = key[i];
            else if (i - key_len < msg_len) inner_input[i] = msg[i - key_len];
            else inner_input[i] = 0;
        }
    }

    uint8_t inner_hash[32];
    hash_compute(inner_input, inner_len, inner_hash, 32);

    uint8_t outer_input[64];
    size_t outer_key_len = key_len > 32 ? 32 : key_len;
    memcpy(outer_input, key, outer_key_len);
    memcpy(outer_input + outer_key_len, inner_hash, 32);

    hash_compute(outer_input, outer_key_len + 32, mac, mac_len);
}

void kdf_derive(const uint8_t *master, size_t master_len,
                const uint8_t *salt, size_t salt_len,
                uint8_t *derived, size_t derived_len) {
    uint8_t combined[128];
    size_t combined_len = 0;

    for (size_t i = 0; i < sizeof(combined); i++) {
        if (i < master_len) combined[i] = master[i];
        else if (i < master_len + salt_len) combined[i] = salt[i - master_len];
        else combined[i] = (uint8_t)(i ^ 0xAB);
        combined_len++;
    }

    hash_compute(combined, combined_len, derived, derived_len);
}
