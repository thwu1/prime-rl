/* Multiple tracepoint programs with perf event output and filtering */
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

struct event {
    __u32 pid;
    __u32 uid;
    char comm[16];
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10240);
    __type(key, __u32);
    __type(value, __u32);
} filter_uid SEC(".maps");

SEC("tracepoint/syscalls/sys_enter_execve")
int trace_execve(void *ctx) {
    struct event e = {};
    e.pid = bpf_get_current_pid_tgid() >> 32;
    e.uid = bpf_get_current_uid_gid() & 0xFFFFFFFF;
    bpf_get_current_comm(e.comm, sizeof(e.comm));

    __u32 *allowed = bpf_map_lookup_elem(&filter_uid, &e.uid);
    if (!allowed)
        return 0;

    bpf_perf_event_output(ctx, &events, BPF_F_CURRENT_CPU, &e, sizeof(e));
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_openat")
int trace_openat(void *ctx) {
    struct event e = {};
    e.pid = bpf_get_current_pid_tgid() >> 32;
    e.uid = bpf_get_current_uid_gid() & 0xFFFFFFFF;
    bpf_get_current_comm(e.comm, sizeof(e.comm));
    bpf_perf_event_output(ctx, &events, BPF_F_CURRENT_CPU, &e, sizeof(e));
    return 0;
}

char LICENSE[] SEC("license") = "Dual BSD/GPL";
