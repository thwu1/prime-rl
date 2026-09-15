#!/usr/bin/env python3
"""
Generate synthetic perf script output for the CPU profile regression forensics task.
Run during Docker build to create /app/profiles/{baseline,regression}.perf.

"""

import os
import random

random.seed(42)

# ---------------------------------------------------------------------------
# Address helpers (deterministic but varied for realism)
# ---------------------------------------------------------------------------

def _hash_name(name):
    h = 5381
    for c in name:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFFFFFF
    return h

def func_addr(base, name):
    return base + (_hash_name(name) % 0x100000)

def func_offset(name):
    return (_hash_name(name) * 7) & 0xFF

# ---------------------------------------------------------------------------
# DSO / base-address constants
# ---------------------------------------------------------------------------

PORTAL_BASE = 0x5634a1b00000
PORTAL_DSO  = "/usr/local/bin/portal-api"
KERNEL_BASE = 0xffffffff81000000
KERNEL_DSO  = "[kernel.kallsyms]"
NODE_BASE   = 0x55d3e2000000
NODE_DSO    = "/usr/local/bin/node"
LIBC_BASE   = 0x7f5a30000000
SSHD_DSO    = "/usr/sbin/sshd"
JOURNAL_BASE = 0x7f5a40000000
JOURNAL_DSO  = "/usr/lib/systemd/libsystemd-shared-255.so"

# ---------------------------------------------------------------------------
# Target process: portal-api (PID 4821)
# Stacks listed ROOT -> LEAF (will be reversed for perf script output)
# ---------------------------------------------------------------------------

BASELINE_TARGET = [
    (["main", "event_loop", "epoll_wait"], 250),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "parse_method"], 40),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "parse_url"], 35),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "parse_content_type"], 20),
    (["main", "event_loop", "accept_conn", "handle_request", "route_request", "match_pattern"], 30),
    (["main", "event_loop", "accept_conn", "handle_request", "route_request", "extract_params"], 15),
    (["main", "event_loop", "accept_conn", "handle_request", "auth_check", "verify_token", "jwt_decode"], 40),
    (["main", "event_loop", "accept_conn", "handle_request", "auth_check", "verify_token", "sig_verify"], 30),
    (["main", "event_loop", "accept_conn", "handle_request", "auth_check", "load_permissions"], 20),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "conn_pool_acquire"], 15),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "execute_sql", "query_plan"], 30),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "execute_sql", "fetch_rows"], 50),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "execute_sql", "deserialize_row"], 35),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "conn_pool_release"], 10),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "format_json", "write_field"], 40),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "format_json", "escape_string"], 20),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "compress_gzip"], 35),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "send_response", "tcp_write"], 50),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "load_cert"], 15),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "negotiate_cipher"], 20),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "cached_session_resume"], 25),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_lookup"], 10),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_hit_return"], 15),
    (["main", "gc_cycle", "mark_phase"], 30),
    (["main", "gc_cycle", "sweep_phase"], 20),
    (["main", "gc_cycle", "compact_phase"], 15),
    (["main", "log_flush", "write_buffer"], 20),
    (["main", "log_flush", "rotate_check"], 5),
    (["main", "signal_handler", "graceful_check"], 5),
]

