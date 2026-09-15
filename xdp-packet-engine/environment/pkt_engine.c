/* pkt_engine.c — XDP-style packet transformation engine (skeleton)
 *
 *
 * Reads hex-encoded Ethernet frames from stdin, applies a pipeline of
 * transformations, outputs transformed frames as hex to stdout.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <arpa/inet.h>

#define MAX_PKT_SIZE 65536
#define ETH_ALEN 6
#define ETH_P_IP     0x0800
#define ETH_P_IPV6   0x86DD
#define ETH_P_8021Q  0x8100
#define ETH_P_8021AD 0x88A8
#define PROTO_ICMP    1
#define PROTO_TCP     6
#define PROTO_UDP     17
#define PROTO_ICMPV6  58

/* Tag trailer constants */
#define TAG_MAGIC       0xD9F04B21
#define TAG_TRAILER_LEN 12
#define TAG_ROT_BITS    13
#define TAG_XOR_CONST   0xCAFE1337

/* ================================================================
 * Packet buffer
 * ================================================================ */
struct packet {
    uint8_t data[MAX_PKT_SIZE];
    size_t  len;
};

/* ================================================================
 * Header structures (packed, matching on-wire layout)
 * ================================================================ */
struct eth_hdr {
    uint8_t  dst[ETH_ALEN];
    uint8_t  src[ETH_ALEN];
    uint16_t proto;          /* network byte order */
} __attribute__((packed));

struct vlan_hdr {
    uint16_t tci;            /* PCP:3 DEI:1 VID:12, network byte order */
    uint16_t proto;          /* encapsulated EtherType, network byte order */
} __attribute__((packed));

struct ipv4_hdr {
    uint8_t  ver_ihl;        /* version:4, ihl:4 */
    uint8_t  tos;
    uint16_t tot_len;
    uint16_t id;
    uint16_t frag_off;
    uint8_t  ttl;
    uint8_t  protocol;
    uint16_t check;
    uint32_t saddr;
    uint32_t daddr;
} __attribute__((packed));

struct ipv6_hdr {
    uint32_t vtc_flow;       /* version:4 tc:8 flow:20, network byte order */
    uint16_t payload_len;
    uint8_t  nexthdr;
    uint8_t  hop_limit;
    uint8_t  saddr[16];
    uint8_t  daddr[16];
} __attribute__((packed));

struct icmp_hdr {
    uint8_t  type;
    uint8_t  code;
    uint16_t checksum;
    uint16_t id;
    uint16_t sequence;
} __attribute__((packed));

/* ================================================================
 * Hex I/O helpers (provided)
 * ================================================================ */
static int hex_to_bytes(const char *hex, uint8_t *out, size_t max_len)
{
    size_t hex_len = strlen(hex);
    while (hex_len > 0 && (hex[hex_len - 1] == '\n' || hex[hex_len - 1] == '\r'))
        hex_len--;
    if (hex_len % 2 != 0 || hex_len == 0)
        return -1;
    size_t byte_len = hex_len / 2;
    if (byte_len > max_len)
        return -1;
    for (size_t i = 0; i < byte_len; i++) {
        unsigned int b;
        if (sscanf(hex + 2 * i, "%2x", &b) != 1)
            return -1;
        out[i] = (uint8_t)b;
    }
    return (int)byte_len;
}

static void bytes_to_hex(const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++)
        printf("%02x", data[i]);
    printf("\n");
}

/* ================================================================
 * Checksum helper (provided)
 *
 * Computes the one's complement partial sum over a byte buffer.
 * Returns the folded 16-bit sum (NOT complemented).
 * To get a final checksum, use: checksum = ~csum_partial(buf, len)
 * ================================================================ */
static uint16_t csum_partial(const uint8_t *buf, size_t len)
{
    uint32_t sum = 0;
    while (len > 1) {
        sum += *(const uint16_t *)buf;
        buf += 2;
        len -= 2;
    }
    if (len)
        sum += *buf;
    while (sum >> 16)
        sum = (sum & 0xFFFF) + (sum >> 16);
    return (uint16_t)sum;
}

/* ================================================================
 * L3-header locator (provided)
 *
 * Skips Ethernet header and any 802.1Q / 802.1ad VLAN tags.
 * Sets *offset to the byte offset of the L3 header.
 * Returns the L3 EtherType (host byte order), or 0 on error.
 * ================================================================ */
