/*
 * TKV1 Flash Key-Value Store — Core Implementation
 *
 */

#include "tickv.h"
#include <string.h>
#include <stdlib.h>

/* ================================================================
 * CRC-32 (polynomial 0xEDB88320, same as zlib / ISO 3309)
 * ================================================================ */

static uint32_t crc_tbl[256];
static int      crc_ready = 0;

static void crc_build_table(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int j = 0; j < 8; j++)
            c = (c >> 1) ^ ((c & 1) ? 0xEDB88320u : 0);
        crc_tbl[i] = c;
    }
    crc_ready = 1;
}

uint32_t tkv_crc32(const uint8_t *data, size_t len) {
    if (!crc_ready) crc_build_table();
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++)
        crc = (crc >> 8) ^ crc_tbl[(crc ^ data[i]) & 0xFF];
    return crc ^ 0xFFFFFFFFu;
}

static uint32_t crc_begin(void) {
    if (!crc_ready) crc_build_table();
    return 0xFFFFFFFFu;
}

static uint32_t crc_feed(uint32_t c, const uint8_t *d, size_t n) {
    for (size_t i = 0; i < n; i++)
        c = (c >> 8) ^ crc_tbl[(c ^ d[i]) & 0xFF];
    return c;
}

static uint32_t crc_end(uint32_t c) { return c ^ 0xFFFFFFFFu; }

/* ================================================================
 * Key hash
 * ================================================================ */

uint32_t tkv_key_hash(const uint8_t *data, size_t len) {
    uint32_t h = 0x811c9dc5u;
    for (size_t i = 0; i < len; i++) {
        h ^= data[i];
        h *= 0x01000193u;
    }
    return h;
}

/* ================================================================
 * Entry CRC — covers everything EXCEPT the state byte so that
 * invalidation (clearing state from 0x0F to 0x00) does not
 * require recomputing or rewriting the checksum.
 *
 * Fields covered (concatenated in this order):
 *   key_len    (1 byte)
 *   value_len  (4 bytes, little-endian)
 *   key_hash   (4 bytes, little-endian)
 *   key data   (key_len bytes)
 *   value data (value_len bytes)
 * ================================================================ */

uint32_t tkv_entry_crc(uint8_t key_len, uint32_t value_len,
                       uint32_t key_hash,
                       const uint8_t *key, const uint8_t *value) {
    uint32_t c = crc_begin();

    c = crc_feed(c, &key_len, 1);

    uint8_t vl[4] = { value_len        & 0xFF,
                      (value_len >> 8)  & 0xFF,
                      (value_len >> 16) & 0xFF,
                      (value_len >> 24) & 0xFF };
    c = crc_feed(c, vl, 4);

    uint8_t kh[4] = { key_hash        & 0xFF,
                      (key_hash >> 8)  & 0xFF,
                      (key_hash >> 16) & 0xFF,
                      (key_hash >> 24) & 0xFF };
    c = crc_feed(c, kh, 4);

    c = crc_feed(c, key, key_len);
    if (value_len > 0)
        c = crc_feed(c, value, value_len);

    return crc_end(c);
}

/* ================================================================
 * Flash helpers (simulated NOR semantics)
 * ================================================================ */

static uint8_t *pg(tkv_store_t *s, int p) {
    return s->flash + p * TKV_PAGE_SIZE;
}

static void fl_write(tkv_store_t *s, int off, const uint8_t *d, int n) {
    for (int i = 0; i < n; i++)
        s->flash[off + i] &= d[i];          /* NOR: bits can only go 1→0 */
}

static void fl_erase(tkv_store_t *s, int p) {
    memset(pg(s, p), 0xFF, TKV_PAGE_SIZE);
    s->erase_counts[p]++;
}

