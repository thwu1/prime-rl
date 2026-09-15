#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdint.h>

#define MAGIC_0 'M'
#define MAGIC_1 'L'
#define HEADER_SIZE 8

#define MSG_HELLO    0
#define MSG_DATA     1
#define MSG_ACK      2
#define MSG_ERROR    3
#define MSG_ROUTE    4
#define MSG_FRAGMENT 5

#define LFSR_POLY       0xB4BCD35Cu
#define LFSR_ZERO_SEED  0x0000ACE1u

static const char *msg_type_names[] = {
    "HELLO", "DATA", "ACK", "ERROR", "ROUTE", "FRAGMENT"
};

typedef enum {
    PKT_OK = 0,
    PKT_TRUNCATED_HEADER,
    PKT_TRUNCATED_PAYLOAD,
    PKT_INVALID_MAGIC,
    PKT_CRC_MISMATCH
} PktError;

typedef struct {
    uint8_t version;
    uint8_t msg_type;
    uint16_t payload_len;
    uint16_t crc_expected;
    uint16_t crc_computed;
    int crc_valid;
    const uint8_t *payload;
    size_t offset;
    PktError error;
    uint8_t magic[2];
} Packet;

typedef struct {
    Packet *packets;
    int count;
    int capacity;
} PacketList;

typedef struct {
    uint32_t msg_id;
    uint16_t frag_idx;
    uint16_t total;
    const uint8_t *data;
    size_t data_len;
    int orig_order;
} FragInfo;

typedef struct {
    int has_gap;
    uint32_t expected;
    uint32_t got;
    uint8_t channel;
} GapInfo;

static uint16_t crc16_ccitt(const uint8_t *data, size_t len) {
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int j = 0; j < 8; j++) {
            if (crc & 0x8000)
                crc = (crc << 1) ^ 0x1021;
            else
                crc = crc << 1;
        }
    }
    return crc & 0xFFFF;
}

static void lfsr_transform(uint8_t *out, const uint8_t *in, size_t len, uint32_t seed) {
    uint32_t st = seed ? seed : LFSR_ZERO_SEED;
    for (size_t i = 0; i < len; i++) {
        uint32_t lsb = st & 1u;
        st >>= 1;
        if (lsb) st ^= LFSR_POLY;
        out[i] = in[i] ^ (uint8_t)(st & 0xFFu);
    }
}

static uint16_t read_u16be(const uint8_t *p) {
    return ((uint16_t)p[0] << 8) | p[1];
}

static uint32_t read_u32be(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | p[3];
}

static uint8_t *read_file(const char *path, size_t *out_len) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "Error: cannot open '%s'\n", path);
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len < 0) { fclose(f); return NULL; }
    uint8_t *buf = malloc((size_t)len);
    if (!buf) { fclose(f); return NULL; }
    if (len > 0) {
        size_t r = fread(buf, 1, (size_t)len, f);
        (void)r;
    }
    fclose(f);
    *out_len = (size_t)len;
    return buf;
}

static void pl_init(PacketList *pl) {
    pl->packets = NULL;
    pl->count = 0;
    pl->capacity = 0;
}

static void pl_add(PacketList *pl, Packet p) {
    if (pl->count >= pl->capacity) {
        pl->capacity = pl->capacity ? pl->capacity * 2 : 16;
        pl->packets = realloc(pl->packets, (size_t)pl->capacity * sizeof(Packet));
    }
    pl->packets[pl->count++] = p;
}

static void pl_free(PacketList *pl) {
    free(pl->packets);
    pl->packets = NULL;
    pl->count = 0;
}

