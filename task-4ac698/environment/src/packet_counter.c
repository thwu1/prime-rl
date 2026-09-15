/* SPDX-License-Identifier: GPL-2.0 */
#include "common.h"

struct bpf_map_def SEC("maps") xdp_stats_map = {
    .type        = BPF_MAP_TYPE_ARRAY,
    .key_size    = sizeof(__u32),
    .value_size  = sizeof(struct datarec),
    .max_entries = 5,
};

SEC("xdp")
int xdp_counter(struct xdp_md *ctx)
{
    void *data_end = (void *)(long)ctx->data_end;
    void *data     = (void *)(long)ctx->data;
    __u32 action   = XDP_PASS;
    __u32 key      = action;
    struct datarec *rec;

    rec = bpf_map_lookup_elem(&xdp_stats_map, &key);
    if (rec) {
        lock_xadd(&rec->rx_packets, 1);
        lock_xadd(&rec->rx_bytes, (__u64)(data_end - data));
    }

    return action;
}

char _license[] SEC("license") = "GPL";
