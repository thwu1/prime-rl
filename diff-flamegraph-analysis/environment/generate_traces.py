#!/usr/bin/env python3
"""Generate deterministic performance trace data for regression triage task.

Creates raw perf script output (baseline + incident), off-CPU traces in
bpftrace map format, system metrics CSV, and collection manifest.

All data is deterministic (seeded PRNG). Sample counts are chosen so that
the regression root cause is 'mixed': CPU regression from regex backtracking
AND I/O regression from disk blocking + lock contention.

Expected totals after stackcollapse-perf.pl + grep '^appserver;':
  baseline appserver: 406 samples
  incident appserver: 928 samples
"""
import json
import os
import random

random.seed(42)

OUTDIR = "/app/traces"

# ── Process definitions ──
APP  = {"comm": "appserver", "pid": 4821, "dso": "/usr/local/bin/appserver"}
NGX  = {"comm": "nginx",     "pid": 3102, "dso": "/usr/sbin/nginx"}
PG   = {"comm": "postgres",  "pid": 5506, "dso": "/usr/bin/postgres"}

# ── Stack definitions: (frames root-to-leaf, count) ──

BASELINE_APP = [
    (["main", "event_loop", "handle_request", "parse_http", "parse_headers"], 30),
    (["main", "event_loop", "handle_request", "parse_http", "parse_body"], 15),
    (["main", "event_loop", "handle_request", "auth_check", "verify_token", "hmac_sha256"], 25),
    (["main", "event_loop", "handle_request", "auth_check", "session_lookup", "hash_table_get"], 12),
    (["main", "event_loop", "handle_request", "cache_lookup", "lru_get", "memcpy_avx2"], 22),
    (["main", "event_loop", "handle_request", "cache_lookup", "hash_key", "murmurhash3"], 18),
    (["main", "event_loop", "handle_request", "db_query", "sql_prepare", "parse_ast"], 20),
    (["main", "event_loop", "handle_request", "db_query", "sql_execute", "btree_scan", "page_read"], 28),
    (["main", "event_loop", "handle_request", "db_query", "sql_execute", "btree_scan", "compare_key"], 12),
    (["main", "event_loop", "handle_request", "db_query", "sql_execute", "hash_join", "probe_table"], 8),
    (["main", "event_loop", "handle_request", "db_query", "result_serialize", "row_to_map"], 15),
    (["main", "event_loop", "handle_request", "serialize", "json_marshal", "reflect_value"], 35),
    (["main", "event_loop", "handle_request", "serialize", "json_marshal", "write_string"], 28),
    (["main", "event_loop", "handle_request", "serialize", "json_marshal", "encode_number"], 8),
    (["main", "event_loop", "handle_request", "send_response", "tcp_write", "writev"], 32),
    (["main", "event_loop", "handle_request", "send_response", "tcp_write", "copy_to_buf"], 15),
    (["main", "event_loop", "handle_request", "log_access", "format_clf", "strftime"], 20),
    (["main", "event_loop", "handle_request", "log_access", "file_write", "fwrite"], 8),
    (["main", "event_loop", "epoll_wait"], 25),
    (["main", "gc_thread", "mark_sweep", "scan_roots"], 10),
    (["main", "gc_thread", "mark_sweep", "trace_refs"], 8),
    (["main", "gc_thread", "compact", "memmove"], 5),
    (["main", "stats_thread", "collect_metrics", "read_proc_stat"], 4),
    (["main", "stats_thread", "push_metrics", "send_payload"], 3),
]
# Total: 406

