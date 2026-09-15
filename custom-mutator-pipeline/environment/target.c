/*
 * XPROTO protocol parser - fuzzing target
 * Parses XPROTO binary messages from stdin or file argument.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <zlib.h>

#define MAGIC_0 0x58  /* 'X' */
#define MAGIC_1 0x50  /* 'P' */
#define MAGIC_2 0x52  /* 'R' */
#define MAGIC_3 0x01
#define HEADER_LEN 12
#define CRC_LEN 4

#define FLAG_COMPRESSED 0x0001
#define FLAG_CHECKSUM   0x0002
#define FLAG_EXTENDED   0x0004

#define TLV_STRING 0x01
#define TLV_INT32  0x02
#define TLV_NESTED 0x03
#define TLV_ARRAY  0x04
#define TLV_KEYVAL 0x05

#define MAX_DEPTH   4
#define MAX_ENTRIES 32
#define MAX_INPUT   (64 * 1024)

static int process_tlv(const uint8_t *data, size_t len,
                       uint16_t version, int depth) {
    if (depth > MAX_DEPTH) return -1;

    size_t offset = 0;
    int entry_count = 0;
    char str_buf[256];

    while (offset < len) {
        if (offset + 3 > len) return -1;

        uint8_t  type = data[offset];
        uint16_t vlen = (uint16_t)data[offset + 1] |
                        ((uint16_t)data[offset + 2] << 8);
        offset += 3;

        if (offset + vlen > len) return -1;

        const uint8_t *value = data + offset;
        offset += vlen;

        switch (type) {
        case TLV_STRING:
            /*
             * Process string entries.  Version-2 messages with a string
             * starting with "OVERFLOW" trigger an intentional copy into
             * a fixed-size stack buffer for fuzz-testing purposes.
             */
            if (version == 2 && vlen >= 8 &&
                memcmp(value, "OVERFLOW", 8) == 0) {
                memcpy(str_buf, value, vlen);
                str_buf[vlen] = '\0';
            }
            break;

        case TLV_INT32:
            if (vlen != 4) return -1;
            break;

        case TLV_NESTED:
            if (version < 2) return -1;
            if (process_tlv(value, vlen, version, depth + 1) < 0)
                return -1;
            break;

        case TLV_ARRAY:
            if (version < 2) return -1;
            if (vlen < 1) return -1;
            {
                uint8_t count = value[0];
                if ((uint16_t)count * 4 != vlen - 1) return -1;
            }
            break;

        case TLV_KEYVAL:
            if (version < 3) return -1;
            if (vlen < 1) return -1;
            {
                uint8_t key_len = value[0];
                if ((uint16_t)key_len + 1 > vlen) return -1;
            }
            break;

        default:
            return -1;
        }

        if (++entry_count > MAX_ENTRIES) return -1;
    }

    return entry_count;
}

int parse_xproto(const uint8_t *data, size_t len) {
    if (len < HEADER_LEN + CRC_LEN) return -1;

    if (data[0] != MAGIC_0 || data[1] != MAGIC_1 ||
        data[2] != MAGIC_2 || data[3] != MAGIC_3)
        return -1;

    uint16_t version = (uint16_t)data[4] | ((uint16_t)data[5] << 8);
    uint16_t flags   = (uint16_t)data[6] | ((uint16_t)data[7] << 8);
    uint32_t payload_len = (uint32_t)data[8]  | ((uint32_t)data[9]  << 8) |
                           ((uint32_t)data[10] << 16) | ((uint32_t)data[11] << 24);

    if (version < 1 || version > 3) return -1;
    if ((flags & FLAG_EXTENDED) && version < 3) return -1;
    if (HEADER_LEN + payload_len + CRC_LEN != len) return -1;

    if (flags & FLAG_CHECKSUM) {
        size_t crc_off = HEADER_LEN + payload_len;
        uint32_t stored = (uint32_t)data[crc_off]     |
                          ((uint32_t)data[crc_off + 1] << 8)  |
                          ((uint32_t)data[crc_off + 2] << 16) |
                          ((uint32_t)data[crc_off + 3] << 24);
        uint32_t computed = crc32(0L, data, HEADER_LEN + payload_len);
        if (stored != computed) return -1;
    }

    const uint8_t *payload = data + HEADER_LEN;
    size_t plen = payload_len;

    uint8_t *decompressed = NULL;
    if (flags & FLAG_COMPRESSED) {
        uLongf dest_len = MAX_INPUT;
        decompressed = (uint8_t *)malloc(dest_len);
        if (!decompressed) return -1;
        if (uncompress(decompressed, &dest_len, payload, plen) != Z_OK) {
            free(decompressed);
            return -1;
        }
        payload = decompressed;
        plen = (size_t)dest_len;
    }

    int result = process_tlv(payload, plen, version, 0);

    free(decompressed);
    return result;
}

int main(int argc, char *argv[]) {
    uint8_t buf[MAX_INPUT];
    size_t len;

    if (argc > 1) {
        FILE *f = fopen(argv[1], "rb");
        if (!f) { perror("fopen"); return 1; }
        len = fread(buf, 1, MAX_INPUT, f);
        fclose(f);
    } else {
        len = fread(buf, 1, MAX_INPUT, stdin);
    }

    int result = parse_xproto(buf, len);
    if (result >= 0) {
        printf("Valid XPROTO message with %d entries\n", result);
        return 0;
    } else {
        printf("Invalid XPROTO message\n");
        return 1;
    }
}
