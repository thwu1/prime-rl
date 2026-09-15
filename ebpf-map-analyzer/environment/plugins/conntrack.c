// Retina conntrack plugin - eBPF connection tracking with LRU map
// Based on microsoft/retina pkg/plugin/conntrack
//

typedef unsigned char __u8;
typedef unsigned short __u16;
typedef unsigned int __u32;
typedef unsigned long long __u64;
typedef _Bool bool;

#define SEC(name) __attribute__((section(name)))
#define __uint(name, val) int (*name)[val]
#define __type(name, val) typeof(val) *name
#define BPF_MAP_TYPE_LRU_HASH 9
#define LIBBPF_PIN_BY_NAME 1
#define CT_MAP_SIZE 131072

struct tcpflagscount {
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

struct conntrackmetadata {
    __u64 bytes_tx_count;
    __u64 bytes_rx_count;
    __u32 packets_tx_count;
    __u32 packets_rx_count;
};

struct ct_v4_key {
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    __u8 proto;
};

struct ct_entry {
    __u32 eviction_time;
    __u32 last_report_tx_dir;
    __u32 last_report_rx_dir;
    __u32 bytes_since_report_tx;
    __u32 bytes_since_report_rx;
    __u32 packets_since_report_tx;
    __u32 packets_since_report_rx;
    struct tcpflagscount flags_since_report_tx;
    struct tcpflagscount flags_since_report_rx;
    __u8 traffic_direction;
    __u8 flags_seen_tx_dir;
    __u8 flags_seen_rx_dir;
    bool is_direction_unknown;
    struct conntrackmetadata conntrack_metadata;
};

struct {
    __uint(type, BPF_MAP_TYPE_LRU_HASH);
    __type(key, struct ct_v4_key);
    __type(value, struct ct_entry);
    __uint(max_entries, CT_MAP_SIZE);
    __uint(pinning, LIBBPF_PIN_BY_NAME);
} retina_conntrack SEC(".maps");
