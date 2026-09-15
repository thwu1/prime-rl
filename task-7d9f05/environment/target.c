#include <stdint.h>

#define MAGIC 0x4D455441u

typedef struct {
    uint32_t magic;
    uint16_t version;
    uint16_t count;
    uint32_t data_offset;
} __attribute__((packed)) Header;

typedef struct {
    uint16_t id;
    uint16_t flags;
    uint32_t value;
} __attribute__((packed)) Entry;

uint32_t hash_entries(const uint8_t *data, uint32_t size) {
    if (size < sizeof(Header))
        return 0;

    const Header *hdr = (const Header *)data;

    if (hdr->magic != MAGIC)
        return 0;

    if (hdr->version < 1 || hdr->version > 3)
        return 0;

    uint32_t hash = 5381;
    uint16_t n = hdr->count;

    for (uint16_t i = 0; i < n; i++) {
        uint32_t off = hdr->data_offset + i * sizeof(Entry);
        if (off + sizeof(Entry) > size)
            break;

        const Entry *e = (const Entry *)(data + off);

        hash = ((hash << 5) + hash) ^ e->id;
        hash = ((hash << 5) + hash) ^ e->value;

        if (hdr->version == 2) {
            hash ^= hash >> 16;
        } else if (hdr->version == 3) {
            hash *= 0x01000193u;
        }
    }

    hash ^= hash >> 13;
    hash *= 0x5bd1e995;
    hash ^= hash >> 15;

    return hash;
}

uint32_t feistel_round(uint32_t block, uint32_t key, int rounds) {
    uint32_t left = block >> 16;
    uint32_t right = block & 0xFFFF;

    for (int r = 0; r < rounds; r++) {
        uint32_t f = right;
        f = ((f << 5) | (f >> 27)) ^ key;
        f *= 0x9E3779B9;
        f ^= f >> 11;

        uint32_t nr = left ^ (f & 0xFFFF);
        left = right;
        right = nr;

        key += 0x61C88647;
    }

    return (left << 16) | right;
}
