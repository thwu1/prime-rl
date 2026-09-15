/*
 * TKV1 Flash Key-Value Store — Reference Implementation
 *
 * Log-structured key-value storage for NOR flash memory.
 * Designed for crash consistency on embedded devices.
 *
 */

#ifndef TICKV_H
#define TICKV_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

/* ---------- Flash geometry ---------- */
#define TKV_PAGE_SIZE       4096
#define TKV_MAX_PAGES       256
#define TKV_MAX_KEY_LEN     255
#define TKV_MAX_ENTRIES     1024

/* ---------- On-flash constants ---------- */
#define TKV_PAGE_MAGIC      0x31564B54u   /* byte sequence: 54 4B 56 31 */
#define TKV_ENTRY_MAGIC     0x73AEu       /* byte sequence: AE 73       */

/* Page status (transitions respect flash AND-write semantics) */
#define TKV_PAGE_ERASED     0xFF
#define TKV_PAGE_ACTIVE     0x0F
#define TKV_PAGE_FULL       0x00

/* Entry state */
#define TKV_ENTRY_VALID     0x0F
#define TKV_ENTRY_INVALID   0x00

/* Header sizes */
#define TKV_PAGE_HDR_SIZE   12
#define TKV_ENTRY_HDR_SIZE  16

/* ---------- On-flash structures (packed, little-endian) ---------- */

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint8_t  status;
    uint16_t sequence;
    uint8_t  _reserved;     /* always 0xFF */
    uint32_t erase_count;
} tkv_page_hdr_t;

typedef struct __attribute__((packed)) {
    uint16_t magic;
    uint8_t  state;
    uint8_t  key_len;
    uint32_t value_len;
    uint32_t key_hash;
    uint32_t crc;
} tkv_entry_hdr_t;

/* ---------- In-memory bookkeeping ---------- */

typedef struct {
    uint8_t  key[TKV_MAX_KEY_LEN];
    uint8_t  *value;
    uint8_t  key_len;
    uint32_t value_len;
    int      page;
    int      offset;
} tkv_entry_t;

typedef struct {
    uint8_t  *flash;
    int      num_pages;
    uint32_t erase_counts[TKV_MAX_PAGES];
    int      active_page;
    int      write_offset;
    uint16_t next_seq;
    tkv_entry_t entries[TKV_MAX_ENTRIES];
    int      entry_count;
} tkv_store_t;

/* ---------- Public API ---------- */

int      tkv_open(tkv_store_t *store, uint8_t *flash, int num_pages);
void     tkv_format(tkv_store_t *store);
int      tkv_put(tkv_store_t *store, const uint8_t *key, uint8_t key_len,
                 const uint8_t *value, uint32_t value_len);
int      tkv_get(tkv_store_t *store, const uint8_t *key, uint8_t key_len,
                 uint8_t **value_out, uint32_t *value_len_out);
int      tkv_delete(tkv_store_t *store, const uint8_t *key, uint8_t key_len);
void     tkv_compact(tkv_store_t *store);
int      tkv_list_keys(tkv_store_t *store,
                       void (*cb)(const uint8_t *key, uint8_t key_len));

/* ---------- Utilities ---------- */

uint32_t tkv_key_hash(const uint8_t *data, size_t len);
uint32_t tkv_crc32(const uint8_t *data, size_t len);
uint32_t tkv_entry_crc(uint8_t key_len, uint32_t value_len,
                       uint32_t key_hash,
                       const uint8_t *key, const uint8_t *value);

#endif /* TICKV_H */
