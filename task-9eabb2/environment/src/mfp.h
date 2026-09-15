/*
 * mfp.h - Mini Format Parser library
 *
 * Parses a simple binary document format (MFP) with typed entries.
 *
 * Format:
 *   [4 bytes: magic 0x4D465000 "MFP\0"]
 *   [4 bytes: version uint32_le]
 *   [4 bytes: num_entries uint32_le]
 *   [4 bytes: flags uint32_le]
 *   For each entry:
 *     [4 bytes: type uint32_le]
 *     [4 bytes: name_len uint32_le]
 *     [name_len bytes: name string]
 *     [4 bytes: data_len uint32_le]
 *     [data_len bytes: data]
 */

#ifndef MFP_H
#define MFP_H

#include <stdint.h>
#include <stdlib.h>

#define MFP_MAGIC 0x4D465000

typedef struct {
    uint32_t type;
    uint32_t name_len;
    char *name;
    uint32_t data_len;
    uint8_t *data;
} mfp_entry_t;

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t num_entries;
    uint32_t flags;
    mfp_entry_t *entries;
} mfp_document_t;

int mfp_parse(const uint8_t *buf, size_t buf_len, mfp_document_t *doc);
char *mfp_render_summary(const mfp_document_t *doc);
int mfp_normalize(mfp_document_t *doc);
uint32_t mfp_compute_checksum(const mfp_document_t *doc);
void mfp_free(mfp_document_t *doc);

#endif /* MFP_H */
