/* SPDX-License-Identifier: GPL-2.0 */
#include "common.h"

/*
 * Minimal ICMP definitions.  We avoid #include <linux/icmp.h> because
 * on some toolchains it transitively pulls in userspace headers
 * (linux/if.h -> sys/socket.h -> gnu/stubs-32.h) that are unavailable
 * when cross-compiling with -target bpf.
 */
struct icmphdr {
    __u8  type;
    __u8  code;
    __be16 checksum;
    union {
        struct {
            __be16 id;
            __be16 sequence;
        } echo;
        __be32 gateway;
    } un;
};

#define ICMP_ECHOREPLY 0
#define ICMP_ECHO      8

struct bpf_map_def SEC("maps") echo_stats = {
    .type        = BPF_MAP_TYPE_ARRAY,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(__u64),
    .max_entries = 1,
};

static __always_inline __u16 csum_fold(__u32 csum)
{
    csum = (csum & 0xffff) + (csum >> 16);
    csum = (csum & 0xffff) + (csum >> 16);
    return (__u16)~csum;
}

static __always_inline void swap_mac(struct ethhdr *eth)
{
    __u8 tmp[ETH_ALEN];
    __builtin_memcpy(tmp, eth->h_source, ETH_ALEN);
    __builtin_memcpy(eth->h_source, eth->h_dest, ETH_ALEN);
    __builtin_memcpy(eth->h_dest, tmp, ETH_ALEN);
}

static __always_inline void swap_ipv4(struct iphdr *iph)
{
    __be32 tmp  = iph->saddr;
    iph->saddr  = iph->daddr;
    iph->daddr  = tmp;
}

SEC("xdp")
int xdp_icmp_echo(struct xdp_md *ctx)
{
    void *data_end = (void *)(long)ctx->data_end;
    void *data     = (void *)(long)ctx->data;

    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;

    if (eth->h_proto != bpf_htons(ETH_P_IP))
        return XDP_PASS;

    struct iphdr *iph = (void *)(eth + 1);
    if ((void *)(iph + 1) > data_end)
        return XDP_PASS;

    if (iph->protocol != IPPROTO_ICMP)
        return XDP_PASS;

    int iph_len = iph->ihl * 4;
    if (iph_len < (int)sizeof(*iph))
        return XDP_PASS;

    if ((void *)iph + iph_len > data_end)
        return XDP_PASS;

    struct icmphdr *icmph = (void *)iph + iph_len;
    if ((void *)(icmph + 1) > data_end)
        return XDP_PASS;

    if (icmph->type != ICMP_ECHO)
        return XDP_PASS;

    /* Incremental checksum update: ICMP_ECHO (8) -> ICMP_ECHOREPLY (0) */
    __u32 old_csum = ~bpf_ntohs(icmph->checksum) & 0xffff;
    old_csum += ~(ICMP_ECHO << 8) & 0xffff;
    old_csum += (ICMP_ECHOREPLY << 8);
    icmph->checksum = bpf_htons(csum_fold(old_csum));
    icmph->type     = ICMP_ECHOREPLY;

    /* Swap addresses */
    swap_ipv4(iph);
    swap_mac(eth);

    /* Update stats */
    __u32 key    = 0;
    __u64 *count = bpf_map_lookup_elem(&echo_stats, &key);
    if (count)
        lock_xadd(count, 1);

    return XDP_TX;
}

char _license[] SEC("license") = "GPL";
