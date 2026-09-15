// Retina dropreason plugin - eBPF program for tracking packet drops
// Based on microsoft/retina pkg/plugin/dropreason
//

typedef unsigned char __u8;
typedef unsigned short __u16;
typedef unsigned int __u32;
typedef unsigned long long __u64;
typedef int __s32;
typedef _Bool bool;

#define SEC(name) __attribute__((section(name)))
#define __uint(name, val) int (*name)[val]
#define __type(name, val) typeof(val) *name
#define BPF_MAP_TYPE_HASH 1
#define BPF_MAP_TYPE_PERF_EVENT_ARRAY 4
#define BPF_MAP_TYPE_PERCPU_HASH 5

char __license[] SEC("license") = "Dual MIT/GPL";

struct metrics_map_key {
    __u16 drop_type;
    __u8 padding[2];
    __s32 return_val;
};

struct metrics_map_value {
    __u64 count;
    __u64 bytes;
};

struct dr_packet {
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    __u32 skb_len;
    __u32 return_val;
    __u16 drop_type;
    __u8 proto;
    bool in_filtermap;
    __u64 ts;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(max_entries, 16384);
} retina_dropreason_events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 16384);
    __type(key, __u32);
    __type(value, struct dr_packet);
} retina_dropreason_drop_pids SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 16384);
    __type(key, __u32);
    __type(value, struct dr_packet);
} retina_dropreason_natdrop_pids SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 16384);
    __type(key, __u32);
    __type(value, __u64);
} retina_dropreason_accept_pids SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_HASH);
    __uint(max_entries, 512);
    __type(key, struct metrics_map_key);
    __type(value, struct metrics_map_value);
} retina_dropreason_metrics SEC(".maps");

SEC("kprobe/nf_hook_slow")
int BPF_KPROBE(nf_hook_slow, void *skb, void *state) {
    return 0;
}

SEC("kretprobe/nf_hook_slow")
int BPF_KRETPROBE(nf_hook_slow_ret, int retVal) {
    return 0;
}

SEC("fexit/nf_hook_slow")
int BPF_PROG(nf_hook_slow_fexit, void *skb, void *state, int retVal) {
    return 0;
}

SEC("kretprobe/tcp_v4_connect")
int BPF_KRETPROBE(tcp_v4_connect_ret, int retVal) {
    return 0;
}

SEC("fexit/tcp_v4_connect")
int BPF_PROG(tcp_v4_connect_fexit, void *sk, void *uaddr, int addr_len, int retVal) {
    return 0;
}

SEC("kprobe/inet_csk_accept")
int BPF_KPROBE(inet_csk_accept_entry) {
    return 0;
}

SEC("kretprobe/inet_csk_accept")
int BPF_KRETPROBE(inet_csk_accept_ret, void *sk) {
    return 0;
}

SEC("fexit/inet_csk_accept")
int BPF_PROG(inet_csk_accept_fexit) {
    return 0;
}

SEC("kprobe/nf_nat_inet_fn")
int BPF_KPROBE(nf_nat_inet_fn_entry, void *priv, void *skb) {
    return 0;
}

SEC("kretprobe/nf_nat_inet_fn")
int BPF_KRETPROBE(nf_nat_inet_fn_ret, int retVal) {
    return 0;
}
