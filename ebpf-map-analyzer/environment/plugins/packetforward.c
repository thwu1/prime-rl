// Retina packetforward plugin - socket filter for packet counting
// Based on microsoft/retina pkg/plugin/packetforward
//

typedef unsigned char __u8;
typedef unsigned short __u16;
typedef unsigned int __u32;
typedef unsigned long long __u64;

#define SEC(name) __attribute__((section(name)))
#define __uint(name, val) int (*name)[val]
#define __type(name, val) typeof(val) *name
#define BPF_MAP_TYPE_PERCPU_HASH 5

char __license[] SEC("license") = "Dual MIT/GPL";

typedef __u32 pf_key_type;

struct pf_metric {
    __u64 count;
    __u64 bytes;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_HASH);
    __uint(max_entries, 2);
    __type(key, pf_key_type);
    __type(value, struct pf_metric);
} retina_packetforward_metrics SEC(".maps");

SEC("socket1")
int socket_filter(void *skb) {
    return 0;
}
