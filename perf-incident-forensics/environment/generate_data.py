#!/usr/bin/env python3
"""
Generate synthetic performance incident data for forensics analysis.
Creates /app/incident/ with raw perf script CPU profiling output,
strace logs, and periodic system state snapshots.
"""
import os
import random

RNG = random.Random(42)
BASE = "/app/incident"


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


# ═══════════════════════════════════════════════════════════════════════════
# DSO MAPPING FOR PERF SCRIPT OUTPUT
# ═══════════════════════════════════════════════════════════════════════════
DSO_MAP = {
    # Kernel
    "do_splice": "[kernel.kallsyms]",
    "vfs_getattr": "[kernel.kallsyms]",
    "__ip_queue_xmit": "[kernel.kallsyms]",
    "tcp_sendmsg": "[kernel.kallsyms]",
    "epoll_wait": "[kernel.kallsyms]",
    "__schedule": "[kernel.kallsyms]",
    "schedule": "[kernel.kallsyms]",
    "copy_user_generic": "[kernel.kallsyms]",
    # libc
    "__futex_wait_queue": "/lib/x86_64-linux-gnu/libc.so.6",
    "mutex_lock": "/lib/x86_64-linux-gnu/libc.so.6",
    "rwlock_rdlock": "/lib/x86_64-linux-gnu/libc.so.6",
    "__libc_malloc": "/lib/x86_64-linux-gnu/libc.so.6",
    "_int_malloc": "/lib/x86_64-linux-gnu/libc.so.6",
    "__GI___libc_write": "/lib/x86_64-linux-gnu/libc.so.6",
    "memmove": "/lib/x86_64-linux-gnu/libc.so.6",
    "clock_gettime": "/lib/x86_64-linux-gnu/libc.so.6",
    "strftime_l": "/lib/x86_64-linux-gnu/libc.so.6",
    # Crypto
    "rsa_ossl_private_decrypt": "/lib/x86_64-linux-gnu/libcrypto.so.3",
    "bn_mod_exp_mont": "/lib/x86_64-linux-gnu/libcrypto.so.3",
    "aes_ctr_cipher": "/lib/x86_64-linux-gnu/libcrypto.so.3",
    "aesni_ctr32_ghash": "/lib/x86_64-linux-gnu/libcrypto.so.3",
    "BF_encrypt": "/lib/x86_64-linux-gnu/libcrypto.so.3",
    "bcrypt_hashpw": "/lib/x86_64-linux-gnu/libcrypto.so.3",
    # Compression
    "deflate_slow": "/lib/x86_64-linux-gnu/libz.so.1",
    "adler32": "/lib/x86_64-linux-gnu/libz.so.1",
    # PCRE2
    "pcre2_match": "/lib/x86_64-linux-gnu/libpcre2-8.so.0",
    # Dynamic linker
    "_dl_load": "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
    "dlopen": "/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2",
}
DEFAULT_DSO = "/usr/lib/x86_64-linux-gnu/libserver.so"


def get_dso(func_name):
    return DSO_MAP.get(func_name, DEFAULT_DSO)


# ═══════════════════════════════════════════════════════════════════════════
# README
# ═══════════════════════════════════════════════════════════════════════════
def generate_readme():
    write_file(f"{BASE}/README.txt", """\
Performance Incident Data Capture
=================================
Captured during a production web server performance degradation event.

Timing:
  Observation window: 20 seconds total
  First snapshot: t0 at epoch 1718000000
  Last snapshot:  t4 at epoch 1718000020
  Snapshot interval: 5 seconds

Storage topology:
  /dev/sda - Root filesystem (OS, system binaries)
  /dev/sdb - Application data partition (mounted at /data)
             Houses database files (/data/db/) and worker process logs (/data/workerd/)
  /dev/sdc - Archival storage (backup snapshots, minimal active traffic)

Data layout:
  perf/perf_script.txt       - Raw CPU profiling output (perf script format,
                                cpu-clock event, multiple sample blocks)
  strace/pid_NNNN.log        - System call traces for suspect processes
  snapshots/tN_EPOCH/        - Periodic system state captures:
    proc_diskstats              - /proc/diskstats at capture time
    proc_net_dev                - /proc/net/dev at capture time
    processes/PID_status        - /proc/PID/status for monitored processes

Monitored processes:
  PID 1001 - systemd (init)
  PID 3156 - workerd (worker daemon, writes to /data/workerd/)
  PID 4821 - nginx (reverse proxy)
  PID 7293 - dataimporter (batch data import)
  PID 8450 - redis-server (caching layer)
""")


