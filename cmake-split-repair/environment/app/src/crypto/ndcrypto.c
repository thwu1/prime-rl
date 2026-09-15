#include "ndcrypto.h"
#include "../core/ndcore.h"
#include <openssl/sha.h>
#include <openssl/rand.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* Internal: compute raw SHA-256 digest */
int compute_digest(const unsigned char *data, size_t len,
                   unsigned char *out, size_t out_len) {
    if (!data || !out || out_len < SHA256_DIGEST_LENGTH) return -1;
    SHA256(data, len, out);
    return 0;
}

int nd_hash_password(const char *password, char *out, size_t out_len) {
    if (!password || !out || out_len < 65) return -1;

    unsigned char hash[SHA256_DIGEST_LENGTH];
    if (compute_digest((unsigned char *)password, strlen(password),
                       hash, sizeof(hash)) != 0)
        return -1;

    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        snprintf(out + (i * 2), 3, "%02x", hash[i]);
    }
    out[64] = '\0';

    nd_log(3, "Password hashed successfully");
    return 0;
}

int nd_verify_password(const char *password, const char *hash) {
    if (!password || !hash) return -1;

    char computed[65];
    if (nd_hash_password(password, computed, sizeof(computed)) != 0) {
        return -1;
    }

    return strcmp(computed, hash) == 0 ? 0 : 1;
}

int nd_generate_token(char *out, size_t len) {
    if (!out || len < 3) return -1;

    size_t raw_len = (len - 1) / 2;
    unsigned char *buf = malloc(raw_len);
    if (!buf) return -1;

    if (RAND_bytes(buf, raw_len) != 1) {
        free(buf);
        nd_log(1, "Failed to generate random bytes");
        return -1;
    }

    for (size_t i = 0; i < raw_len; i++) {
        snprintf(out + (i * 2), 3, "%02x", buf[i]);
    }
    out[raw_len * 2] = '\0';

    free(buf);
    nd_log(3, "Token generated");
    return 0;
}
