/* SPDX-License-Identifier: GPL-2.0 */
#include "common.h"

struct bpf_map_def SEC("maps") port_blacklist = {
    .type        = BPF_MAP_TYPE_HASH,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(__u32),
    .max_entries = 1024,
};

struct bpf_map_def SEC("maps") filter_stats = {
    .type        = BPF_MAP_TYPE_ARRAY,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(struct datarec),
    .max_entries = 2,
};

static __always_inline int parse_ethhdr(struct hdr_cursor *nh,
                                        void *data_end,
                                        struct ethhdr **ethhdr_out)
{
    struct ethhdr *eth = nh->pos;

    if ((void *)(eth + 1) > data_end)
        return -1;

    nh->pos = eth + 1;
    *ethhdr_out = eth;
    return bpf_ntohs(eth->h_proto);
}

static __always_inline int parse_iphdr(struct hdr_cursor *nh,
                                       void *data_end,
                                       struct iphdr **iphdr_out)
{
    struct iphdr *iph = nh->pos;
    int hdrsize;

    if ((void *)(iph + 1) > data_end)
        return -1;

    hdrsize = iph->ihl * 4;
    if (hdrsize < (int)sizeof(*iph))
        return -1;

    if (nh->pos + hdrsize > data_end)
        return -1;

    nh->pos += hdrsize;
    *iphdr_out = iph;
    return iph->protocol;
}

SEC("xdp")
int xdp_port_filter(struct xdp_md *ctx)
{
    void *data_end = (void *)(long)ctx->data_end;
    void *data     = (void *)(long)ctx->data;
    struct hdr_cursor nh = { .pos = data };
    struct ethhdr *eth;
    struct iphdr *iph;
    __u32 action = XDP_PASS;
    __u32 port   = 0;
    __u32 *value;

    int eth_type = parse_ethhdr(&nh, data_end, &eth);
    if (eth_type < 0)
        return XDP_PASS;

    if (eth_type != ETH_P_IP)
        return XDP_PASS;

    int ip_proto = parse_iphdr(&nh, data_end, &iph);
    if (ip_proto < 0)
        return XDP_PASS;

    if (ip_proto == IPPROTO_TCP) {
        struct tcphdr *tcph = nh.pos;
        if ((void *)(tcph + 1) > data_end)
            return XDP_PASS;
        port = bpf_ntohs(tcph->dest);
    } else if (ip_proto == IPPROTO_UDP) {
        struct udphdr *udph = nh.pos;
        if ((void *)(udph + 1) > data_end)
            return XDP_PASS;
        port = bpf_ntohs(udph->dest);
    } else {
        return XDP_PASS;
    }

    value = bpf_map_lookup_elem(&port_blacklist, &port);
    if (value)
        action = XDP_DROP;

    /* Update stats */
    __u32 stats_key = (action == XDP_DROP) ? 1 : 0;
    struct datarec *rec = bpf_map_lookup_elem(&filter_stats, &stats_key);
    if (rec) {
        lock_xadd(&rec->rx_packets, 1);
    }

    return action;
}

char _license[] SEC("license") = "GPL";