static void parse_packets(const uint8_t *data, size_t len, PacketList *pl) {
    size_t offset = 0;
    while (offset < len) {
        Packet pkt;
        memset(&pkt, 0, sizeof(pkt));
        pkt.offset = offset;

        if (offset + HEADER_SIZE > len) {
            pkt.error = PKT_TRUNCATED_HEADER;
            pl_add(pl, pkt);
            break;
        }

        if (data[offset] != MAGIC_0 || data[offset + 1] != MAGIC_1) {
            pkt.error = PKT_INVALID_MAGIC;
            pkt.magic[0] = data[offset];
            pkt.magic[1] = data[offset + 1];
            pl_add(pl, pkt);
            size_t next = offset + 1;
            while (next + 1 < len) {
                if (data[next] == MAGIC_0 && data[next + 1] == MAGIC_1)
                    break;
                next++;
            }
            if (next + 1 >= len) break;
            offset = next;
            continue;
        }

        pkt.version = data[offset + 2];
        pkt.msg_type = data[offset + 3];
        pkt.payload_len = read_u16be(&data[offset + 4]);
        pkt.crc_expected = read_u16be(&data[offset + 6]);

        if (offset + HEADER_SIZE + pkt.payload_len > len) {
            pkt.error = PKT_TRUNCATED_PAYLOAD;
            pl_add(pl, pkt);
            break;
        }

        pkt.payload = &data[offset + HEADER_SIZE];

        size_t crc_len = 4 + pkt.payload_len;
        uint8_t *crc_buf = malloc(crc_len);
        memcpy(crc_buf, &data[offset + 2], 4);
        if (pkt.payload_len > 0)
            memcpy(crc_buf + 4, pkt.payload, pkt.payload_len);
        pkt.crc_computed = crc16_ccitt(crc_buf, crc_len);
        free(crc_buf);

        pkt.crc_valid = (pkt.crc_expected == pkt.crc_computed);
        pkt.error = pkt.crc_valid ? PKT_OK : PKT_CRC_MISMATCH;

        pl_add(pl, pkt);
        offset += HEADER_SIZE + pkt.payload_len;
    }
}

static void print_hex(const uint8_t *data, size_t len) {
    for (size_t i = 0; i < len; i++)
        printf("%02x", data[i]);
}

