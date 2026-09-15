// Retina DNS plugin - eBPF socket filter for DNS query/response capture
// Based on microsoft/retina pkg/plugin/dns
//

typedef unsigned char __u8;
typedef unsigned short __u16;
typedef unsigned int __u32;
typedef unsigned long long __u64;
typedef _Bool bool;

#define SEC(name) __attribute__((section(name)))
#define __uint(name, val) int (*name)[val]
#define __type(name, val) typeof(val) *name
#define BPF_MAP_TYPE_PERF_EVENT_ARRAY 4
#define BPF_MAP_TYPE_PERCPU_ARRAY 6

char __license[] SEC("license") = "Dual MIT/GPL";

struct dnshdr {
    __u16 id;
    __u16 flags;
    __u16 qdcount;
    __u16 ancount;
    __u16 nscount;
    __u16 arcount;
};

// Fields ordered by descending alignment to minimize internal padding.
// The compiler adds 5 bytes of trailing padding to reach 8-byte struct
// alignment (required by the __u64 field).
struct dns_event {
    __u64 timestamp;
    __u32 src_ip;
    __u32 dst_ip;
    __u8 src_ip6[16];
    __u8 dst_ip6[16];
    __u16 src_port;
    __u16 dst_port;
    __u16 id;
    __u16 qtype;
    __u16 ancount;
    __u16 dns_off;
    __u16 data_len;
    __u8 af;
    __u8 proto;
    __u8 pkt_type;
    __u8 qr;
    __u8 rcode;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} retina_dns_events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, 1);
    __type(key, __u32);
    __type(value, struct dns_event);
} tmp_dns_events SEC(".maps");

SEC("socket1")
int retina_dns_filter(void *skb) {
    return 0;
}
