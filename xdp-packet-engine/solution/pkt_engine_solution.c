/* pkt_engine.c — XDP-style packet transformation engine (complete solution)
 *
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

struct packet {
    uint8_t data[MAX_PKT_SIZE];
    size_t  len;
};

struct eth_hdr {
    uint8_t  dst[ETH_ALEN];
    uint8_t  src[ETH_ALEN];
    uint16_t proto;
} __attribute__((packed));

struct vlan_hdr {
    uint16_t tci;
    uint16_t proto;
} __attribute__((packed));

struct ipv4_hdr {
    uint8_t  ver_ihl;
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
    uint32_t vtc_flow;
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

/* ---- Hex I/O ---- */

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

/* ---- Checksum ---- */

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

/* ---- L3 finder ---- */

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

/* ---- Tag digest computation ---- */

static uint32_t compute_tag_digest(const uint8_t *data, size_t len)
{
    uint32_t fold = 0;
    size_t i;
    /* XOR-fold all complete 32-bit big-endian words */
    for (i = 0; i + 4 <= len; i += 4) {
        uint32_t word = ((uint32_t)data[i] << 24) |
                        ((uint32_t)data[i + 1] << 16) |
                        ((uint32_t)data[i + 2] << 8) |
                        ((uint32_t)data[i + 3]);
        fold ^= word;
    }
    /* Handle remaining 1–3 bytes, zero-padded to 4 bytes */
    if (i < len) {
        uint32_t word = 0;
        size_t rem = len - i;
        if (rem >= 1) word |= (uint32_t)data[i] << 24;
        if (rem >= 2) word |= (uint32_t)data[i + 1] << 16;
        if (rem >= 3) word |= (uint32_t)data[i + 2] << 8;
        fold ^= word;
    }
    /* Rotate left by TAG_ROT_BITS */
    fold = (fold << TAG_ROT_BITS) | (fold >> (32 - TAG_ROT_BITS));
    /* XOR with constant */
    fold ^= TAG_XOR_CONST;
    return fold;
}

/* ================================================================
 * OPERATIONS — full implementations
 * ================================================================ */

int op_vlan_pop(struct packet *pkt)
{
    if (pkt->len < 18)
        return -1;
    struct eth_hdr *eth = (struct eth_hdr *)pkt->data;
    uint16_t proto = ntohs(eth->proto);
    if (proto != ETH_P_8021Q && proto != ETH_P_8021AD)
        return -1;

    memmove(pkt->data + 4, pkt->data, 12);
    pkt->len -= 4;
    memmove(pkt->data, pkt->data + 4, pkt->len);

    return 0;
}

int op_vlan_push(struct packet *pkt, uint16_t vid)
{
    if (pkt->len + 4 > MAX_PKT_SIZE || pkt->len < 14)
        return -1;

    memmove(pkt->data + 16, pkt->data + 12, pkt->len - 12);
    *(uint16_t *)(pkt->data + 12) = htons(ETH_P_8021Q);
    *(uint16_t *)(pkt->data + 14) = htons(vid & 0x0FFF);
    pkt->len += 4;
    return 0;
}

int op_echo_reply(struct packet *pkt)
{
    size_t l3_off;
    uint16_t l3_proto = find_l3(pkt, &l3_off);

    struct eth_hdr *eth = (struct eth_hdr *)pkt->data;
    uint8_t tmp_mac[ETH_ALEN];
    memcpy(tmp_mac, eth->dst, ETH_ALEN);
    memcpy(eth->dst, eth->src, ETH_ALEN);
    memcpy(eth->src, tmp_mac, ETH_ALEN);

    if (l3_proto == ETH_P_IP) {
        if (l3_off + sizeof(struct ipv4_hdr) > pkt->len)
            return -1;
        struct ipv4_hdr *ip = (struct ipv4_hdr *)(pkt->data + l3_off);
        if (ip->protocol != PROTO_ICMP)
            return -1;

        size_t ihl = (ip->ver_ihl & 0x0F) * 4;
        size_t icmp_off = l3_off + ihl;
        if (icmp_off + 8 > pkt->len)
            return -1;
        struct icmp_hdr *icmp = (struct icmp_hdr *)(pkt->data + icmp_off);
        if (icmp->type != 8)
            return -1;

        uint32_t tmp_ip = ip->saddr;
        ip->saddr = ip->daddr;
        ip->daddr = tmp_ip;

        icmp->type = 0;

        size_t icmp_len = pkt->len - icmp_off;
        icmp->checksum = 0;
        icmp->checksum = ~csum_partial(pkt->data + icmp_off, icmp_len);

        return 0;

    } else if (l3_proto == ETH_P_IPV6) {
        if (l3_off + sizeof(struct ipv6_hdr) > pkt->len)
            return -1;
        struct ipv6_hdr *ip6 = (struct ipv6_hdr *)(pkt->data + l3_off);
        if (ip6->nexthdr != PROTO_ICMPV6)
            return -1;

        size_t icmp_off = l3_off + 40;
        if (icmp_off + 8 > pkt->len)
            return -1;
        struct icmp_hdr *icmp = (struct icmp_hdr *)(pkt->data + icmp_off);
        if (icmp->type != 128)
            return -1;

        uint8_t tmp_addr[16];
        memcpy(tmp_addr, ip6->saddr, 16);
        memcpy(ip6->saddr, ip6->daddr, 16);
        memcpy(ip6->daddr, tmp_addr, 16);

        icmp->type = 129;

        size_t icmp_len = pkt->len - icmp_off;
        icmp->checksum = 0;

        uint8_t pseudo[40];
        memcpy(pseudo, ip6->saddr, 16);
        memcpy(pseudo + 16, ip6->daddr, 16);
        uint32_t icmp_len_n = htonl((uint32_t)icmp_len);
        memcpy(pseudo + 32, &icmp_len_n, 4);
        pseudo[36] = 0;
        pseudo[37] = 0;
        pseudo[38] = 0;
        pseudo[39] = PROTO_ICMPV6;

        uint32_t sum = (uint32_t)csum_partial(pseudo, 40) +
                       (uint32_t)csum_partial(pkt->data + icmp_off, icmp_len);
        while (sum >> 16)
            sum = (sum & 0xFFFF) + (sum >> 16);
        icmp->checksum = ~(uint16_t)sum;

        return 0;
    }

    return -1;
}