REGRESSION_TARGET = [
    (["main", "event_loop", "epoll_wait"], 320),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "parse_method"], 54),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "parse_url"], 47),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "parse_content_type"], 27),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "validate_encoding", "utf8_check_byte"], 38),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "validate_encoding", "utf8_check_sequence"], 29),
    (["main", "event_loop", "accept_conn", "handle_request", "parse_headers", "validate_encoding", "encoding_fallback"], 18),
    (["main", "event_loop", "accept_conn", "handle_request", "route_request", "match_pattern"], 42),
    (["main", "event_loop", "accept_conn", "handle_request", "route_request", "extract_params"], 21),
    (["main", "event_loop", "accept_conn", "handle_request", "auth_check", "verify_token", "jwt_decode"], 56),
    (["main", "event_loop", "accept_conn", "handle_request", "auth_check", "verify_token", "sig_verify"], 42),
    (["main", "event_loop", "accept_conn", "handle_request", "auth_check", "load_permissions"], 28),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "conn_pool_acquire"], 21),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "execute_sql", "query_plan"], 42),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "execute_sql", "fetch_rows"], 70),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "execute_sql", "deserialize_row"], 49),
    (["main", "event_loop", "accept_conn", "handle_request", "db_query", "conn_pool_release"], 14),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "format_json", "write_field"], 95),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "format_json", "escape_string"], 62),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "format_json", "buffer_realloc"], 43),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "compress_gzip"], 49),
    (["main", "event_loop", "accept_conn", "handle_request", "serialize_response", "send_response", "tcp_write"], 70),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "load_cert"], 20),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "negotiate_cipher"], 28),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "derive_key_full", "generate_params"], 35),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "derive_key_full", "compute_shared_secret"], 42),
    (["main", "event_loop", "accept_conn", "handle_request", "tls_handshake", "derive_key_full", "expand_key_material"], 28),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_lookup"], 14),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_miss", "build_query"], 12),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_miss", "udp_send"], 9),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_miss", "wait_response"], 31),
    (["main", "event_loop", "accept_conn", "handle_request", "dns_resolve", "cache_miss", "parse_response"], 8),
    (["main", "event_loop", "accept_conn", "handle_request", "log_request_body", "serialize_body", "json_encode"], 25),
    (["main", "event_loop", "accept_conn", "handle_request", "log_request_body", "serialize_body", "base64_encode"], 18),
    (["main", "event_loop", "accept_conn", "handle_request", "log_request_body", "write_debug_log", "format_timestamp"], 12),
    (["main", "event_loop", "accept_conn", "handle_request", "log_request_body", "write_debug_log", "file_write"], 9),
    (["main", "gc_cycle", "mark_phase"], 42),
    (["main", "gc_cycle", "sweep_phase"], 28),
    (["main", "gc_cycle", "compact_phase"], 21),
    (["main", "log_flush", "write_buffer"], 28),
    (["main", "log_flush", "rotate_check"], 7),
    (["main", "signal_handler", "graceful_check"], 7),
]

# ---------------------------------------------------------------------------
# Noise processes
# ---------------------------------------------------------------------------

NOISE_BASELINE = [
    # kworker/0:1 (PID 12)
    ("kworker/0:1", 12, KERNEL_BASE, KERNEL_DSO, [
        (["entry_SYSCALL_64", "rcu_core", "rcu_do_batch", "call_rcu_cb"], 30),
        (["kthread", "worker_thread", "process_one_work", "flush_to_ldisc"], 25),
        (["kthread", "worker_thread", "process_one_work", "wb_workfn"], 20),
    ]),
    # systemd-journal (PID 345)
    ("systemd-journald", 345, JOURNAL_BASE, JOURNAL_DSO, [
        (["__libc_start_main", "main", "server_process_datagram", "compress_blob"], 15),
        (["__libc_start_main", "main", "server_process_datagram", "journal_file_append"], 10),
    ]),
    # sshd (PID 2100)
    ("sshd", 2100, LIBC_BASE, SSHD_DSO, [
        (["__libc_start_main", "main", "server_loop", "read_network"], 8),
        (["__libc_start_main", "main", "server_loop", "write_network"], 5),
    ]),
    # node (PID 5500) -- another microservice on the same host
    ("node", 5500, NODE_BASE, NODE_DSO, [
        (["_start", "node_main", "uv_run", "poll_io", "epoll_pwait"], 40),
        (["_start", "node_main", "uv_run", "run_timers", "timer_cb", "compile_fn"], 35),
        (["_start", "node_main", "uv_run", "run_timers", "timer_cb", "gc_collect"], 20),
        (["_start", "node_main", "uv_run", "run_timers", "timer_cb", "handle_req"], 15),
    ]),
]

