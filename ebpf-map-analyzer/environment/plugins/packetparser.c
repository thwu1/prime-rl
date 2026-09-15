// Retina packetparser plugin - TC classifier for packet flow analysis
// Based on microsoft/retina pkg/plugin/packetparser
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
#define TC_ACT_UNSPEC (-1)

char __license[] SEC("license") = "Dual MIT/GPL";

struct pp_tcpmetadata {
    __u32 seq;
    __u32 ack_num;
    __u32 tsval;
    __u32 tsecr;
};

struct pp_tcpflagscount {
    __u32 syn;
    __u32 ack;
    __u32 fin;
    __u32 rst;
    __u32 psh;
    __u32 urg;
    __u32 ece;
    __u32 cwr;
    __u32 ns;
};

struct pp_conntrackmetadata {
    __u64 bytes_tx_count;
    __u64 bytes_rx_count;
    __u32 packets_tx_count;
    __u32 packets_rx_count;
};

struct pp_packet {
    __u64 t_nsec;
    __u32 bytes;
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    struct pp_tcpmetadata tcp_metadata;
    __u8 observation_point;
    __u8 traffic_direction;
    __u8 proto;
    __u16 flags;
    bool is_reply;
    __u32 prev_observed_packets;
    __u32 prev_observed_bytes;
    struct pp_tcpflagscount prev_observed_flags;
    struct pp_conntrackmetadata ct_meta;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(max_entries, 16384);
} retina_packetparser_events SEC(".maps");

SEC("classifier_endpoint_ingress")
int endpoint_ingress_filter(void *skb) {
    return TC_ACT_UNSPEC;
}

SEC("classifier_endpoint_egress")
int endpoint_egress_filter(void *skb) {
    return TC_ACT_UNSPEC;
}

SEC("classifier_host_ingress")
int host_ingress_filter(void *skb) {
    return TC_ACT_UNSPEC;
}

SEC("classifier_host_egress")
int host_egress_filter(void *skb) {
    return TC_ACT_UNSPEC;
}
