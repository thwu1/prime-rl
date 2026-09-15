/* Kprobe program that counts execve calls per UID using a hash map */
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 1024);
    __type(key, __u32);
    __type(value, __u64);
} call_count SEC(".maps");

SEC("kprobe/do_execve")
int count_execve(void *ctx) {
    __u32 uid = bpf_get_current_uid_gid() & 0xFFFFFFFF;
    __u64 *count = bpf_map_lookup_elem(&call_count, &uid);
    if (count) {
        __sync_fetch_and_add(count, 1);
    } else {
        __u64 init = 1;
        bpf_map_update_elem(&call_count, &uid, &init, BPF_ANY);
    }
    return 0;
}

char LICENSE[] SEC("license") = "Dual BSD/GPL";