INCIDENT_APP = [
    (["main", "event_loop", "handle_request", "parse_http", "parse_headers"], 58),
    (["main", "event_loop", "handle_request", "parse_http", "parse_body"], 30),
    (["main", "event_loop", "handle_request", "auth_check", "verify_token", "hmac_sha256"], 50),
    (["main", "event_loop", "handle_request", "auth_check", "session_lookup", "hash_table_get"], 24),
    # NEW: input validation with catastrophic regex backtracking
    (["main", "event_loop", "handle_request", "validate_input", "regex_compile", "nfa_build"], 45),
    (["main", "event_loop", "handle_request", "validate_input", "regex_match", "backtrack"], 120),
    (["main", "event_loop", "handle_request", "validate_input", "schema_check", "type_coerce"], 15),
    # db_query — page_read has regression (missing index after schema change)
    (["main", "event_loop", "handle_request", "db_query", "sql_prepare", "parse_ast"], 42),
    (["main", "event_loop", "handle_request", "db_query", "sql_execute", "btree_scan", "page_read"], 130),
    (["main", "event_loop", "handle_request", "db_query", "sql_execute", "btree_scan", "compare_key"], 28),
    (["main", "event_loop", "handle_request", "db_query", "sql_execute", "hash_join", "probe_table"], 16),
    (["main", "event_loop", "handle_request", "db_query", "result_serialize", "row_to_map"], 32),
    # NEW: protobuf replaced json serialization
    (["main", "event_loop", "handle_request", "serialize", "proto_marshal", "wire_encode"], 55),
    (["main", "event_loop", "handle_request", "serialize", "proto_marshal", "field_tag"], 20),
    (["main", "event_loop", "handle_request", "serialize", "proto_marshal", "varint_encode"], 12),
    (["main", "event_loop", "handle_request", "send_response", "tcp_write", "writev"], 65),
    (["main", "event_loop", "handle_request", "send_response", "tcp_write", "copy_to_buf"], 30),
    (["main", "event_loop", "handle_request", "log_access", "format_clf", "strftime"], 40),
    (["main", "event_loop", "handle_request", "log_access", "file_write", "fwrite"], 16),
    # Reduced idle — CPU pressure
    (["main", "event_loop", "epoll_wait"], 15),
    (["main", "gc_thread", "mark_sweep", "scan_roots"], 20),
    (["main", "gc_thread", "mark_sweep", "trace_refs"], 16),
    (["main", "gc_thread", "compact", "memmove"], 10),
    (["main", "stats_thread", "collect_metrics", "read_proc_stat"], 8),
    (["main", "stats_thread", "push_metrics", "send_payload"], 6),
    # NEW: connection pool spin-wait under contention
    (["main", "event_loop", "handle_request", "db_query", "conn_pool_acquire", "spin_wait"], 25),
]
# Total: 928

BASELINE_NGX = [
    (["main", "ngx_worker_process_cycle", "ngx_process_events_and_timers", "ngx_epoll_process_events"], 20),
    (["main", "ngx_worker_process_cycle", "ngx_http_process_request", "ngx_http_upstream_send_request"], 15),
    (["main", "ngx_worker_process_cycle", "ngx_http_process_request", "ngx_http_log_request"], 10),
]

INCIDENT_NGX = [
    (["main", "ngx_worker_process_cycle", "ngx_process_events_and_timers", "ngx_epoll_process_events"], 40),
    (["main", "ngx_worker_process_cycle", "ngx_http_process_request", "ngx_http_upstream_send_request"], 30),
    (["main", "ngx_worker_process_cycle", "ngx_http_process_request", "ngx_http_log_request"], 20),
]

BASELINE_PG = [
    (["main", "PostmasterMain", "ServerLoop", "BackendStartup", "PostgresMain", "exec_simple_query", "PortalRun"], 18),
    (["main", "PostmasterMain", "ServerLoop", "BackendStartup", "PostgresMain", "exec_simple_query", "heap_getnext"], 10),
]

INCIDENT_PG = [
    (["main", "PostmasterMain", "ServerLoop", "BackendStartup", "PostgresMain", "exec_simple_query", "PortalRun"], 35),
    (["main", "PostmasterMain", "ServerLoop", "BackendStartup", "PostgresMain", "exec_simple_query", "heap_getnext"], 20),
]