static void decode_packet(int idx, const Packet *pkt, const GapInfo *gap) {
    printf("Packet #%d:\n", idx + 1);

    if (pkt->error == PKT_TRUNCATED_HEADER || pkt->error == PKT_TRUNCATED_PAYLOAD) {
        printf("  [TRUNCATED]\n\n");
        return;
    }
    if (pkt->error == PKT_INVALID_MAGIC) {
        printf("  [INVALID MAGIC: 0x%02x%02x]\n\n", pkt->magic[0], pkt->magic[1]);
        return;
    }

    const char *type_name = (pkt->msg_type <= MSG_FRAGMENT)
        ? msg_type_names[pkt->msg_type] : "UNKNOWN";
    printf("  Type: %s (%d)\n", type_name, pkt->msg_type);

    if (pkt->error == PKT_CRC_MISMATCH) {
        printf("  CRC: INVALID (expected 0x%04X, computed 0x%04X)\n",
               pkt->crc_expected, pkt->crc_computed);
        printf("  Payload: ");
        print_hex(pkt->payload, pkt->payload_len);
        printf(" (%d bytes)\n\n", pkt->payload_len);
        return;
    }

    const uint8_t *p = pkt->payload;
    uint16_t plen = pkt->payload_len;

    switch (pkt->msg_type) {
    case MSG_HELLO:
        if (plen < 4) { printf("  [MALFORMED PAYLOAD]\n\n"); return; }
        printf("  Node ID: 0x%08X\n", read_u32be(p));
        {
            const uint8_t *ns = p + 4;
            size_t nm = plen - 4;
            size_t nl = 0;
            while (nl < nm && ns[nl] != '\0') nl++;
            printf("  Node Name: \"%.*s\"\n", (int)nl, ns);
        }
        break;
    case MSG_DATA:
        if (plen < 5) { printf("  [MALFORMED PAYLOAD]\n\n"); return; }
        printf("  Channel: %d\n", p[0]);
        printf("  Sequence: %u\n", read_u32be(p + 1));
        if (gap && gap->has_gap) {
            printf("  [Sequence gap on channel %d: expected %u, got %u]\n",
                   gap->channel, gap->expected, gap->got);
        }
        {
            size_t dlen = plen - 5;
            if (p[0] & 0x80) {
                uint32_t seq = read_u32be(p + 1);
                uint8_t *unscr = malloc(dlen);
                lfsr_transform(unscr, p + 5, dlen, seq);
                printf("  Scrambled: yes\n");
                printf("  Data: ");
                print_hex(unscr, dlen);
                printf(" (%d bytes)\n", (int)dlen);
                free(unscr);
            } else {
                printf("  Data: ");
                print_hex(p + 5, dlen);
                printf(" (%d bytes)\n", (int)dlen);
            }
        }
        break;
    case MSG_ACK:
        if (plen < 4) { printf("  [MALFORMED PAYLOAD]\n\n"); return; }
        printf("  Sequence: %u\n", read_u32be(p));
        break;
    case MSG_ERROR:
        if (plen < 2) { printf("  [MALFORMED PAYLOAD]\n\n"); return; }
        printf("  Error Code: 0x%04X\n", read_u16be(p));
        printf("  Error Message: \"%.*s\"\n", (int)(plen - 2), p + 2);
        break;
    case MSG_ROUTE:
        if (plen < 1) { printf("  [MALFORMED PAYLOAD]\n\n"); return; }
        printf("  Hop Count: %d\n", p[0]);
        {
            size_t nd = plen - 1;
            int nn = (int)(nd / 4);
            printf("  Route: [");
            for (int i = 0; i < nn; i++) {
                if (i > 0) printf(", ");
                printf("0x%08X", read_u32be(p + 1 + i * 4));
            }
            printf("]\n");
        }
        break;
    case MSG_FRAGMENT:
        if (plen < 8) { printf("  [MALFORMED PAYLOAD]\n\n"); return; }
        printf("  Message ID: 0x%08X\n", read_u32be(p));
        printf("  Fragment: %d/%d\n", read_u16be(p + 4), read_u16be(p + 6));
        {
            size_t fdlen = plen - 8;
            printf("  Fragment Data: ");
            print_hex(p + 8, fdlen);
            printf(" (%d bytes)\n", (int)fdlen);
        }
        break;
    default:
        printf("  Payload: ");
        print_hex(p, plen);
        printf(" (%d bytes)\n", plen);
        break;
    }
    printf("\n");
}

static int cmd_decode(const char *filepath) {
    size_t len;
    uint8_t *data = read_file(filepath, &len);
    if (!data) return 1;
    PacketList pl;
    pl_init(&pl);
    parse_packets(data, len, &pl);

    int64_t ch_last_seq[256];
    for (int c = 0; c < 256; c++) ch_last_seq[c] = -1;

    for (int i = 0; i < pl.count; i++) {
        GapInfo gap = {0, 0, 0, 0};
        const Packet *pkt = &pl.packets[i];
        if (pkt->error == PKT_OK && pkt->msg_type == MSG_DATA && pkt->payload_len >= 5) {
            uint8_t ch = pkt->payload[0];
            uint32_t seq = read_u32be(pkt->payload + 1);
            if (ch_last_seq[ch] >= 0) {
                uint32_t expected = (uint32_t)ch_last_seq[ch] + 1;
                if (seq != expected) {
                    gap.has_gap = 1;
                    gap.expected = expected;
                    gap.got = seq;
                    gap.channel = ch;
                }
            }
            ch_last_seq[ch] = (int64_t)seq;
        }
        decode_packet(i, pkt, &gap);
    }
    pl_free(&pl);
    free(data);
    return 0;
}

