#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ndp.h"

static int parse_packet(const uint8_t *data, size_t file_size) {
    if (file_size < NDP_HEADER_SIZE) {
        fprintf(stderr, "Error: file too small for NDP header\n");
        return 1;
    }

    uint32_t magic = read_u32_be(data);
    if (magic != NDP_MAGIC) {
        fprintf(stderr, "Error: invalid magic 0x%08X (expected 0x%08X)\n",
                magic, NDP_MAGIC);
        return 1;
    }

    uint8_t type = data[4];
    uint8_t flags = data[5];
    uint16_t payload_len = read_u16_be(data + 6);
    uint32_t checksum = read_u32_be(data + 8);

    if ((size_t)NDP_HEADER_SIZE + payload_len > file_size) {
        fprintf(stderr, "Error: payload extends past file end (%u + %u > %zu)\n",
                NDP_HEADER_SIZE, payload_len, file_size);
        return 1;
    }

    const uint8_t *payload = data + NDP_HEADER_SIZE;

    /* Verify CRC32 checksum */
    uint32_t computed = ndp_crc32(payload, payload_len);
    if (computed != checksum) {
        fprintf(stderr, "Error: CRC32 mismatch (computed 0x%08X, header 0x%08X)\n",
                computed, checksum);
        return 1;
    }

    if (flags & NDP_FLAG_VERBOSE) {
        fprintf(stderr, "NDP: type=0x%02X flags=0x%02X payload_len=%u checksum=0x%08X\n",
                type, flags, payload_len, checksum);
    }

    int ret;
    switch (type) {
        case NDP_PROBE:
            ret = handle_probe(payload, payload_len, flags);
            break;
        case NDP_IDENT:
            ret = handle_ident(payload, payload_len, flags);
            break;
        case NDP_AUTH:
            ret = handle_auth(payload, payload_len, flags);
            break;
        case NDP_BULK:
            ret = handle_bulk(payload, payload_len, flags);
            break;
        case NDP_DIAG:
            ret = handle_diag(payload, payload_len, flags);
            break;
        default:
            fprintf(stderr, "Warning: unknown packet type 0x%02X\n", type);
            ret = 0;
            break;
    }

    return (ret < 0) ? 1 : 0;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <packet_file>\n", argv[0]);
        return 1;
    }

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        perror("fopen");
        return 1;
    }

    fseek(f, 0, SEEK_END);
    long fsize = ftell(f);
    fseek(f, 0, SEEK_SET);

    if (fsize <= 0 || fsize > 1024 * 1024) {
        fprintf(stderr, "Error: invalid file size %ld\n", fsize);
        fclose(f);
        return 1;
    }

    uint8_t *data = malloc((size_t)fsize);
    if (!data) {
        fprintf(stderr, "Error: out of memory\n");
        fclose(f);
        return 1;
    }

    if (fread(data, 1, (size_t)fsize, f) != (size_t)fsize) {
        fprintf(stderr, "Error: read failed\n");
        free(data);
        fclose(f);
        return 1;
    }
    fclose(f);

    int result = parse_packet(data, (size_t)fsize);

    free(data);
    return result;
}