# ── Off-CPU stacks: (frames leaf-to-root, duration_us) ──
OFFCPU_STACKS = [
    # Lock contention: conn_pool_acquire mutex wait
    (["finish_task_switch", "schedule", "futex_wait_queue_me", "futex_wait",
      "do_futex", "__x64_sys_futex", "do_syscall_64",
      "entry_SYSCALL_64_after_hwframe", "__lll_lock_wait",
      "__GI___pthread_mutex_lock", "conn_pool_acquire",
      "db_query", "handle_request", "event_loop", "main"], 5200),

    # I/O: page_read blocking on disk read
    (["finish_task_switch", "schedule", "io_schedule", "io_schedule_timeout",
      "wait_on_page_bit", "__lock_page_killable", "generic_file_buffered_read",
      "ext4_file_read_iter", "vfs_read", "ksys_read", "do_syscall_64",
      "entry_SYSCALL_64_after_hwframe", "__GI___libc_read", "page_read",
      "btree_scan", "sql_execute", "db_query", "handle_request",
      "event_loop", "main"], 12800),

    # Network: new direct DB connections (bypassing pool)
    (["finish_task_switch", "schedule", "inet_wait_for_connect",
      "__inet_stream_connect", "__sys_connect_file", "__sys_connect",
      "do_syscall_64", "entry_SYSCALL_64_after_hwframe",
      "__GI___libc_connect", "tcp_connect_nonblock", "get_connection",
      "db_query", "handle_request", "event_loop", "main"], 3400),

    # Idle: epoll wait (voluntary, not a problem)
    (["finish_task_switch", "schedule", "ep_poll", "do_epoll_wait",
      "__x64_sys_epoll_wait", "do_syscall_64",
      "entry_SYSCALL_64_after_hwframe", "__GI_epoll_wait",
      "epoll_wait", "event_loop", "main"], 45000),

    # Idle: GC sleep (voluntary, not a problem)
    (["finish_task_switch", "schedule", "hrtimer_nanosleep",
      "__x64_sys_nanosleep", "do_syscall_64",
      "entry_SYSCALL_64_after_hwframe", "__GI___nanosleep",
      "gc_sleep", "gc_thread", "main"], 62000),

    # Lock contention: conn_pool via retry path
    (["finish_task_switch", "schedule", "futex_wait_queue_me", "futex_wait",
      "do_futex", "__x64_sys_futex", "do_syscall_64",
      "entry_SYSCALL_64_after_hwframe", "__lll_lock_wait",
      "__GI___pthread_mutex_lock", "conn_pool_acquire",
      "retry_connection", "db_query", "handle_request",
      "event_loop", "main"], 2800),

    # I/O: log file fsync
    (["finish_task_switch", "schedule", "io_schedule",
      "wait_on_page_writeback", "__filemap_fdatawrite_range",
      "file_write_and_wait_range", "ext4_sync_file", "vfs_fsync_range",
      "do_syscall_64", "entry_SYSCALL_64_after_hwframe",
      "__GI___libc_fsync", "fwrite_flush", "file_write", "log_access",
      "handle_request", "event_loop", "main"], 1500),
]


# ── Generators ──

def gen_perf_event(comm, pid, cpu, ts, frames_leaf_first, dso):
    """Format one perf script event block."""
    base = 0x55a3b2c00000 if "appserver" in dso else (
           0x55b4c3000000 if "nginx" in dso else 0x55c5d4000000)
    lines = [f"{comm} {pid} [{cpu:03d}] {ts:.6f}: cpu-clock:ppp:"]
    for j, frame in enumerate(frames_leaf_first):
        addr = base + j * 0x100 + 0x20
        offset = j * 0x10 + 0x5
        lines.append(f"\t    {addr:x} {frame}+0x{offset:x} ({dso})")
    lines.append("")
    return "\n".join(lines)


def gen_perf_file(app_stacks, noise_groups, app_proc, base_ts, duration):
    """Generate a complete perf script file with interleaved processes."""
    events = []

    for frames, count in app_stacks:
        for _ in range(count):
            ts = base_ts + random.uniform(0, duration)
            cpu = random.randint(0, 3)
            events.append((ts, app_proc, list(reversed(frames))))

    for proc, stacks in noise_groups:
        for frames, count in stacks:
            for _ in range(count):
                ts = base_ts + random.uniform(0, duration)
                cpu = random.randint(0, 3)
                events.append((ts, proc, list(reversed(frames))))

    events.sort(key=lambda e: e[0])

    parts = [
        "# ========",
        f"# captured by: perf record -F 99 -a -g -- sleep {duration}",
        "# ========",
        "#",
        "",
    ]
    for ts, proc, frames_rev in events:
        cpu = random.randint(0, 3)
        parts.append(gen_perf_event(
            proc["comm"], proc["pid"], cpu, ts, frames_rev, proc["dso"]))

    return "\n".join(parts) + "\n"