int op_forward(struct packet *pkt, const uint8_t *dst_mac, const uint8_t *src_mac)
{
    if (pkt->len < 14)
        return -1;

    struct eth_hdr *eth = (struct eth_hdr *)pkt->data;
    memcpy(eth->dst, dst_mac, ETH_ALEN);
    memcpy(eth->src, src_mac, ETH_ALEN);

    size_t l3_off;
    uint16_t l3_proto = find_l3(pkt, &l3_off);

    if (l3_proto == ETH_P_IP) {
        if (l3_off + sizeof(struct ipv4_hdr) > pkt->len)
            return -1;
        struct ipv4_hdr *ip = (struct ipv4_hdr *)(pkt->data + l3_off);

        if (ip->ttl <= 1)
            return -1;

        ip->ttl--;

        size_t ihl = (ip->ver_ihl & 0x0F) * 4;
        ip->check = 0;
        ip->check = ~csum_partial((const uint8_t *)ip, ihl);

        return 0;

    } else if (l3_proto == ETH_P_IPV6) {
        if (l3_off + sizeof(struct ipv6_hdr) > pkt->len)
            return -1;
        struct ipv6_hdr *ip6 = (struct ipv6_hdr *)(pkt->data + l3_off);

        if (ip6->hop_limit <= 1)
            return -1;

        ip6->hop_limit--;
        return 0;
    }

    return -1;
}

int op_filter(struct packet *pkt, const char *proto_name)
{
    size_t l3_off;
    uint16_t l3_proto = find_l3(pkt, &l3_off);

    if (l3_proto == ETH_P_IP) {
        if (l3_off + sizeof(struct ipv4_hdr) > pkt->len)
            return 0;
        struct ipv4_hdr *ip = (struct ipv4_hdr *)(pkt->data + l3_off);

        if (strcmp(proto_name, "icmp") == 0 && ip->protocol == PROTO_ICMP)
            return 1;
        if (strcmp(proto_name, "tcp") == 0 && ip->protocol == PROTO_TCP)
            return 1;
        if (strcmp(proto_name, "udp") == 0 && ip->protocol == PROTO_UDP)
            return 1;

    } else if (l3_proto == ETH_P_IPV6) {
        if (l3_off + sizeof(struct ipv6_hdr) > pkt->len)
            return 0;
        struct ipv6_hdr *ip6 = (struct ipv6_hdr *)(pkt->data + l3_off);

        if (strcmp(proto_name, "icmp6") == 0 && ip6->nexthdr == PROTO_ICMPV6)
            return 1;
        if (strcmp(proto_name, "tcp") == 0 && ip6->nexthdr == PROTO_TCP)
            return 1;
        if (strcmp(proto_name, "udp") == 0 && ip6->nexthdr == PROTO_UDP)
            return 1;
    }

    return 0;
}

int op_tag(struct packet *pkt, uint16_t key)
{
    if (pkt->len + TAG_TRAILER_LEN > MAX_PKT_SIZE)
        return -1;

    size_t l3_off;
    uint16_t l3_proto = find_l3(pkt, &l3_off);

    uint32_t digest = compute_tag_digest(pkt->data, pkt->len);

    uint8_t *trailer = pkt->data + pkt->len;

    uint32_t magic_n = htonl(TAG_MAGIC);
    memcpy(trailer, &magic_n, 4);

    uint16_t key_n = htons(key);
    memcpy(trailer + 4, &key_n, 2);

    uint16_t proto_n = htons(l3_proto);
    memcpy(trailer + 6, &proto_n, 2);

    uint32_t digest_n = htonl(digest);
    memcpy(trailer + 8, &digest_n, 4);

    pkt->len += TAG_TRAILER_LEN;
    return 0;
}

int op_untag(struct packet *pkt)
{
    if (pkt->len < 14 + TAG_TRAILER_LEN)
        return -1;

    size_t trailer_off = pkt->len - TAG_TRAILER_LEN;

    uint32_t magic;
    memcpy(&magic, pkt->data + trailer_off, 4);
    if (ntohl(magic) != TAG_MAGIC)
        return -1;

    uint32_t stored_digest;
    memcpy(&stored_digest, pkt->data + trailer_off + 8, 4);
    stored_digest = ntohl(stored_digest);

    uint32_t computed = compute_tag_digest(pkt->data, trailer_off);
    if (computed != stored_digest)
        return -1;

    pkt->len -= TAG_TRAILER_LEN;
    return 0;
}

/* ---- MAC parser ---- */

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

/* ---- Main ---- */

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
    uint16_t     vid;
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