# ═══════════════════════════════════════════════════════════════════════════
# RAW PERF SCRIPT OUTPUT (total: 25200 cpu-clock samples)
# ═══════════════════════════════════════════════════════════════════════════
STACKS = [
    ("server_main;request_handler;db_query;mutex_lock;__futex_wait_queue", 2800),
    ("server_main;request_handler;cache_get;rwlock_rdlock;__futex_wait_queue", 1410),
    ("server_main;request_handler;response_write;compress;deflate_slow", 1750),
    ("server_main;request_handler;response_write;compress;deflate_slow;adler32", 400),
    ("server_main;request_handler;response_write;tcp_sendmsg;copy_user_generic", 2100),
    ("server_main;request_handler;response_write;tcp_sendmsg;__ip_queue_xmit", 800),
    ("server_main;request_handler;body_parse;json_decode;validate_utf8", 1100),
    ("server_main;request_handler;body_parse;json_decode;hash_insert", 750),
    ("server_main;request_handler;db_query;sql_exec;btree_search", 600),
    ("server_main;request_handler;db_query;sql_exec;btree_search;key_compare", 300),
    ("server_main;request_handler;db_query;sql_exec;row_compare", 600),
    ("server_main;request_handler;auth;bcrypt_hashpw;BF_encrypt", 1500),
    ("server_main;request_handler;auth;session_lookup;hash_find", 350),
    ("server_main;gc_thread;mark_phase;trace_references", 1800),
    ("server_main;gc_thread;sweep_phase;free_chunk", 700),
    ("server_main;gc_thread;compact_phase;memmove", 500),
    ("server_main;ssl_thread;rsa_ossl_private_decrypt;bn_mod_exp_mont", 1100),
    ("server_main;ssl_thread;aes_ctr_cipher;aesni_ctr32_ghash", 650),
    ("server_main;log_thread;format_log_entry;strftime_l", 400),
    ("server_main;log_thread;write_log;__GI___libc_write", 250),
    ("server_main;request_handler;alloc_response;__libc_malloc;_int_malloc", 700),
    ("server_main;request_handler;template_render;pcre2_match", 600),
    ("server_main;timer_thread;check_expires;rbtree_next", 300),
    ("server_main;stats_thread;collect_metrics;clock_gettime", 200),
    ("server_main;request_handler;middleware_chain;rate_limiter;token_check", 180),
    ("server_main;request_handler;middleware_chain;cors_check;header_match", 120),
    ("server_main;request_handler;response_write;chunked_encode;base64_encode", 350),
    ("server_main;request_handler;error_handler;format_error;json_encode", 150),
    ("server_main;request_handler;websocket;frame_decode;unmask_payload", 280),
    ("server_main;request_handler;websocket;frame_encode;mask_payload", 220),
    ("server_main;request_handler;static_file;sendfile;do_splice", 400),
    ("server_main;request_handler;static_file;stat;vfs_getattr", 130),
    ("server_main;epoll_thread;epoll_wait;schedule;__schedule", 500),
    ("server_main;epoll_thread;process_events;fd_lookup", 160),
    ("server_main;request_handler;db_query;conn_pool;check_idle", 180),
    ("server_main;request_handler;body_parse;multipart_decode;boundary_scan", 250),
    ("server_main;request_handler;body_parse;url_decode;percent_decode", 190),
    ("server_main;request_handler;response_write;set_headers;date_format", 130),
    ("server_main;worker_init;dlopen;_dl_load", 100),
    ("server_main;request_handler;geoip_lookup;trie_search", 200),
]


