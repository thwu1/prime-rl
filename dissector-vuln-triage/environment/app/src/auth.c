#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "ndp.h"

/*
 * AUTH payload format:
 *   [0]     phase       uint8
 *   Phase-specific data follows (see ndp.h for full format).
 */

static void auth_log(const char *level, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    fprintf(stderr, "[AUTH-%s] ", level);
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap);
}

static int validate_token(const uint8_t *token, size_t len) {
    if (len < 8)
        return 0;
    for (size_t i = 0; i < len; i++) {
        char c = (char)token[i];
        if (!((c >= '0' && c <= '9') ||
              (c >= 'a' && c <= 'f') ||
              (c >= 'A' && c <= 'F'))) {
            return 0;
        }
    }
    return 1;
}

static int process_auth_init(const uint8_t *payload, size_t len, uint8_t flags) {
    if (len < 3)
        return -1;

    uint16_t user_len = read_u16_be(payload + 1);
    if (3 + (size_t)user_len > len) {
        auth_log("ERROR", "username extends past payload");
        return -1;
    }

    char username[AUTH_USER_BUF];
    if (user_len >= AUTH_USER_BUF) {
        auth_log("ERROR", "username too long (%u bytes)", user_len);
        return -1;
    }
    memcpy(username, payload + 3, user_len);
    username[user_len] = '\0';

    /* Debug logging for authentication attempts */
    if (flags & NDP_FLAG_DEBUG) {
        char log_msg[LOG_BUF_SIZE];
        snprintf(log_msg, sizeof(log_msg), username);
        auth_log("DEBUG", "auth_init from: %s", log_msg);
    }

    /* Parse optional token */
    size_t token_offset = 3 + (size_t)user_len;
    if (token_offset + 2 <= len) {
        uint16_t token_len = read_u16_be(payload + token_offset);
        if (token_offset + 2 + (size_t)token_len <= len) {
            if (!validate_token(payload + token_offset + 2, token_len)) {
                auth_log("WARN", "invalid token format");
                return -1;
            }
            printf("AUTH: user=\"%s\" token_len=%u phase=INIT\n",
                   username, token_len);
        } else {
            printf("AUTH: user=\"%s\" phase=INIT (token truncated)\n", username);
        }
    } else {
        printf("AUTH: user=\"%s\" phase=INIT (no token)\n", username);
    }

    return 0;
}

static int process_auth_response(const uint8_t *payload, size_t len,
                                 uint8_t flags) {
    (void)flags;
    if (len < 5)
        return -1;

    uint32_t challenge = read_u32_be(payload + 1);
    printf("AUTH: challenge=0x%08X phase=RESPONSE\n", challenge);
    return 0;
}

static int process_auth_confirm(const uint8_t *payload, size_t len,
                                uint8_t flags) {
    (void)flags;
    if (len < 2)
        return -1;

    uint8_t status = payload[1];
    printf("AUTH: status=%s phase=CONFIRM\n",
           status ? "accepted" : "rejected");
    return 0;
}

int handle_auth(const uint8_t *payload, size_t len, uint8_t flags) {
    if (len < 1) {
        auth_log("ERROR", "empty auth payload");
        return -1;
    }

    uint8_t phase = payload[0];

    switch (phase) {
        case AUTH_PHASE_INIT:
            return process_auth_init(payload, len, flags);
        case AUTH_PHASE_RESPONSE:
            return process_auth_response(payload, len, flags);
        case AUTH_PHASE_CONFIRM:
            return process_auth_confirm(payload, len, flags);
        default:
            auth_log("ERROR", "unknown auth phase 0x%02X", phase);
            return -1;
    }
}
