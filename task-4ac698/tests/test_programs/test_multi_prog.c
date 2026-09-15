/* SPDX-License-Identifier: GPL-2.0 */
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

SEC("xdp/prog_alpha")
int xdp_prog_alpha(struct xdp_md *ctx)
{
    return XDP_PASS;
}

SEC("xdp/prog_beta")
int xdp_prog_beta(struct xdp_md *ctx)
{
    return XDP_DROP;
}

char _license[] SEC("license") = "GPL";
