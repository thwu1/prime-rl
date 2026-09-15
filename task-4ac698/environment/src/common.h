/* SPDX-License-Identifier: GPL-2.0 */
#ifndef __COMMON_H
#define __COMMON_H

#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/ipv6.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <linux/in.h>

/* Legacy map definition — five sequential unsigned ints in the ELF "maps" section */
struct bpf_map_def {
    unsigned int type;
    unsigned int key_size;
    unsigned int value_size;
    unsigned int max_entries;
    unsigned int map_flags;
};

struct datarec {
    __u64 rx_packets;
    __u64 rx_bytes;
};

struct hdr_cursor {
    void *pos;
};

#ifndef lock_xadd
#define lock_xadd(ptr, val) ((void)__sync_fetch_and_add(ptr, val))
#endif

#endif /* __COMMON_H */
