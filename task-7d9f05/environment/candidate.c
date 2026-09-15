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
    const Header *hdr = (const Header *)data;
    if (size < sizeof(Header) || hdr->magic != MAGIC)
        return 0;

    if (!(hdr->version >= 1 && hdr->version <= 3))
        return 0;

    uint32_t hash = 5381;

    for (int i = 0; i < hdr->count; i++) {
        uint32_t off = hdr->data_offset + i * sizeof(Entry);
        if (off + sizeof(Entry) > size)
            break;

        const Entry *e = (const Entry *)(&data[off]);

        hash = hash * 33 ^ e->id;
        hash = hash * 33 ^ e->value;

        switch (hdr->version) {
            case 2:
                hash ^= hash >> 16;
                break;
            case 3:
                hash *= 0x01000193u;
                break;
        }
    }

    hash ^= (hash >> 13);
    hash *= 0x5BD1E995;
    hash ^= (hash >> 15);

    return (hash);
}

uint32_t feistel_round(uint32_t block, uint32_t key, int rounds) {
    unsigned int left = block >> 16;
    unsigned int right = block & 0xFFFF;

    for (int r = 0; r < rounds; r++) {
        uint32_t f = right;
        uint32_t rot = (f << 5) | (f >> 27);
        f = rot ^ key;
        f = f * 0x9E3779B9;
        f = f ^ (f >> 11);

        left = left ^ (f & 0xFFFF);
        uint32_t tmp = left;
        left = right;
        right = tmp;

        key = key + 0x61C88647;
    }

    return ((left << 16) | right);
}