def generate_perf_script():
    """Generate raw perf script format output from stack data.

    Format:
        comm  PID [CPU] timestamp: event:
        \\taddr function+offset (dso)
        \\taddr function+offset (dso)
        ...
        <blank line>
    """
    # Expand all samples into individual sample entries
    all_samples = []
    for stack_str, count in STACKS:
        parts = stack_str.split(";")
        comm = parts[0]  # e.g. "server_main"
        # Remaining frames from root to leaf
        frames = parts[1:]
        # Reverse for perf script (leaf function first)
        frames_rev = list(reversed(frames))
        for _ in range(count):
            all_samples.append((comm, frames_rev))

    RNG.shuffle(all_samples)

    lines = []
    ts = 1718000000.000000
    pid = 1234
    cpu = 0

    for comm, frames in all_samples:
        # Header line
        lines.append(f"{comm} {pid} [{cpu:03d}] {ts:.6f}: cpu-clock:")
        cpu = (cpu + 1) % 4

        # Frame lines (leaf first, callers follow)
        for func in frames:
            addr = RNG.randint(0x7f0000000000, 0x7fffffffffff)
            offset = RNG.randint(1, 0xff)
            dso = get_dso(func)
            lines.append(f"\t{addr:016x} {func}+0x{offset:x} ({dso})")

        # Blank line separator
        lines.append("")
        ts += RNG.uniform(0.0001, 0.001)

    write_file(f"{BASE}/perf/perf_script.txt", "\n".join(lines) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# STRACE LOGS
# ═══════════════════════════════════════════════════════════════════════════
def generate_strace_normal(pid):
    """Normal web worker process, no pathological patterns. ~3000 lines."""
    lines = []
    ts = 1718000000.0
    for _ in range(3000):
        fd = RNG.choice([5, 6, 7, 8])
        c = RNG.randint(0, 9)
        if c == 0:
            sz = RNG.choice([1024, 2048, 4096, 8192])
            ret = RNG.randint(sz // 2, sz)
            lines.append(f"{ts:.6f} read({fd}, \"GET /api/v1/users\"..., {sz}) = {ret}")
        elif c == 1:
            sz = RNG.choice([64, 128, 247, 512])
            lines.append(f"{ts:.6f} write({fd}, \"HTTP/1.1 200 OK\\r\\n\"..., {sz}) = {sz}")
        elif c == 2:
            lines.append(
                f"{ts:.6f} epoll_wait(4, [{{EPOLLIN, {{u32={fd}, u64={fd}}}}}], 128, -1) = 1"
            )
        elif c == 3:
            port = RNG.randint(30000, 60000)
            lines.append(
                f"{ts:.6f} accept4(3, {{sa_family=AF_INET, sin_port=htons({port})}}, "
                f"[128->16], SOCK_CLOEXEC) = {fd}"
            )
        elif c == 4:
            lines.append(f"{ts:.6f} close({fd}) = 0")
        elif c == 5:
            sz = RNG.choice([1024, 2048, 4096])
            ret = RNG.randint(sz // 2, sz)
            lines.append(
                f'{ts:.6f} read({fd}, "{{\\\"user_id\\\": 42}}"..., {sz}) = {ret}'
            )
        elif c == 6:
            lines.append(
                f"{ts:.6f} sendto({fd}, \"\\x00\\x01\"..., 64, MSG_NOSIGNAL, NULL, 0) = 64"
            )
        elif c == 7:
            lines.append(
                f"{ts:.6f} recvfrom({fd}, \"\\x01\\x02\"..., 1024, 0, NULL, NULL) = 256"
            )
        elif c == 8:
            addr = RNG.randint(0x1000000, 0x9999999)
            lines.append(
                f"{ts:.6f} futex(0x7f{addr:07x}, FUTEX_WAIT_PRIVATE, 0, NULL) = 0"
            )
        else:
            ns = RNG.randint(0, 999999999)
            lines.append(
                f"{ts:.6f} clock_gettime(CLOCK_MONOTONIC, "
                f"{{tv_sec={int(ts)}, tv_nsec={ns}}}) = 0"
            )
        ts += RNG.uniform(0.0001, 0.005)
    write_file(f"{BASE}/strace/pid_{pid}.log", "\n".join(lines) + "\n")


def generate_strace_pathological(pid):
    """Process with exactly 1847 zero-byte reads among 4000 total syscall lines."""
    markers = [True] * 1847 + [False] * 2153
    RNG.shuffle(markers)

    lines = []
    ts = 1718000000.0
    for is_zero in markers:
        fd = RNG.choice([5, 6])
        if is_zero:
            lines.append(f'{ts:.6f} read({fd}, "", 0) = 0')
        else:
            c = RNG.randint(0, 6)
            if c == 0:
                sz = RNG.choice([1024, 2048, 4096, 8192])
                ret = RNG.randint(sz // 4, sz)
                lines.append(
                    f"{ts:.6f} read({fd}, \"\\x00\\x01\\x02\"..., {sz}) = {ret}"
                )
            elif c == 1:
                sz = RNG.choice([64, 128, 256, 512])
                lines.append(f"{ts:.6f} write({fd}, \"data\"..., {sz}) = {sz}")
            elif c == 2:
                chunk = RNG.randint(1, 999)
                lines.append(
                    f"{ts:.6f} open(\"/data/import/chunk_{chunk:03d}.dat\", O_RDONLY) = {fd}"
                )
            elif c == 3:
                lines.append(f"{ts:.6f} close({fd}) = 0")
            elif c == 4:
                lines.append(f"{ts:.6f} lseek({fd}, 0, SEEK_SET) = 0")
            elif c == 5:
                sz = RNG.randint(1000, 10000000)
                lines.append(
                    f"{ts:.6f} fstat({fd}, {{st_mode=S_IFREG|0644, st_size={sz}}}) = 0"
                )
            else:
                addr = RNG.randint(0x7F0000000, 0x7FFFFFFFFF)
                lines.append(
                    f"{ts:.6f} mmap(NULL, 4096, PROT_READ|PROT_WRITE, "
                    f"MAP_PRIVATE|MAP_ANONYMOUS, -1, 0) = 0x{addr:x}"
                )
        ts += RNG.uniform(0.00001, 0.001)
    write_file(f"{BASE}/strace/pid_{pid}.log", "\n".join(lines) + "\n")


def generate_strace_sync(pid):
    """Sync I/O writer — heavy O_SYNC writes to /data/workerd/ on sdb."""
    lines = []
    ts = 1718000000.0
    lines.append(
        f'{ts:.6f} open("/data/workerd/journal.log", O_WRONLY|O_CREAT|O_SYNC, 0644) = 4'
    )
    ts += 0.001
    for i in range(2500):
        sz = RNG.choice([4096, 8192, 16384])
        lines.append(f"{ts:.6f} write(4, \"\\x00\"..., {sz}) = {sz}")
        ts += RNG.uniform(0.001, 0.05)
        if i % 50 == 0:
            lines.append(f"{ts:.6f} lseek(4, 0, SEEK_SET) = 0")
            ts += 0.0001
        if i % 100 == 0:
            ns = RNG.randint(0, 999999999)
            lines.append(
                f"{ts:.6f} clock_gettime(CLOCK_MONOTONIC, "
                f"{{tv_sec={int(ts)}, tv_nsec={ns}}}) = 0"
            )
            ts += 0.0001
        if i % 200 == 0:
            # Periodic reads from data directory showing sdb usage
            lines.append(
                f'{ts:.6f} open("/data/workerd/state_{i:04d}.dat", O_RDONLY) = 7'
            )
            ts += 0.0001
            rsz = RNG.choice([4096, 8192, 16384, 32768])
            lines.append(
                f'{ts:.6f} read(7, "\\x00"..., {rsz}) = {rsz}'
            )
            ts += 0.0001
            lines.append(f"{ts:.6f} close(7) = 0")
            ts += 0.0001
    write_file(f"{BASE}/strace/pid_{pid}.log", "\n".join(lines) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# SYSTEM STATE SNAPSHOTS
# ═══════════════════════════════════════════════════════════════════════════
TIMESTAMPS = [1718000000, 1718000005, 1718000010, 1718000015, 1718000020]

PROCESSES = {
    1001: {
        "name": "systemd",
        "rss": [5120, 5120, 5120, 5120, 5120],
        "state": "S",
        "threads": 1,
    },
    3156: {
        "name": "workerd",
        "rss": [51200, 89344, 127488, 165632, 204800],
        "state": "S",
        "threads": 16,
    },
    4821: {
        "name": "nginx",
        "rss": [32000, 32100, 31900, 32050, 31950],
        "state": "S",
        "threads": 8,
    },
    7293: {
        "name": "dataimporter",
        "rss": [28000, 28200, 27800, 28100, 27900],
        "state": "R",
        "threads": 4,
    },
    8450: {
        "name": "redis-server",
        "rss": [85000, 85100, 84900, 85200, 84800],
        "state": "S",
        "threads": 6,
    },
}

# /proc/diskstats: major minor name then 11 stat fields
# Fields: rd_ios rd_merges rd_sectors rd_ticks wr_ios wr_merges wr_sectors
#         wr_ticks ios_inflight io_ticks weighted_io_ticks
DISKS = {
    "sda": {
        "major": 8,
        "minor": 0,
        "base": [50000, 1000, 800000, 25000, 30000, 500, 600000, 20000, 0, 30000, 50000],
        "incr": [500, 10, 8000, 250, 300, 5, 6000, 200, 0, 400, 10000],
    },
    "sdb": {
        "major": 8,
        "minor": 16,
        "base": [
            200000, 5000, 3200000, 100000,
            180000, 4000, 2800000, 90000,
            0, 120000, 100000,
        ],
        "incr": [3000, 80, 48000, 1500, 2400, 60, 36000, 1200, 0, 2000, 42650],
    },
    "sdc": {
        "major": 8,
        "minor": 32,
        "base": [5000, 200, 40000, 2500, 3000, 100, 24000, 1500, 0, 3000, 10000],
        "incr": [50, 2, 400, 25, 30, 1, 240, 15, 0, 40, 1250],
    },
}

NET = {
    "lo": {
        "base": [1234567, 12345, 0, 0, 0, 0, 0, 0, 1234567, 12345, 0, 0, 0, 0, 0, 0],
        "incr": [5000, 50, 0, 0, 0, 0, 0, 0, 5000, 50, 0, 0, 0, 0, 0, 0],
    },
    "eth0": {
        "base": [
            987654321, 654321, 45, 3, 0, 0, 0, 0,
            876543210, 543210, 23, 1, 0, 0, 0, 0,
        ],
        "incr": [4500000, 3000, 4, 0, 0, 0, 0, 0, 3800000, 2500, 2, 0, 0, 0, 0, 0],
    },
    "eth1": {
        "base": [
            543210000, 432100, 1500, 200, 0, 0, 0, 0,
            432100000, 321000, 620, 100, 0, 0, 0, 0,
        ],
        "incr": [
            2700000, 2100, 450, 64, 0, 0, 0, 0,
            2160000, 1680, 150, 33, 0, 0, 0, 0,
        ],
    },
}


def proc_status_text(pid, name, rss_kb, state, threads):
    vmsize = rss_kb * 3
    return (
        f"Name:\t{name}\n"
        f"Umask:\t0022\n"
        f"State:\t{state} (sleeping)\n"
        f"Tgid:\t{pid}\n"
        f"Ngid:\t0\n"
        f"Pid:\t{pid}\n"
        f"PPid:\t1\n"
        f"TracerPid:\t0\n"
        f"Uid:\t1000\t1000\t1000\t1000\n"
        f"Gid:\t1000\t1000\t1000\t1000\n"
        f"FDSize:\t256\n"
        f"Groups:\t1000\n"
        f"VmPeak:\t{vmsize + 10000} kB\n"
        f"VmSize:\t{vmsize} kB\n"
        f"VmLck:\t0 kB\n"
        f"VmPin:\t0 kB\n"
        f"VmHWM:\t{rss_kb + 5000} kB\n"
        f"VmRSS:\t{rss_kb} kB\n"
        f"RssAnon:\t{max(rss_kb - 2000, 0)} kB\n"
        f"RssFile:\t1500 kB\n"
        f"RssShmem:\t500 kB\n"
        f"VmData:\t{max(vmsize - 50000, 1000)} kB\n"
        f"VmStk:\t132 kB\n"
        f"VmExe:\t2048 kB\n"
        f"VmLib:\t12000 kB\n"
        f"VmPTE:\t512 kB\n"
        f"VmSwap:\t0 kB\n"
        f"HugetlbPages:\t0 kB\n"
        f"CoreDumping:\t0\n"
        f"THP_enabled:\t1\n"
        f"Threads:\t{threads}\n"
        f"SigQ:\t1/63322\n"
        f"SigPnd:\t0000000000000000\n"
        f"ShdPnd:\t0000000000000000\n"
        f"SigBlk:\t0000000000000000\n"
        f"SigIgn:\t0000000000001000\n"
        f"SigCgt:\t0000000180014a07\n"
        f"CapInh:\t0000000000000000\n"
        f"CapPrm:\t0000000000000000\n"
        f"CapEff:\t0000000000000000\n"
        f"CapBnd:\t000001ffffffffff\n"
        f"CapAmb:\t0000000000000000\n"
        f"voluntary_ctxt_switches:\t{pid * 100}\n"
        f"nonvoluntary_ctxt_switches:\t{pid * 10}\n"
    )


def generate_snapshots():
    for idx, ts in enumerate(TIMESTAMPS):
        snap_dir = f"{BASE}/snapshots/t{idx}_{ts}"

        # Process status files
        for pid, pdata in PROCESSES.items():
            content = proc_status_text(
                pid, pdata["name"], pdata["rss"][idx], pdata["state"], pdata["threads"]
            )
            write_file(f"{snap_dir}/processes/{pid}_status", content)

        # /proc/diskstats
        disk_lines = []
        for devname, ddata in DISKS.items():
            fields = [ddata["base"][j] + ddata["incr"][j] * idx for j in range(11)]
            disk_lines.append(
                f"   {ddata['major']:>3}       {ddata['minor']:>2} {devname} "
                + " ".join(str(f) for f in fields)
            )
        write_file(f"{snap_dir}/proc_diskstats", "\n".join(disk_lines) + "\n")

        # /proc/net/dev
        hdr1 = (
            "Inter-|   Receive                                   "
            "             |  Transmit"
        )
        hdr2 = (
            " face |bytes    packets errs drop fifo frame compressed "
            "multicast|bytes    packets errs drop fifo colls carrier compressed"
        )
        net_lines = [hdr1, hdr2]
        for iface, ndata in NET.items():
            fields = [ndata["base"][j] + ndata["incr"][j] * idx for j in range(16)]
            rx_str = " ".join(f"{v:>12}" for v in fields[:8])
            tx_str = " ".join(f"{v:>12}" for v in fields[8:])
            net_lines.append(f"{iface:>6}: {rx_str} {tx_str}")
        write_file(f"{snap_dir}/proc_net_dev", "\n".join(net_lines) + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    os.makedirs(BASE, exist_ok=True)
    generate_readme()
    generate_perf_script()
    generate_strace_normal(4821)
    generate_strace_pathological(7293)
    generate_strace_sync(3156)
    generate_snapshots()
    print(f"Incident data generated at {BASE}")
