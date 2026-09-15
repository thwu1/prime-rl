// Retina tcpretrans plugin - tracepoint for TCP retransmission tracking
// Based on microsoft/retina pkg/plugin/tcpretrans
//

typedef unsigned char __u8;
typedef unsigned short __u16;
typedef unsigned int __u32;
typedef unsigned long long __u64;

#define SEC(name) __attribute__((section(name)))
#define __uint(name, val) int (*name)[val]
#define __type(name, val) typeof(val) *name
#define BPF_MAP_TYPE_PERF_EVENT_ARRAY 4

char __license[] SEC("license") = "Dual MIT/GPL";

struct tcpretrans_event {
    __u64 timestamp;
    __u32 src_ip;
    __u32 dst_ip;
    __u32 state;
    __u16 src_port;
    __u16 dst_port;
    __u8 src_ip6[16];
    __u8 dst_ip6[16];
    __u8 tcpflags;
    __u8 af;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} retina_tcpretrans_events SEC(".maps");

SEC("tracepoint/tcp/tcp_retransmit_skb")
int retina_tcp_retransmit_skb(void *ctx) {
    return 0;
}
