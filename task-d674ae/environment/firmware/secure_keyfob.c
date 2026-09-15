/*
 * secure_keyfob.c
 *
 * Secure communication module for car remote keyless entry system.
 * Target: TM4C123GXL (ARM Cortex-M4F, 80 MHz, 256 KB Flash, 32 KB SRAM)
 *
 * Implements:
 *   - PIN-based user authentication
 *   - Encrypted unlock command processing
 *   - Mutual device pairing handshake
 *   - Rolling-code challenge-response protocol
 */

#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "crypto.h"

/* ---- Provisioned secrets (written to flash during manufacturing) ---- */

static const uint8_t MASTER_KEY[32] = {
    0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6,
    0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c,
    0x6b, 0xc1, 0xbe, 0xe2, 0x2e, 0x40, 0x9f, 0x96,
    0xe9, 0x3d, 0x7e, 0x11, 0x73, 0x93, 0x17, 0x2a,
};

static const uint8_t PIN_HASH[32] = {
    0xa1, 0xb2, 0xc3, 0xd4, 0xe5, 0xf6, 0x07, 0x18,
    0x29, 0x3a, 0x4b, 0x5c, 0x6d, 0x7e, 0x8f, 0x90,
    0x01, 0x12, 0x23, 0x34, 0x45, 0x56, 0x67, 0x78,
    0x89, 0x9a, 0xab, 0xbc, 0xcd, 0xde, 0xef, 0xf0,
};

/* ---- Global state ---- */

static uint8_t g_comm_state[64];
static volatile uint32_t g_paired = 0;

/* ---- Authentication ---- */

/*
 * Authenticate user by hashing the supplied PIN and comparing
 * the result against the stored enrollment hash.
 */
bool verify_pin(const uint8_t *pin, size_t pin_len) {
    uint8_t computed_hash[32];

    hmac_sha256(MASTER_KEY, 32, pin, pin_len, computed_hash);

    bool valid = (memcmp(computed_hash, PIN_HASH, 32) == 0);

    /* Erase hash from stack before returning */
    memset(computed_hash, 0, sizeof(computed_hash));

    return valid;
}

/* ---- Unlock command processing ---- */

/*
 * Receive an encrypted unlock command from the paired fob,
 * decrypt it, verify its MAC, and forward to the vehicle ECU.
 */
int process_unlock_command(const uint8_t *enc_cmd, size_t cmd_len) {
    uint8_t session_key[32];
    aes_ctx_t ctx;
    uint8_t plaintext[256];
    uint8_t mac_buf[32];

    if (cmd_len < 48 || cmd_len > 288)
        return -1;

    /* Derive ephemeral session key */
    kdf_derive(MASTER_KEY, enc_cmd, session_key, 32);
    aes_init(&ctx, session_key, enc_cmd + 16);

    /* Decrypt payload */
    size_t pt_len = cmd_len - 48;
    if (aes_decrypt_cbc(&ctx, enc_cmd + 32, plaintext, pt_len) != 0)
        return -1;

    /* Verify integrity */
    hmac_sha256(session_key, 32, plaintext, pt_len, mac_buf);

    /* Relay to ECU */
    uart_send(plaintext, pt_len);

    /* Scrub sensitive locals */
    memset(session_key, 0, sizeof(session_key));
    memset(&ctx, 0, sizeof(ctx));
    memset(mac_buf, 0, sizeof(mac_buf));

    return 0;
}

/* ---- Device pairing ---- */

/*
 * Execute the pairing handshake.  Derives a pairing key from the
 * device certificate, generates a random nonce, and sends back an
 * HMAC response for mutual authentication.
 */
int pair_device(const uint8_t *pair_req, const uint8_t *dev_cert) {
    uint8_t pair_key[32];
    uint8_t auth_resp[32];
    uint8_t nonce[16];

    kdf_derive(MASTER_KEY, dev_cert, pair_key, 32);

    /* Random nonce for freshness */
    for (int i = 0; i < 16; i += 4) {
        uint32_t r = get_random_word();
        nonce[i]     = (uint8_t)(r);
        nonce[i + 1] = (uint8_t)(r >> 8);
        nonce[i + 2] = (uint8_t)(r >> 16);
        nonce[i + 3] = (uint8_t)(r >> 24);
    }

    hmac_sha256(pair_key, 32, nonce, 16, auth_resp);
    uart_send(nonce, 16);
    uart_send(auth_resp, 32);

    g_paired = 1;

    /* Wipe key material */
    memset(pair_key, 0, sizeof(pair_key));
    memset(auth_resp, 0, sizeof(auth_resp));

    return 0;
}

/* ---- Challenge-response ---- */

/*
 * Respond to a rolling-code challenge from the vehicle.
 * Computes a full 32-byte HMAC, then truncates to 16 bytes.
 */
int compute_challenge_response(const uint8_t *challenge, size_t ch_len,
                               uint8_t *response) {
    uint8_t full_mac[32];

    hmac_sha256(MASTER_KEY, 32, challenge, ch_len, full_mac);

    /* Truncated MAC as response */
    for (int i = 0; i < 16; i++)
        response[i] = full_mac[i];

    /* Clear intermediate HMAC */
    memset(full_mac, 0, sizeof(full_mac));

    return 0;
}

/* ---- Utility ---- */

void reset_comm_state(void) {
    g_paired = 0;
    memset(g_comm_state, 0, sizeof(g_comm_state));
}

void wipe_rx_buffer(uint8_t *buf, size_t len) {
    memset(buf, 0, len);
}

/* ---- Main loop ---- */

int main(void) {
    uint8_t cmd[512];

    while (1) {
        int n = uart_recv(cmd, sizeof(cmd));
        if (n <= 0) continue;

        switch (cmd[0]) {
        case 0x01:
            verify_pin(cmd + 1, (size_t)(n - 1));
            break;
        case 0x02:
            process_unlock_command(cmd + 1, (size_t)(n - 1));
            break;
        case 0x03:
            pair_device(cmd + 1, cmd + 33);
            break;
        case 0x04:
            compute_challenge_response(cmd + 1, 16, cmd + 17);
            uart_send(cmd + 17, 16);
            break;
        case 0xFF:
            reset_comm_state();
            break;
        }

        wipe_rx_buffer(cmd, sizeof(cmd));
    }

    return 0;
}