static void write_phdr(tkv_store_t *s, int p,
                       uint8_t status, uint16_t seq, uint32_t ec) {
    tkv_page_hdr_t h;
    h.magic       = TKV_PAGE_MAGIC;
    h.status      = status;
    h.sequence    = seq;
    h._reserved   = 0xFF;
    h.erase_count = ec;
    fl_write(s, p * TKV_PAGE_SIZE, (uint8_t *)&h, sizeof(h));
}

/* ================================================================
 * Index helpers
 * ================================================================ */

static int find_idx(tkv_store_t *s, const uint8_t *key, uint8_t kl) {
    for (int i = 0; i < s->entry_count; i++)
        if (s->entries[i].key_len == kl &&
            memcmp(s->entries[i].key, key, kl) == 0)
            return i;
    return -1;
}

static void drop_idx(tkv_store_t *s, int i) {
    if (s->entries[i].value) free(s->entries[i].value);
    if (i < s->entry_count - 1)
        s->entries[i] = s->entries[s->entry_count - 1];
    s->entry_count--;
}

/* ================================================================
 * Recovery / open
 * ================================================================ */

int tkv_open(tkv_store_t *store, uint8_t *flash, int num_pages) {
    memset(store, 0, sizeof(*store));
    store->flash       = flash;
    store->num_pages   = num_pages;
    store->active_page = -1;
    store->next_seq    = 0;

    /* --- pass 1: discover initialized pages --- */
    typedef struct { int p; uint16_t seq; uint8_t st; } pi_t;
    pi_t plist[TKV_MAX_PAGES];
    int  pcnt = 0;

    for (int p = 0; p < num_pages; p++) {
        tkv_page_hdr_t *ph = (tkv_page_hdr_t *)pg(store, p);
        if (ph->magic != TKV_PAGE_MAGIC)  continue;
        if (ph->status == TKV_PAGE_ERASED) continue;

        store->erase_counts[p] = ph->erase_count;
        plist[pcnt].p   = p;
        plist[pcnt].seq = ph->sequence;
        plist[pcnt].st  = ph->status;
        pcnt++;

        if (ph->sequence >= store->next_seq)
            store->next_seq = ph->sequence + 1;
    }

    /* sort by sequence ascending (insertion sort) */
    for (int i = 1; i < pcnt; i++) {
        pi_t tmp = plist[i];
        int j = i - 1;
        while (j >= 0 && plist[j].seq > tmp.seq) {
            plist[j + 1] = plist[j];
            j--;
        }
        plist[j + 1] = tmp;
    }

    /* --- pass 2: scan entries per page --- */
    for (int pi = 0; pi < pcnt; pi++) {
        int p   = plist[pi].p;
        int off = TKV_PAGE_HDR_SIZE;

        while (off + TKV_ENTRY_HDR_SIZE <= TKV_PAGE_SIZE) {
            tkv_entry_hdr_t *eh = (tkv_entry_hdr_t *)(pg(store, p) + off);
            if (eh->magic != TKV_ENTRY_MAGIC) break;
            if (eh->key_len == 0)             break;

            int total = TKV_ENTRY_HDR_SIZE + eh->key_len + eh->value_len;
            if (off + total > TKV_PAGE_SIZE)  break;

            uint8_t *k = pg(store, p) + off + TKV_ENTRY_HDR_SIZE;
            uint8_t *v = k + eh->key_len;

            uint32_t check = tkv_entry_crc(eh->key_len, eh->value_len,
                                           eh->key_hash, k, v);
            if (check != eh->crc) break;   /* corruption — stop this page */

            int idx = find_idx(store, k, eh->key_len);

            if (eh->state == TKV_ENTRY_VALID) {
                if (idx >= 0) {
                    if (store->entries[idx].value)
                        free(store->entries[idx].value);
                    store->entries[idx].value =
                        (eh->value_len > 0) ? malloc(eh->value_len) : NULL;
                    if (eh->value_len > 0)
                        memcpy(store->entries[idx].value, v, eh->value_len);
                    store->entries[idx].value_len = eh->value_len;
                    store->entries[idx].page   = p;
                    store->entries[idx].offset = off;
                } else {
                    tkv_entry_t *e = &store->entries[store->entry_count++];
                    memcpy(e->key, k, eh->key_len);
                    e->key_len   = eh->key_len;
                    e->value     = (eh->value_len > 0) ? malloc(eh->value_len) : NULL;
                    if (eh->value_len > 0)
                        memcpy(e->value, v, eh->value_len);
                    e->value_len = eh->value_len;
                    e->page      = p;
                    e->offset    = off;
                }
            } else if (eh->state == TKV_ENTRY_INVALID) {
                if (idx >= 0) drop_idx(store, idx);
            }

            off += total;
        }

        if (plist[pi].st == TKV_PAGE_ACTIVE) {
            store->active_page  = p;
            store->write_offset = off;
        }
    }

    return 0;
}

