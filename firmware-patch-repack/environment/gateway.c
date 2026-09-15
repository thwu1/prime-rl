#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>

#define NUM_CHANNELS 16

static const char *PROTOCOL_ID = "IoTGW-SECURE-v3";

/*
 * Channel access control table.
 * Entries 0..15 are the valid channels.
 * Entry 16 is a trap: value 1 causes a false-positive if the
 * bounds check has an off-by-one error.
 */
static int channel_acl[] = {
    1, 1, 1, 1,   /* 0-3   */
    1, 1, 0, 0,   /* 4-7   */
    1, 1, 1, 1,   /* 8-11  */
    0, 0, 1, 1,   /* 12-15 */
    1, 0, 0, 0,   /* 16-19: trap / padding */
};

/*
 * Embedded security policy block.
 * Fields are read at runtime to enforce security parameters.
 */
struct __attribute__((packed)) security_config {
    char     magic[8];          /* "SECCFG\0\0" */
    uint16_t max_channel;       /* exclusive upper bound for valid channels */
    uint8_t  require_auth;      /* 1 = authentication required */
    uint8_t  tls_mode;          /* 0=off, 1=optional, 2=required */
    uint32_t session_timeout;   /* seconds */
    uint8_t  allow_debug;       /* 0 = debug interface disabled */
    uint8_t  cert_verify;       /* 1 = verify remote certificates */
    uint16_t min_key_bits;      /* minimum acceptable RSA key size */
    uint32_t reserved[2];
};

static struct security_config sec_cfg = {
    .magic           = "SECCFG\0",
    .max_channel     = 17,       /* VULN: off-by-one, should be 16 */
    .require_auth    = 0,        /* VULN: no auth */
    .tls_mode        = 0,        /* VULN: TLS disabled */
    .session_timeout = 86400,
    .allow_debug     = 1,        /* VULN: debug on */
    .cert_verify     = 0,        /* VULN: no cert check */
    .min_key_bits    = 512,      /* VULN: weak keys accepted */
    .reserved        = {0, 0},
};

void print_info(void) {
    printf("IoT Gateway Firmware\n");
    printf("Protocol: %s\n", PROTOCOL_ID);
    printf("Channels: %d\n", NUM_CHANNELS);
    printf("TLS: %d  Auth: %d\n", sec_cfg.tls_mode, sec_cfg.require_auth);
}

int check_channel(int ch) {
    if (ch >= 0 && ch < sec_cfg.max_channel) {
        return channel_acl[ch];
    }
    return 0;
}

void dump_security(void) {
    printf("Security Config:\n");
    printf("  max_channel: %d\n", sec_cfg.max_channel);
    printf("  require_auth: %d\n", sec_cfg.require_auth);
    printf("  tls_mode: %d\n", sec_cfg.tls_mode);
    printf("  session_timeout: %u\n", sec_cfg.session_timeout);
    printf("  allow_debug: %d\n", sec_cfg.allow_debug);
    printf("  cert_verify: %d\n", sec_cfg.cert_verify);
    printf("  min_key_bits: %d\n", sec_cfg.min_key_bits);
}

int main(int argc, char *argv[]) {
    if (argc > 1 && strcmp(argv[1], "--info") == 0) {
        print_info();
        return 0;
    }
    if (argc > 1 && strcmp(argv[1], "--security") == 0) {
        dump_security();
        return 0;
    }
    if (argc > 1 && strcmp(argv[1], "--validate") == 0) {
        if (argc < 3) {
            fprintf(stderr, "Usage: gateway --validate <channel>\n");
            return 1;
        }
        int ch = atoi(argv[2]);
        if (check_channel(ch)) {
            printf("Channel %d: valid\n", ch);
            return 0;
        } else {
            printf("Channel %d: invalid\n", ch);
            return 1;
        }
    }
    printf("IoT Gateway running protocol %s\n", PROTOCOL_ID);
    return 0;
}
