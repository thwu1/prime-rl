/*
 * heapservice.c - HeapService v2.4.1 Secure Session Manager
 *
 * This source is compiled during Docker build, stripped, and placed at
 * /app/heapservice for the solver to reverse-engineer.
 *
 * Build: gcc -O1 -o heapservice heapservice.c && strip heapservice
 *
 */

#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdio.h>

/* Service identification */
static const char BANNER[] = "HEAPSERVICE v2.4.1 - Secure Session Manager";

/* Integrity verification salt (NOT the encryption key - red herring) */
static const uint8_t INTEGRITY_SALT[8] = {
    0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE
};

/*
 * Audit key for session token encryption.
 * Stored in a packed struct with a marker string for forensic recovery.
 * The solver must extract these 16 bytes from the stripped binary's .rodata.
 */
struct __attribute__((packed)) audit_blob {
    char marker[20];    /* "AUDIT_KEY_MATERIAL:" + null terminator */
    uint8_t key[16];    /* The actual encryption key */
};

static const struct audit_blob audit_data = {
    .marker = "AUDIT_KEY_MATERIAL:",
    .key = {
        0x7a, 0x3f, 0xb1, 0x94, 0xe2, 0x55, 0x08, 0xc7,
        0x6d, 0xa3, 0x19, 0xf0, 0x4b, 0x82, 0xd6, 0x5e
    }
};

/* Allocation sizes for each heap slot */
#define NUM_SLOTS 8
static const size_t SLOT_SIZES[NUM_SLOTS] = {
    0x80, 0x20, 0x40, 0x40, 0x60, 0xA0, 0x20, 0x40
};

static const char *SLOT_LABELS[NUM_SLOTS] = {
    "BANNER", "METADATA", "BUFFER_A", "BUFFER_B",
    "TX_LOG", "AUDIT", "CONFIG", "SESSION"
};

static void *slots[NUM_SLOTS];

int main(void) {
    int i;

    /* Allocate all slots */
    for (i = 0; i < NUM_SLOTS; i++) {
        slots[i] = calloc(1, SLOT_SIZES[i]);
        if (!slots[i]) {
            fprintf(stderr, "Allocation failed for slot %d\n", i);
            return 1;
        }
    }

    /* Initialize banner (slot 0) */
    strncpy(slots[0], BANNER, SLOT_SIZES[0] - 1);

    /* Initialize metadata (slot 1) */
    uint64_t *meta = (uint64_t *)slots[1];
    meta[0] = 0x0100;        /* sequence number */
    meta[1] = 0x02;          /* version */
    meta[2] = 0x65a1b2c3;   /* timestamp */
    meta[3] = INTEGRITY_SALT[0]; /* use salt to keep it in binary */

    /* Initialize data slots */
    for (i = 2; i < NUM_SLOTS; i++) {
        snprintf(slots[i], SLOT_SIZES[i], "SLOT%d:%s", i, SLOT_LABELS[i]);
    }

    /* Encrypt session token (slot 7) using audit key material.
     * This reference ensures the key data is preserved in the binary. */
    for (i = 0; i < 16 && (size_t)(i + 6) < SLOT_SIZES[7]; i++) {
        ((uint8_t *)slots[7])[6 + i] = audit_data.key[i];
    }

    printf("HeapService initialized: %d slots, marker=%s\n",
           NUM_SLOTS, audit_data.marker);

    /* Service loop would run here ... */

    /* Cleanup */
    for (i = 0; i < NUM_SLOTS; i++) {
        free(slots[i]);
    }

    return 0;
}