static int cmd_validate(const char *filepath) {
    size_t len;
    uint8_t *data = read_file(filepath, &len);
    if (!data) return 1;
    PacketList pl;
    pl_init(&pl);
    parse_packets(data, len, &pl);
    int all_valid = 1;
    for (int i = 0; i < pl.count; i++) {
        const Packet *pkt = &pl.packets[i];
        switch (pkt->error) {
        case PKT_OK:
            printf("Packet #%d: OK\n", i + 1);
            break;
        case PKT_TRUNCATED_HEADER:
        case PKT_TRUNCATED_PAYLOAD:
            printf("Packet #%d: TRUNCATED\n", i + 1);
            all_valid = 0;
            break;
        case PKT_INVALID_MAGIC:
            printf("Packet #%d: INVALID_MAGIC (0x%02x%02x)\n",
                   i + 1, pkt->magic[0], pkt->magic[1]);
            all_valid = 0;
            break;
        case PKT_CRC_MISMATCH:
            printf("Packet #%d: CRC_MISMATCH (expected 0x%04X, computed 0x%04X)\n",
                   i + 1, pkt->crc_expected, pkt->crc_computed);
            all_valid = 0;
            break;
        }
    }
    pl_free(&pl);
    free(data);
    return all_valid ? 0 : 1;
}

static int cmd_stats(const char *filepath) {
    size_t len;
    uint8_t *data = read_file(filepath, &len);
    if (!data) return 1;
    PacketList pl;
    pl_init(&pl);
    parse_packets(data, len, &pl);
    int type_counts[7] = {0};
    int total_payload = 0;
    int invalid_count = 0;
    int scrambled_count = 0;
    for (int i = 0; i < pl.count; i++) {
        const Packet *pkt = &pl.packets[i];
        if (pkt->error == PKT_TRUNCATED_HEADER || pkt->error == PKT_TRUNCATED_PAYLOAD
            || pkt->error == PKT_INVALID_MAGIC) {
            invalid_count++;
            continue;
        }
        if (pkt->msg_type <= MSG_FRAGMENT)
            type_counts[pkt->msg_type]++;
        else
            type_counts[6]++;
        total_payload += pkt->payload_len;
        if (pkt->error == PKT_CRC_MISMATCH)
            invalid_count++;
        if (pkt->msg_type == MSG_DATA && pkt->error == PKT_OK
            && pkt->payload_len >= 5 && (pkt->payload[0] & 0x80))
            scrambled_count++;
    }
    printf("Total packets: %d\n", pl.count);
    for (int i = 0; i <= MSG_FRAGMENT; i++)
        printf("  %s: %d\n", msg_type_names[i], type_counts[i]);
    if (type_counts[6] > 0)
        printf("  UNKNOWN: %d\n", type_counts[6]);
    printf("Total payload bytes: %d\n", total_payload);
    printf("Invalid packets: %d\n", invalid_count);
    if (scrambled_count > 0)
        printf("Scrambled DATA packets: %d\n", scrambled_count);
    pl_free(&pl);
    free(data);
    return 0;
}