static uint16_t find_l3(struct packet *pkt, size_t *offset)
{
    if (pkt->len < 14)
        return 0;
    struct eth_hdr *eth = (struct eth_hdr *)pkt->data;
    uint16_t proto = ntohs(eth->proto);
    *offset = 14;
    while ((proto == ETH_P_8021Q || proto == ETH_P_8021AD) &&
           *offset + 4 <= pkt->len) {
        struct vlan_hdr *vh = (struct vlan_hdr *)(pkt->data + *offset);
        proto = ntohs(vh->proto);
        *offset += 4;
    }
    return proto;
}

/* ================================================================
 * OPERATIONS — implement these seven functions
 * ================================================================ */

/*
 * Remove the outermost 802.1Q or 802.1ad VLAN tag.
 * Returns 0 on success, -1 if no VLAN tag is present.
 */
int op_vlan_pop(struct packet *pkt)
{
    /* TODO */
    (void)pkt;
    return -1;
}

/*
 * Insert an 802.1Q VLAN tag with the given VID (1–4094).
 * Returns 0 on success, -1 on error.
 */
int op_vlan_push(struct packet *pkt, uint16_t vid)
{
    /* TODO */
    (void)pkt;
    (void)vid;
    return -1;
}

/*
 * Convert an ICMP/ICMPv6 Echo Request into an Echo Reply.
 * Swap L2 and L3 addresses, change the ICMP type, recompute the
 * checksum.  ICMPv6 requires a pseudo-header per RFC 2460 §8.1.
 * Returns 0 on success, -1 if the packet is not an echo request.
 */
int op_echo_reply(struct packet *pkt)
{
    /* TODO */
    (void)pkt;
    return -1;
}

/*
 * L3 forward: rewrite destination and source MACs, decrement IPv4 TTL
 * or IPv6 hop limit (drop if it would reach zero), recompute affected
 * header checksums.
 * Returns 0 on success, -1 to drop.
 */
int op_forward(struct packet *pkt, const uint8_t *dst_mac, const uint8_t *src_mac)
{
    /* TODO */
    (void)pkt;
    (void)dst_mac;
    (void)src_mac;
    return -1;
}

/*
 * Drop the packet if its L4 protocol matches the given name.
 * Supported: "icmp", "icmp6", "tcp", "udp".
 * Returns 1 to drop, 0 to pass.
 */
int op_filter(struct packet *pkt, const char *proto_name)
{
    /* TODO */
    (void)pkt;
    (void)proto_name;
    return 0;
}

/*
 * Append a TAG_TRAILER_LEN-byte metadata trailer.
 * Returns 0 on success, -1 if the trailer would exceed MAX_PKT_SIZE.
 *
 * Trailer layout (big-endian):
 *   [0–3]  TAG_MAGIC
 *   [4–5]  key argument (uint16)
 *   [6–7]  L3 EtherType (from find_l3)
 *   [8–11] digest
 *
 * Digest: XOR-fold all 32-bit big-endian words of the current packet
 *   (zero-pad final partial word), rotate left TAG_ROT_BITS,
 *   XOR with TAG_XOR_CONST.
 */
int op_tag(struct packet *pkt, uint16_t key)
{
    /* TODO */
    (void)pkt;
    (void)key;
    return -1;
}

/*
 * Verify and strip the TAG_TRAILER_LEN-byte metadata trailer.
 * Check magic and recompute digest; drop on any mismatch.
 * Returns 0 on success, -1 to drop.
 */
int op_untag(struct packet *pkt)
{
    /* TODO */
    (void)pkt;
    return -1;
}

/* ================================================================
 * MAC address parser (provided)
 * ================================================================ */
static int parse_mac(const char *str, uint8_t *mac)
{
    unsigned int m[6];
    if (sscanf(str, "%x:%x:%x:%x:%x:%x",
               &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) != 6)
        return -1;
    for (int i = 0; i < 6; i++)
        mac[i] = (uint8_t)m[i];
    return 0;
}

/* ================================================================
 * Main — argument parsing and pipeline execution (provided)
 * ================================================================ */