/* ================================================================
 * Format
 * ================================================================ */

void tkv_format(tkv_store_t *store) {
    for (int i = 0; i < store->num_pages; i++)
        fl_erase(store, i);

    for (int i = 0; i < store->entry_count; i++)
        if (store->entries[i].value) free(store->entries[i].value);
    store->entry_count = 0;

    write_phdr(store, 0, TKV_PAGE_ACTIVE, 0, store->erase_counts[0]);
    store->active_page  = 0;
    store->write_offset = TKV_PAGE_HDR_SIZE;
    store->next_seq     = 1;
}

/* ================================================================
 * Page activation
 * ================================================================ */

static int activate_next(tkv_store_t *s) {
    if (s->active_page >= 0) {
        int soff = s->active_page * TKV_PAGE_SIZE + 4;
        uint8_t full = TKV_PAGE_FULL;
        fl_write(s, soff, &full, 1);
    }
    for (int p = 0; p < s->num_pages; p++) {
        if (pg(s, p)[0] == 0xFF) {       /* erased page */
            uint16_t seq = s->next_seq++;
            write_phdr(s, p, TKV_PAGE_ACTIVE, seq, s->erase_counts[p]);
            s->active_page  = p;
            s->write_offset = TKV_PAGE_HDR_SIZE;
            return p;
        }
    }
    s->active_page = -1;
    return -1;
}

/* ================================================================
 * PUT
 * ================================================================ */

int tkv_put(tkv_store_t *store, const uint8_t *key, uint8_t key_len,
            const uint8_t *value, uint32_t value_len) {
    int total = TKV_ENTRY_HDR_SIZE + key_len + value_len;
    if (total > TKV_PAGE_SIZE - TKV_PAGE_HDR_SIZE) return -1;

    if (store->active_page >= 0) {
        if (store->write_offset + total > TKV_PAGE_SIZE)
            if (activate_next(store) < 0) return -1;
    } else {
        if (activate_next(store) < 0) return -1;
    }

    /* invalidate previous entry for this key */
    int idx = find_idx(store, key, key_len);
    if (idx >= 0) {
        int soff = store->entries[idx].page * TKV_PAGE_SIZE
                 + store->entries[idx].offset + 2;
        uint8_t inv = TKV_ENTRY_INVALID;
        fl_write(store, soff, &inv, 1);
    }

    /* build header */
    uint32_t kh  = tkv_key_hash(key, key_len);
    uint32_t crc = tkv_entry_crc(key_len, value_len, kh, key, value);

    tkv_entry_hdr_t hdr;
    hdr.magic     = TKV_ENTRY_MAGIC;
    hdr.state     = TKV_ENTRY_VALID;
    hdr.key_len   = key_len;
    hdr.value_len = value_len;
    hdr.key_hash  = kh;
    hdr.crc       = crc;

    int wpos = store->active_page * TKV_PAGE_SIZE + store->write_offset;
    fl_write(store, wpos, (uint8_t *)&hdr, sizeof(hdr));
    fl_write(store, wpos + TKV_ENTRY_HDR_SIZE, key, key_len);
    if (value_len > 0)
        fl_write(store, wpos + TKV_ENTRY_HDR_SIZE + key_len, value, value_len);

    /* update index */
    if (idx >= 0) {
        if (store->entries[idx].value) free(store->entries[idx].value);
        store->entries[idx].value =
            (value_len > 0) ? malloc(value_len) : NULL;
        if (value_len > 0) memcpy(store->entries[idx].value, value, value_len);
        store->entries[idx].value_len = value_len;
        store->entries[idx].page      = store->active_page;
        store->entries[idx].offset    = store->write_offset;
    } else {
        tkv_entry_t *e = &store->entries[store->entry_count++];
        memcpy(e->key, key, key_len);
        e->key_len   = key_len;
        e->value     = (value_len > 0) ? malloc(value_len) : NULL;
        if (value_len > 0) memcpy(e->value, value, value_len);
        e->value_len = value_len;
        e->page      = store->active_page;
        e->offset    = store->write_offset;
    }

    store->write_offset += total;
    return 0;
}