static int matches_filter(const Packet *pkt, const char *expr) {
    if (pkt->error != PKT_OK) return 0;
    char buf[512];
    strncpy(buf, expr, sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = '\0';
    char *saveptr;
    char *token = strtok_r(buf, ",", &saveptr);
    while (token) {
        while (*token == ' ') token++;
        char *eq = strchr(token, '=');
        if (!eq) { token = strtok_r(NULL, ",", &saveptr); continue; }
        *eq = '\0';
        char *key = token;
        char *val = eq + 1;
        char *ke = eq - 1;
        while (ke > key && *ke == ' ') { *ke = '\0'; ke--; }
        while (*val == ' ') val++;

        if (strcmp(key, "type") == 0) {
            const char *tn = (pkt->msg_type <= MSG_FRAGMENT)
                ? msg_type_names[pkt->msg_type] : "UNKNOWN";
            if (strcasecmp(tn, val) != 0) return 0;
        } else if (strcmp(key, "channel") == 0) {
            if (pkt->msg_type != MSG_DATA || pkt->payload_len < 5) return 0;
            if (pkt->payload[0] != (uint8_t)atoi(val)) return 0;
        } else if (strcmp(key, "seq") == 0) {
            uint32_t target = (uint32_t)strtoul(val, NULL, 0);
            if (pkt->msg_type == MSG_DATA) {
                if (pkt->payload_len < 5) return 0;
                if (read_u32be(pkt->payload + 1) != target) return 0;
            } else if (pkt->msg_type == MSG_ACK) {
                if (pkt->payload_len < 4) return 0;
                if (read_u32be(pkt->payload) != target) return 0;
            } else {
                return 0;
            }
        } else if (strcmp(key, "node_id") == 0) {
            if (pkt->msg_type != MSG_HELLO || pkt->payload_len < 4) return 0;
            uint32_t target = (uint32_t)strtoul(val, NULL, 0);
            if (read_u32be(pkt->payload) != target) return 0;
        } else if (strcmp(key, "error_code") == 0) {
            if (pkt->msg_type != MSG_ERROR || pkt->payload_len < 2) return 0;
            uint16_t target = (uint16_t)strtoul(val, NULL, 0);
            if (read_u16be(pkt->payload) != target) return 0;
        } else if (strcmp(key, "msg_id") == 0) {
            if (pkt->msg_type != MSG_FRAGMENT || pkt->payload_len < 8) return 0;
            uint32_t target = (uint32_t)strtoul(val, NULL, 0);
            if (read_u32be(pkt->payload) != target) return 0;
        } else if (strcmp(key, "hop_count") == 0) {
            if (pkt->msg_type != MSG_ROUTE || pkt->payload_len < 1) return 0;
            if (pkt->payload[0] != (uint8_t)atoi(val)) return 0;
        }
        token = strtok_r(NULL, ",", &saveptr);
    }
    return 1;
}

static int cmd_filter(const char *expr, const char *filepath) {
    size_t len;
    uint8_t *data = read_file(filepath, &len);
    if (!data) return 1;
    PacketList pl;
    pl_init(&pl);
    parse_packets(data, len, &pl);
    int midx = 0;
    for (int i = 0; i < pl.count; i++) {
        if (matches_filter(&pl.packets[i], expr)) {
            decode_packet(midx, &pl.packets[i], NULL);
            midx++;
        }
    }
    if (midx == 0)
        printf("No matching packets.\n");
    pl_free(&pl);
    free(data);
    return 0;
}

static int frag_cmp(const void *a, const void *b) {
    const FragInfo *fa = (const FragInfo *)a;
    const FragInfo *fb = (const FragInfo *)b;
    if (fa->msg_id != fb->msg_id)
        return (fa->msg_id < fb->msg_id) ? -1 : 1;
    if (fa->frag_idx != fb->frag_idx)
        return (fa->frag_idx < fb->frag_idx) ? -1 : 1;
    return fa->orig_order - fb->orig_order;
}

static int cmd_reassemble(const char *filepath) {
    size_t len;
    uint8_t *data = read_file(filepath, &len);
    if (!data) return 1;
    PacketList pl;
    pl_init(&pl);
    parse_packets(data, len, &pl);

    FragInfo *frags = NULL;
    int nfrags = 0, fcap = 0;

    for (int i = 0; i < pl.count; i++) {
        Packet *pkt = &pl.packets[i];
        if (pkt->error != PKT_OK) continue;
        if (pkt->msg_type != MSG_FRAGMENT) continue;
        if (pkt->payload_len < 8) continue;
        if (nfrags >= fcap) {
            fcap = fcap ? fcap * 2 : 16;
            frags = realloc(frags, (size_t)fcap * sizeof(FragInfo));
        }
        frags[nfrags].msg_id = read_u32be(pkt->payload);
        frags[nfrags].frag_idx = read_u16be(pkt->payload + 4);
        frags[nfrags].total = read_u16be(pkt->payload + 6);
        frags[nfrags].data = pkt->payload + 8;
        frags[nfrags].data_len = pkt->payload_len - 8;
        frags[nfrags].orig_order = nfrags;
        nfrags++;
    }

    if (nfrags == 0) {
        printf("No fragment packets found.\n");
        pl_free(&pl);
        free(data);
        return 0;
    }

    qsort(frags, (size_t)nfrags, sizeof(FragInfo), frag_cmp);

    int fi = 0;
    int first_msg = 1;
    while (fi < nfrags) {
        uint32_t cur_id = frags[fi].msg_id;
        int start = fi;
        while (fi < nfrags && frags[fi].msg_id == cur_id) fi++;
        int end = fi;

        /* Determine total: use maximum if fragments disagree */
        uint16_t total = frags[start].total;
        int has_conflict = 0;
        for (int j = start + 1; j < end; j++) {
            if (frags[j].total != frags[start].total) {
                has_conflict = 1;
                if (frags[j].total > total)
                    total = frags[j].total;
            }
        }

        if (!first_msg) printf("\n");
        first_msg = 0;

        int unique = 0;
        for (int j = start; j < end; j++) {
            if (j == start || frags[j].frag_idx != frags[j - 1].frag_idx)
                unique++;
        }

        printf("Message 0x%08X: ", cur_id);

        if ((uint16_t)unique >= total) {
            printf("COMPLETE (%d/%d)\n", total, total);
            printf("  ");
            size_t total_size = 0;
            for (int j = start; j < end; j++) {
                if (j > start && frags[j].frag_idx == frags[j - 1].frag_idx)
                    continue;
                print_hex(frags[j].data, frags[j].data_len);
                total_size += frags[j].data_len;
            }
            printf(" (%zu bytes)\n", total_size);
        } else {
            printf("INCOMPLETE (%d/%d, missing:", unique, total);
            int first = 1;
            for (uint16_t idx = 0; idx < total; idx++) {
                int found = 0;
                for (int j = start; j < end; j++) {
                    if (frags[j].frag_idx == idx) { found = 1; break; }
                }
                if (!found) {
                    if (!first) printf(",");
                    printf(" %d", idx);
                    first = 0;
                }
            }
            printf(")\n");
        }

        if (has_conflict) {
            printf("  [Warning: inconsistent fragment counts]\n");
        }
    }

    free(frags);
    pl_free(&pl);
    free(data);
    return 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: pktool <command> [args...]\n");
        fprintf(stderr, "Commands: decode, validate, stats, filter, reassemble\n");
        return 1;
    }
    if (strcmp(argv[1], "decode") == 0) {
        if (argc != 3) { fprintf(stderr, "Usage: pktool decode <file>\n"); return 1; }
        return cmd_decode(argv[2]);
    } else if (strcmp(argv[1], "validate") == 0) {
        if (argc != 3) { fprintf(stderr, "Usage: pktool validate <file>\n"); return 1; }
        return cmd_validate(argv[2]);
    } else if (strcmp(argv[1], "stats") == 0) {
        if (argc != 3) { fprintf(stderr, "Usage: pktool stats <file>\n"); return 1; }
        return cmd_stats(argv[2]);
    } else if (strcmp(argv[1], "filter") == 0) {
        if (argc != 4) { fprintf(stderr, "Usage: pktool filter <expr> <file>\n"); return 1; }
        return cmd_filter(argv[2], argv[3]);
    } else if (strcmp(argv[1], "reassemble") == 0) {
        if (argc != 3) { fprintf(stderr, "Usage: pktool reassemble <file>\n"); return 1; }
        return cmd_reassemble(argv[2]);
    } else {
        fprintf(stderr, "Unknown command: %s\n", argv[1]);
        return 1;
    }
}
