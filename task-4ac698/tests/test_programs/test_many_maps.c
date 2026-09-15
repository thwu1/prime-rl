/* SPDX-License-Identifier: GPL-2.0 */
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

struct bpf_map_def {
    unsigned int type;
    unsigned int key_size;
    unsigned int value_size;
    unsigned int max_entries;
    unsigned int map_flags;
};

struct bpf_map_def SEC("maps") map_hash = {
    .type        = 1,  /* BPF_MAP_TYPE_HASH */
    .key_size    = 4,
    .value_size  = 8,
    .max_entries = 100,
};

struct bpf_map_def SEC("maps") map_array = {
    .type        = 2,  /* BPF_MAP_TYPE_ARRAY */
    .key_size    = 4,
    .value_size  = 4,
    .max_entries = 16,
};

struct bpf_map_def SEC("maps") map_percpu = {
    .type        = 6,  /* BPF_MAP_TYPE_PERCPU_ARRAY */
    .key_size    = 4,
    .value_size  = 32,
    .max_entries = 64,
};

SEC("xdp")
int xdp_many_maps(struct xdp_md *ctx)
{
    __u32 key = 0;
    void *val;

    val = bpf_map_lookup_elem(&map_hash, &key);
    if (val) return XDP_DROP;

    val = bpf_map_lookup_elem(&map_array, &key);
    if (val) return XDP_DROP;

    val = bpf_map_lookup_elem(&map_percpu, &key);
    if (val) return XDP_DROP;

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