/* ================================================================
 * GET
 * ================================================================ */

int tkv_get(tkv_store_t *store, const uint8_t *key, uint8_t key_len,
            uint8_t **value_out, uint32_t *value_len_out) {
    int idx = find_idx(store, key, key_len);
    if (idx < 0) return -1;
    *value_out     = store->entries[idx].value;
    *value_len_out = store->entries[idx].value_len;
    return 0;
}

/* ================================================================
 * DELETE
 * ================================================================ */

int tkv_delete(tkv_store_t *store, const uint8_t *key, uint8_t key_len) {
    int idx = find_idx(store, key, key_len);
    if (idx < 0) return -1;
    int soff = store->entries[idx].page * TKV_PAGE_SIZE
             + store->entries[idx].offset + 2;
    uint8_t inv = TKV_ENTRY_INVALID;
    fl_write(store, soff, &inv, 1);
    drop_idx(store, idx);
    return 0;
}

/* ================================================================
 * COMPACT — collect live entries, erase everything, rewrite
 * ================================================================ */

void tkv_compact(tkv_store_t *store) {
    int cnt = store->entry_count;
    tkv_entry_t *snap = NULL;
    if (cnt > 0) {
        snap = malloc(cnt * sizeof(tkv_entry_t));
        for (int i = 0; i < cnt; i++) {
            snap[i] = store->entries[i];
            snap[i].value = NULL;
            if (store->entries[i].value_len > 0) {
                snap[i].value = malloc(store->entries[i].value_len);
                memcpy(snap[i].value, store->entries[i].value,
                       store->entries[i].value_len);
            }
        }
    }

    for (int i = 0; i < store->num_pages; i++)
        fl_erase(store, i);

    for (int i = 0; i < store->entry_count; i++)
        if (store->entries[i].value) free(store->entries[i].value);
    store->entry_count = 0;
    store->next_seq    = 0;

    write_phdr(store, 0, TKV_PAGE_ACTIVE, 0, store->erase_counts[0]);
    store->active_page  = 0;
    store->write_offset = TKV_PAGE_HDR_SIZE;
    store->next_seq     = 1;

    for (int i = 0; i < cnt; i++) {
        tkv_put(store, snap[i].key, snap[i].key_len,
                snap[i].value, snap[i].value_len);
        if (snap[i].value) free(snap[i].value);
    }
    if (snap) free(snap);
}

/* ================================================================
 * LIST KEYS
 * ================================================================ */

int tkv_list_keys(tkv_store_t *store,
                  void (*cb)(const uint8_t *key, uint8_t key_len)) {
    for (int i = 0; i < store->entry_count; i++)
        cb(store->entries[i].key, store->entries[i].key_len);
    return store->entry_count;
}