NOISE_REGRESSION = [
    ("kworker/0:1", 12, KERNEL_BASE, KERNEL_DSO, [
        (["entry_SYSCALL_64", "rcu_core", "rcu_do_batch", "call_rcu_cb"], 45),
        (["kthread", "worker_thread", "process_one_work", "flush_to_ldisc"], 38),
        (["kthread", "worker_thread", "process_one_work", "wb_workfn"], 30),
    ]),
    ("systemd-journald", 345, JOURNAL_BASE, JOURNAL_DSO, [
        (["__libc_start_main", "main", "server_process_datagram", "compress_blob"], 20),
        (["__libc_start_main", "main", "server_process_datagram", "journal_file_append"], 13),
    ]),
    ("sshd", 2100, LIBC_BASE, SSHD_DSO, [
        (["__libc_start_main", "main", "server_loop", "read_network"], 8),
        (["__libc_start_main", "main", "server_loop", "write_network"], 5),
    ]),
    ("node", 5500, NODE_BASE, NODE_DSO, [
        (["_start", "node_main", "uv_run", "poll_io", "epoll_pwait"], 56),
        (["_start", "node_main", "uv_run", "run_timers", "timer_cb", "compile_fn"], 49),
        (["_start", "node_main", "uv_run", "run_timers", "timer_cb", "gc_collect"], 28),
        (["_start", "node_main", "uv_run", "run_timers", "timer_cb", "handle_req"], 21),
    ]),
]

# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_sample(comm, pid, timestamp, frames_leaf_to_root, base_addr, dso):
    """Emit one perf-script sample block."""
    lines = []
    lines.append(
        f"{comm} {pid:5d} {timestamp:.6f}:          1 cpu-clock:ppp: "
    )
    for fn in frames_leaf_to_root:
        addr = func_addr(base_addr, fn)
        off  = func_offset(fn)
        lines.append(f"\t{addr:016x} {fn}+0x{off:x} ({dso})")
    lines.append("")            # blank separator
    return "\n".join(lines) + "\n"


def build_samples(target_stacks, target_pid, noise_list):
    """Return a list of (comm, pid, frames_leaf_to_root, base, dso) tuples."""
    samples = []

    for root_to_leaf, count in target_stacks:
        leaf_to_root = list(reversed(root_to_leaf))
        for _ in range(count):
            samples.append(("portal-api", target_pid, leaf_to_root,
                            PORTAL_BASE, PORTAL_DSO))

    for comm, pid, base, dso, stacks in noise_list:
        for root_to_leaf, count in stacks:
            leaf_to_root = list(reversed(root_to_leaf))
            for _ in range(count):
                samples.append((comm, pid, leaf_to_root, base, dso))

    return samples


def write_profile(samples, path, start_ts):
    """Shuffle samples and write perf-script output."""
    random.shuffle(samples)                     # deterministic via seed
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = start_ts
    with open(path, "w") as fh:
        for comm, pid, frames, base, dso in samples:
            ts += random.uniform(0.0005, 0.015)
            fh.write(format_sample(comm, pid, ts, frames, base, dso))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    random.seed(42)

    baseline_samples = build_samples(BASELINE_TARGET, 4821, NOISE_BASELINE)
    # reset seed so regression shuffle is independent
    random.seed(137)
    regression_samples = build_samples(REGRESSION_TARGET, 4821, NOISE_REGRESSION)

    random.seed(42)
    write_profile(baseline_samples, "/app/profiles/baseline.perf", 1710512520.0)
    random.seed(137)
    write_profile(regression_samples, "/app/profiles/regression.perf", 1710598920.0)

    print(f"baseline.perf  : {len(baseline_samples)} samples")
    print(f"regression.perf: {len(regression_samples)} samples")