def gen_offcpu():
    """Generate off-CPU trace file in bpftrace @usecs map format."""
    lines = [
        "# Off-CPU stack traces collected with bpftrace",
        "# Probe: kprobe:finish_task_switch / pid == 4821 /",
        "# Target: PID 4821 (appserver), Duration: 60s",
        "# Captured: 2024-11-15T14:45:00Z",
        "# Stack ordering: leaf frame at top, root frame at bottom",
        "# Value: aggregate off-CPU time in microseconds",
        "",
    ]
    for frames, dur_us in OFFCPU_STACKS:
        lines.append("@usecs[")
        for frame in frames:
            lines.append(f"    {frame}")
        lines.append(f"]: {dur_us}")
        lines.append("")
    return "\n".join(lines) + "\n"


def gen_metrics():
    """Generate system metrics CSV spanning both windows."""
    rows = [
        "timestamp_epoch,runq_lat_avg_us,runq_lat_p99_us,cpu_util_pct,iowait_pct,ctx_switches_per_sec",
        # Baseline window (30s)
        "1731634200,8,42,32,2,15000",
        "1731634205,10,45,34,2,14800",
        "1731634210,9,43,33,3,15200",
        "1731634215,11,48,35,2,14600",
        "1731634220,8,40,31,2,15100",
        "1731634225,10,46,34,3,14900",
        # Gap
        # Incident window (60s)
        "1731635100,75,850,72,10,38000",
        "1731635105,95,1200,78,13,42000",
        "1731635110,110,1400,80,14,45000",
        "1731635115,125,1650,82,15,47000",
        "1731635120,135,1800,84,16,49000",
        "1731635125,140,1900,83,17,48500",
        "1731635130,145,2000,85,17,50000",
        "1731635135,148,2050,85,18,50500",
        "1731635140,150,2100,86,18,51000",
        "1731635145,142,1950,84,17,49500",
        "1731635150,138,1850,83,16,48000",
        "1731635155,145,2000,85,18,50000",
    ]
    return "\n".join(rows) + "\n"


def gen_manifest():
    """Generate collection metadata."""
    return json.dumps({
        "target_process": "appserver",
        "target_pid": 4821,
        "baseline": {
            "perf_file": "baseline.perf",
            "duration_seconds": 30,
            "sample_rate_hz": 99,
            "capture_start": "2024-11-15T02:30:00Z",
            "description": "Baseline capture during normal operation, v2.4.1"
        },
        "incident": {
            "perf_file": "incident.perf",
            "offcpu_file": "offcpu_stacks.txt",
            "duration_seconds": 60,
            "sample_rate_hz": 99,
            "capture_start": "2024-11-15T14:45:00Z",
            "description": "Capture during latency incident after v2.5.0 deploy, p99 latency 3x baseline"
        },
        "metrics_file": "sysmetrics.csv",
        "notes": [
            "Baseline and incident captures have different durations; normalize before comparing.",
            "The system-wide perf capture includes all processes running on the host.",
            "Off-CPU stacks were collected only during the incident window.",
            "System metrics span both baseline and incident windows."
        ]
    }, indent=2) + "\n"


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    baseline_noise = [(NGX, BASELINE_NGX), (PG, BASELINE_PG)]
    incident_noise = [(NGX, INCIDENT_NGX), (PG, INCIDENT_PG)]

    with open(os.path.join(OUTDIR, "baseline.perf"), "w") as f:
        f.write(gen_perf_file(BASELINE_APP, baseline_noise, APP, 1731634200.0, 30))

    with open(os.path.join(OUTDIR, "incident.perf"), "w") as f:
        f.write(gen_perf_file(INCIDENT_APP, incident_noise, APP, 1731635100.0, 60))

    with open(os.path.join(OUTDIR, "offcpu_stacks.txt"), "w") as f:
        f.write(gen_offcpu())

    with open(os.path.join(OUTDIR, "sysmetrics.csv"), "w") as f:
        f.write(gen_metrics())

    with open(os.path.join(OUTDIR, "manifest.json"), "w") as f:
        f.write(gen_manifest())

    app_b = sum(c for _, c in BASELINE_APP)
    app_i = sum(c for _, c in INCIDENT_APP)
    print(f"Generated trace data in {OUTDIR}")
    print(f"  baseline.perf: {app_b} app + "
          f"{sum(c for _, s in baseline_noise for _, c in s)} noise samples")
    print(f"  incident.perf: {app_i} app + "
          f"{sum(c for _, s in incident_noise for _, c in s)} noise samples")
    print(f"  offcpu_stacks.txt: {len(OFFCPU_STACKS)} stacks")


if __name__ == "__main__":
    main()