enum op_type {
    OP_VLAN_POP,
    OP_VLAN_PUSH,
    OP_ECHO_REPLY,
    OP_FORWARD,
    OP_FILTER,
    OP_TAG,
    OP_UNTAG
};

struct operation {
    enum op_type type;
    uint16_t     vid;     /* also used as tag key */
    uint8_t      dst_mac[6];
    uint8_t      src_mac[6];
    char         proto[16];
};

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr,
                "Usage: %s <op> [args] [-- <op> [args] ...]\n"
                "Operations:\n"
                "  vlan-pop\n"
                "  vlan-push <VID>\n"
                "  echo-reply\n"
                "  forward <dst-mac> <src-mac>\n"
                "  filter <proto>\n"
                "  tag <key>\n"
                "  untag\n",
                argv[0]);
        return 1;
    }

    struct operation ops[64];
    int n_ops = 0;
    int i = 1;

    while (i < argc && n_ops < 64) {
        if (strcmp(argv[i], "--") == 0) {
            i++;
            continue;
        }
        if (strcmp(argv[i], "vlan-pop") == 0) {
            ops[n_ops++].type = OP_VLAN_POP;
        } else if (strcmp(argv[i], "vlan-push") == 0) {
            if (++i >= argc) {
                fprintf(stderr, "vlan-push requires VID\n");
                return 1;
            }
            ops[n_ops].type = OP_VLAN_PUSH;
            ops[n_ops].vid  = (uint16_t)atoi(argv[i]);
            n_ops++;
        } else if (strcmp(argv[i], "echo-reply") == 0) {
            ops[n_ops++].type = OP_ECHO_REPLY;
        } else if (strcmp(argv[i], "forward") == 0) {
            if (i + 2 >= argc) {
                fprintf(stderr, "forward requires dst-mac src-mac\n");
                return 1;
            }
            ops[n_ops].type = OP_FORWARD;
            parse_mac(argv[++i], ops[n_ops].dst_mac);
            parse_mac(argv[++i], ops[n_ops].src_mac);
            n_ops++;
        } else if (strcmp(argv[i], "filter") == 0) {
            if (++i >= argc) {
                fprintf(stderr, "filter requires proto\n");
                return 1;
            }
            ops[n_ops].type = OP_FILTER;
            strncpy(ops[n_ops].proto, argv[i], 15);
            ops[n_ops].proto[15] = '\0';
            n_ops++;
        } else if (strcmp(argv[i], "tag") == 0) {
            if (++i >= argc) {
                fprintf(stderr, "tag requires key\n");
                return 1;
            }
            ops[n_ops].type = OP_TAG;
            ops[n_ops].vid  = (uint16_t)atoi(argv[i]);
            n_ops++;
        } else if (strcmp(argv[i], "untag") == 0) {
            ops[n_ops++].type = OP_UNTAG;
        } else {
            fprintf(stderr, "Unknown operation: %s\n", argv[i]);
            return 1;
        }
        i++;
    }

    /* Process packets from stdin, one hex-encoded frame per line */
    char line[MAX_PKT_SIZE * 2 + 2];

    while (fgets(line, sizeof(line), stdin)) {
        struct packet pkt;
        int pkt_len = hex_to_bytes(line, pkt.data, MAX_PKT_SIZE);
        if (pkt_len < 0)
            continue;
        pkt.len = (size_t)pkt_len;

        int drop = 0;

        for (int j = 0; j < n_ops && !drop; j++) {
            int ret = 0;
            switch (ops[j].type) {
            case OP_VLAN_POP:
                ret = op_vlan_pop(&pkt);
                break;
            case OP_VLAN_PUSH:
                ret = op_vlan_push(&pkt, ops[j].vid);
                break;
            case OP_ECHO_REPLY:
                ret = op_echo_reply(&pkt);
                break;
            case OP_FORWARD:
                ret = op_forward(&pkt, ops[j].dst_mac, ops[j].src_mac);
                break;
            case OP_FILTER:
                drop = op_filter(&pkt, ops[j].proto);
                break;
            case OP_TAG:
                ret = op_tag(&pkt, ops[j].vid);
                break;
            case OP_UNTAG:
                ret = op_untag(&pkt);
                break;
            }
            if (ret < 0)
                drop = 1;
        }

        if (!drop)
            bytes_to_hex(pkt.data, pkt.len);
    }

    return 0;
}
